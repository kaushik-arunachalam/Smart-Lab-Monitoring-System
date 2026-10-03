/*
 * ============================================================================
 *  Smart Laboratory Environment Monitoring System
 *  An IoT based embedded system with AI-driven environmental safety analysis
 *  M.A. Kaushik (CH.SC.U4CSE24123)  |  Deepak SN (CH.SC.U4CSE24112)
 * ============================================================================
 *  Board    : ESP32 DevKit-C (runs in the Wokwi simulator)
 *  Sensors  : DHT22 (temperature, humidity), MQ-135 (air quality, CO2-eq ppm),
 *             PIR (occupancy), LDR (ambient light, lux)
 *  Outputs  : 0.96" SSD1306 OLED, relay -> exhaust fan, buzzer,
 *             green / yellow / red status LEDs
 *  AI       : on-device neural network (model.h, trained in ml/) predicts the
 *             worst lab status in the NEXT 10 MINUTES from current readings
 *             and 10-minute trends -> pre-emptive ventilation + early alerts
 *  IoT      : Wi-Fi -> MQTT live data (web/mobile dashboard)
 *             -> ThingSpeak cloud database (optional, API key)
 *             -> Telegram notifications (optional, bot token)
 *
 *  Status rules (same as the ML training labels)
 *    CRITICAL : T > 32 or T < 15 C, RH > 70 or < 20 %, air > 2000 ppm
 *    WARNING  : T > 27 or T < 18 C, RH > 60 or < 30 %, air > 1000 ppm,
 *               or lab occupied with light < 150 lux
 *    SAFE     : otherwise
 *
 *  Button (GPIO 4): short press = mute buzzer 60 s, long press (2 s) = test
 * ============================================================================
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include <DHTesp.h>
#include <time.h>
#include "model.h"

// ------------------------------- Pins ---------------------------------------
const int PIN_DHT        = 15;
const int PIN_MQ135      = 34;   // analog (ADC1)
const int PIN_LDR        = 35;   // analog (ADC1)
const int PIN_PIR        = 27;
const int PIN_RELAY_FAN  = 26;
const int PIN_BUZZER     = 13;
const int PIN_LED_GREEN  = 25;
const int PIN_LED_YELLOW = 33;
const int PIN_LED_RED    = 32;
const int PIN_BUTTON     = 4;
// OLED: SDA 21, SCL 22

// ------------------------------- Settings -----------------------------------
// One "model minute" (the time step the ML model was trained on).
// 60000 on real hardware; 3000 in the simulator so trends develop quickly.
const unsigned long MODEL_MINUTE_MS = 3000;
const unsigned long SENSOR_MS       = 1000;
const unsigned long OLED_MS         = 500;
const unsigned long MQTT_MS         = 3000;
const unsigned long CLOUD_MS        = 20000;   // ThingSpeak free limit: 15 s
const unsigned long OCCUPIED_HOLD_MS= 60000;   // occupied if motion in last 60 s (use 5 min on hardware)
const unsigned long MUTE_MS         = 60000;
const unsigned long NOTIFY_GAP_MS   = 60000;   // min gap between Telegram messages
const float ML_CRITICAL_PROB        = 0.60;    // confidence needed for pre-emptive action
const unsigned long STATUS_HOLD_MS  = 5 * MODEL_MINUTE_MS; // status must stay lower this long before it drops (no flapping)

// ------------------------------- Network ------------------------------------
const char* WIFI_SSID  = "Wokwi-GUEST";
const char* WIFI_PASS  = "";
const char* MQTT_HOST  = "broker.hivemq.com";
const char* DEVICE_ID  = "smartlab-cse24";     // must match the dashboard
const char* TZ_INFO    = "IST-5:30";           // POSIX TZ string (change if needed)
// Optional cloud database (https://thingspeak.com -> channel with 8 fields)
const char* THINGSPEAK_API_KEY = "";           // Write API key, leave "" to disable
// Optional Telegram alerts (@BotFather -> token, @userinfobot -> chat id)
const char* TELEGRAM_BOT_TOKEN = "";
const char* TELEGRAM_CHAT_ID   = "";

// ------------------------------- MQ-135 model -------------------------------
// ppm = PARA * (Rs/R0)^-PARB  (CO2 curve), R0 calibrated in fresh air (~420 ppm)
const float MQ_VC = 5.0, MQ_RL = 10.0, ADC_VREF = 3.3, DIVIDER = 1.0; // DIVIDER 1.5 on hardware
const float MQ_PARA = 116.6020682, MQ_PARB = 2.769034857, FRESH_AIR_PPM = 420.0;
float mqR0 = 76.63;

// ------------------------------- Objects ------------------------------------
Adafruit_SSD1306 oled(128, 64, &Wire, -1);
DHTesp dht;
WiFiClient netClient;
PubSubClient mqtt(netClient);

// ------------------------------- State --------------------------------------
enum Status { SAFE = 0, WARNING = 1, CRITICAL = 2 };
const char* STATUS_NAME[] = {"SAFE", "WARNING", "CRITICAL"};

float tempC = 24, humidity = 45, airPpm = 420, lux = 300;
float aqFiltered = -1;
bool  occupied = false;
unsigned long lastMotion = 0;
Status status = SAFE;
String reason = "Environment Stable";

// ML
const int HIST = 11;                       // 10-minute trend window
float histT[HIST], histH[HIST], histA[HIST];
int   histCount = 0, histHead = 0;
float slopeT = 0, slopeH = 0, slopeA = 0;
float mlProb[3] = {1, 0, 0};
int   mlClass = SAFE;
bool  mlEarlyWarning = false;              // AI predicts CRITICAL before it happens
bool  mlSelfTestOk = false;

// actuators
bool fanOn = false, fanManual = false, buzzerOn = false, muted = false;
unsigned long mutedUntil = 0, testUntil = 0;
bool cloudOk = false;
unsigned long lastNotify = 0;
Status lastNotifiedStatus = SAFE;
bool lastNotifiedEarly = false;
unsigned long tSensor = 0, tModel = 0, tOled = 0, tMqtt = 0, tCloud = 0, tWifi = 0, tMqttTry = 0;

// ============================================================================
//  Sensors
// ============================================================================
float mqRs(int raw) {
  float v = raw / 4095.0f * ADC_VREF * DIVIDER;
  v = constrain(v, 0.01f, MQ_VC - 0.01f);
  return MQ_RL * (MQ_VC - v) / v;
}

void calibrateMq135() {
  float sum = 0;
  for (int i = 0; i < 30; i++) { sum += mqRs(analogRead(PIN_MQ135)); delay(20); }
  float rs = sum / 30;
  mqR0 = rs / powf(FRESH_AIR_PPM / MQ_PARA, -1.0f / MQ_PARB);
  Serial.printf("[CAL] MQ-135 R0 = %.2f kOhm\n", mqR0);
}

float readLux() {
  // Wokwi / common LDR module formula (10k fixed resistor, GL5528-type LDR)
  const float GAMMA = 0.7, RL10 = 50;
  float v = analogRead(PIN_LDR) / 4095.0f * 3.3f;
  v = constrain(v, 0.01f, 3.29f);
  float r = 2000 * v / (1 - v / 3.3f);
  return powf(RL10 * 1e3 * powf(10, GAMMA) / r, 1 / GAMMA);
}

void readSensors(unsigned long now) {
  static unsigned long tDht = 0;           // DHT22 needs >= 2 s between reads
  if (tDht == 0 || now - tDht >= 2000) {
    tDht = now;
    TempAndHumidity th = dht.getTempAndHumidity();
    if (dht.getStatus() == DHTesp::ERROR_NONE) { tempC = th.temperature; humidity = th.humidity; }
  }

  int raw = analogRead(PIN_MQ135);
  if (aqFiltered < 0) aqFiltered = raw;
  aqFiltered = 0.7f * aqFiltered + 0.3f * raw;
  airPpm = constrain(MQ_PARA * powf(mqRs(aqFiltered) / mqR0, -MQ_PARB), 300.0f, 10000.0f);

  lux = readLux();
  if (digitalRead(PIN_PIR) == HIGH) lastMotion = now;
  occupied = lastMotion != 0 && (now - lastMotion) < OCCUPIED_HOLD_MS;
}

const char* airLabel(float ppm) {
  if (ppm < 800) return "Good";
  if (ppm < 1000) return "Moderate";
  if (ppm < 2000) return "Poor";
  return "Hazardous";
}

// ============================================================================
//  Rule-based status (deterministic safety layer)
// ============================================================================
Status evaluateStatus(String& reason) {
  if (tempC > 32) { reason = "High temperature!"; return CRITICAL; }
  if (tempC < 15) { reason = "Low temperature!"; return CRITICAL; }
  if (humidity > 70) { reason = "Humidity too high!"; return CRITICAL; }
  if (humidity < 20) { reason = "Humidity too low!"; return CRITICAL; }
  if (airPpm > 2000) { reason = "Hazardous air!"; return CRITICAL; }
  if (airPpm > 1000) { reason = "Poor air quality"; return WARNING; }
  if (tempC > 27 || tempC < 18) { reason = "Temperature abnormal"; return WARNING; }
  if (humidity > 60 || humidity < 30) { reason = "Humidity abnormal"; return WARNING; }
  if (occupied && lux < 150) { reason = "Insufficient light"; return WARNING; }
  reason = (!occupied && lux > 300) ? "Lab empty, lights on" : "Environment Stable";
  return SAFE;
}

// ============================================================================
//  AI prediction (TinyML, runs on the ESP32)
// ============================================================================
void updateModel() {
  histT[histHead] = tempC; histH[histHead] = humidity; histA[histHead] = airPpm;
  histHead = (histHead + 1) % HIST;
  if (histCount < HIST) histCount++;
  int newest = (histHead - 1 + HIST) % HIST;
  int oldest = histCount < HIST ? 0 : histHead;
  float span = histCount - 1;
  if (span >= 1) {
    slopeT = (histT[newest] - histT[oldest]) / span;
    slopeH = (histH[newest] - histH[oldest]) / span;
    slopeA = (histA[newest] - histA[oldest]) / span;
  }
  float x[ML_N_FEATURES] = {tempC, humidity, airPpm, occupied ? 1.0f : 0.0f, lux, slopeT, slopeA, slopeH};
  mlClass = ml_predict(x, mlProb);
  mlEarlyWarning = mlClass == CRITICAL && mlProb[CRITICAL] >= ML_CRITICAL_PROB && status != CRITICAL;
}

void mlSelfTest() {
  float p[3], maxErr = 0;
  for (int t = 0; t < ML_N_TESTS; t++) {
    ml_predict(&ML_TEST_X[t * ML_N_FEATURES], p);
    for (int c = 0; c < 3; c++) maxErr = max(maxErr, fabsf(p[c] - ML_TEST_P[t * 3 + c]));
  }
  mlSelfTestOk = maxErr < 1e-3;
  Serial.printf("[AI] model self-test %s (max error %.6f)\n", mlSelfTestOk ? "PASSED" : "FAILED", maxErr);
}

// ============================================================================
//  Actuators
// ============================================================================
void applyOutputs(unsigned long now) {
  if (now < testUntil) {                           // self-test animation
    int ph = (now / 300) % 3;
    digitalWrite(PIN_LED_GREEN, ph == 0); digitalWrite(PIN_LED_YELLOW, ph == 1); digitalWrite(PIN_LED_RED, ph == 2);
    digitalWrite(PIN_RELAY_FAN, HIGH); tone(PIN_BUZZER, 800 + 300 * ph);
    return;
  }
  bool blink = (now / 400) % 2;
  digitalWrite(PIN_LED_GREEN,  status == SAFE && !mlEarlyWarning);
  digitalWrite(PIN_LED_YELLOW, status == WARNING || (mlEarlyWarning && blink));
  digitalWrite(PIN_LED_RED,    status == CRITICAL && blink);

  // Exhaust fan: same rule as the training data controller + AI pre-emptive start
  bool airOrHeat = airPpm > 900 || tempC > 26.5 || humidity > 58;
  fanOn = fanManual || (status >= WARNING && airOrHeat) || mlEarlyWarning;
  digitalWrite(PIN_RELAY_FAN, fanOn);

  if (muted && now > mutedUntil) muted = false;
  buzzerOn = false;
  if (!muted) {
    if (status == CRITICAL) { buzzerOn = true; tone(PIN_BUZZER, ((now / 300) % 2) ? 2000 : 1300); }
    else if (mlEarlyWarning && (now % 5000) < 300 && ((now % 5000) < 120 || (now % 5000) > 180)) {
      buzzerOn = true; tone(PIN_BUZZER, 1700);      // double chirp every 5 s
    }
  }
  if (!buzzerOn) noTone(PIN_BUZZER);
}

void handleButton(unsigned long now) {
  static bool last = false; static unsigned long down = 0; static bool longDone = false;
  bool pressed = digitalRead(PIN_BUTTON) == LOW;
  if (pressed && !last) { down = now; longDone = false; }
  if (pressed && !longDone && now - down > 2000) { longDone = true; testUntil = now + 3000; Serial.println("[BTN] self-test"); }
  if (!pressed && last && !longDone && now - down > 40) { muted = true; mutedUntil = now + MUTE_MS; Serial.println("[BTN] buzzer muted 60 s"); }
  last = pressed;
}

// ============================================================================
//  OLED (layout from the Phase-1 "expected output")
// ============================================================================
void drawWifiIcon(int x, int y, bool on) {
  if (!on) { oled.drawLine(x, y, x + 8, y + 7, SSD1306_WHITE); }
  oled.drawCircleHelper(x + 4, y + 7, 7, 1 | 2, SSD1306_WHITE);
  oled.drawCircleHelper(x + 4, y + 7, 4, 1 | 2, SSD1306_WHITE);
  oled.fillCircle(x + 4, y + 7, 1, SSD1306_WHITE);
}
void drawCloudIcon(int x, int y, bool ok) {
  oled.fillCircle(x + 4, y + 5, 3, SSD1306_WHITE); oled.fillCircle(x + 8, y + 3, 4, SSD1306_WHITE);
  oled.fillCircle(x + 12, y + 5, 3, SSD1306_WHITE); oled.fillRect(x + 4, y + 5, 9, 3, SSD1306_WHITE);
  if (!ok) oled.drawLine(x, y, x + 15, y + 8, SSD1306_BLACK);
}

void updateOled(unsigned long now) {
  oled.clearDisplay();
  oled.setTextColor(SSD1306_WHITE);
  oled.setTextSize(1);
  drawWifiIcon(0, 0, WiFi.status() == WL_CONNECTED);
  struct tm ti; char clk[12] = "--:--";
  if (getLocalTime(&ti, 5)) strftime(clk, sizeof(clk), "%I:%M %p", &ti);
  oled.setCursor(40, 1); oled.print(clk);
  drawCloudIcon(111, 0, mqtt.connected());
  oled.drawFastHLine(0, 9, 128, SSD1306_WHITE);

  oled.setCursor(0, 11); oled.printf("Temp    : %.1f C", tempC);
  oled.setCursor(0, 20); oled.printf("Humidity: %.0f %%", humidity);
  oled.setCursor(0, 29); oled.printf("Air     : %s %d", airLabel(airPpm), (int)airPpm);
  oled.setCursor(0, 38); oled.printf("Occupied: %s %dlx", occupied ? "YES" : "NO ", (int)lux);
  oled.setCursor(0, 47); oled.printf("Status  : %s", STATUS_NAME[status]);
  oled.drawFastHLine(0, 55, 128, SSD1306_WHITE);

  String msg = mlEarlyWarning ? String("AI:CRITICAL in 10m!") : reason;
  if (msg.length() > 21) msg = msg.substring(0, 21);
  bool invert = status == CRITICAL || mlEarlyWarning;
  if (invert) oled.fillRect(0, 56, 128, 8, SSD1306_WHITE);
  oled.setTextColor(invert ? SSD1306_BLACK : SSD1306_WHITE);
  oled.setCursor((128 - msg.length() * 6) / 2, 57); oled.print(msg);
  oled.display();
}

// ============================================================================
//  IoT: MQTT (live), ThingSpeak (cloud DB), Telegram (notifications)
// ============================================================================
String topic(const char* leaf) { return String("smartlab/") + DEVICE_ID + "/" + leaf; }

void publishData() {
  if (!mqtt.connected()) return;
  char buf[640];
  time_t ts; time(&ts);
  snprintf(buf, sizeof(buf),
    "{\"id\":\"%s\",\"ts\":%ld,\"temp\":%.1f,\"hum\":%.1f,\"aq\":%d,\"aqLabel\":\"%s\",\"occ\":%s,"
    "\"lux\":%d,\"status\":\"%s\",\"reason\":\"%s\",\"pred\":\"%s\",\"pSafe\":%.3f,\"pWarn\":%.3f,"
    "\"pCrit\":%.3f,\"early\":%s,\"slopeT\":%.3f,\"slopeA\":%.1f,\"fan\":%s,\"fanManual\":%s,"
    "\"buzzer\":%s,\"muted\":%s,\"cloud\":%s,\"rssi\":%d,\"uptime\":%lu}",
    DEVICE_ID, (long)ts, tempC, humidity, (int)airPpm, airLabel(airPpm), occupied ? "true" : "false",
    (int)lux, STATUS_NAME[status], reason.c_str(), STATUS_NAME[mlClass], mlProb[0], mlProb[1],
    mlProb[2], mlEarlyWarning ? "true" : "false", slopeT, slopeA, fanOn ? "true" : "false",
    fanManual ? "true" : "false", buzzerOn ? "true" : "false", muted ? "true" : "false",
    cloudOk ? "true" : "false", WiFi.RSSI(), millis() / 1000);
  mqtt.publish(topic("data").c_str(), buf);
}

String urlEncode(const String& s) {
  String o; char hex[4];
  for (char c : s) {
    if (isalnum(c) || c == '-' || c == '_' || c == '.') o += c;
    else { snprintf(hex, sizeof(hex), "%%%02X", (uint8_t)c); o += hex; }
  }
  return o;
}

void notify(const String& msg) {
  Serial.println("[NOTIFY] " + msg);
  if (mqtt.connected()) {
    String j = String("{\"status\":\"") + STATUS_NAME[status] + "\",\"msg\":\"" + msg + "\"}";
    mqtt.publish(topic("alert").c_str(), j.c_str());
  }
  if (strlen(TELEGRAM_BOT_TOKEN) == 0 || WiFi.status() != WL_CONNECTED) return;
  WiFiClientSecure tls; tls.setInsecure();
  HTTPClient http;
  String url = String("https://api.telegram.org/bot") + TELEGRAM_BOT_TOKEN +
               "/sendMessage?chat_id=" + TELEGRAM_CHAT_ID + "&text=" + urlEncode("[Smart Lab] " + msg);
  if (http.begin(tls, url)) { int code = http.GET(); Serial.printf("[TELEGRAM] HTTP %d\n", code); http.end(); }
}

void checkNotifications(unsigned long now) {
  bool escalate = status > lastNotifiedStatus;
  bool early = mlEarlyWarning && !lastNotifiedEarly;
  bool recovered = status == SAFE && lastNotifiedStatus != SAFE;
  if (!(escalate || early || recovered)) {
    if (!mlEarlyWarning) lastNotifiedEarly = false;
    return;
  }
  if (now - lastNotify < NOTIFY_GAP_MS && !escalate && lastNotify != 0) return;
  char m[160];
  if (escalate)
    snprintf(m, sizeof(m), "%s: %s | T %.1fC RH %.0f%% Air %dppm", STATUS_NAME[status], reason.c_str(), tempC, humidity, (int)airPpm);
  else if (early)
    snprintf(m, sizeof(m), "AI EARLY WARNING: CRITICAL expected within 10 min (p=%.0f%%). Fan started.", mlProb[2] * 100);
  else
    snprintf(m, sizeof(m), "Back to SAFE. T %.1fC RH %.0f%% Air %dppm", tempC, humidity, (int)airPpm);
  notify(m);
  lastNotify = now;
  lastNotifiedStatus = status;
  lastNotifiedEarly = mlEarlyWarning;
}

void uploadCloud() {
  if (strlen(THINGSPEAK_API_KEY) == 0 || WiFi.status() != WL_CONNECTED) { cloudOk = false; return; }
  WiFiClient httpNet;                      // separate socket: netClient belongs to MQTT
  HTTPClient http;
  char url[300];
  snprintf(url, sizeof(url),
    "http://api.thingspeak.com/update?api_key=%s&field1=%.1f&field2=%.1f&field3=%d&field4=%d"
    "&field5=%d&field6=%d&field7=%d&field8=%.3f",
    THINGSPEAK_API_KEY, tempC, humidity, (int)airPpm, occupied ? 1 : 0, (int)lux, (int)status, mlClass, mlProb[2]);
  http.begin(httpNet, url);
  int code = http.GET();
  cloudOk = code == 200 && http.getString().toInt() > 0;
  http.end();
  Serial.printf("[CLOUD] ThingSpeak %s (HTTP %d)\n", cloudOk ? "OK" : "failed", code);
}

void onCommand(char*, byte* payload, unsigned int len) {
  String c; for (unsigned i = 0; i < len; i++) c += (char)payload[i];
  c.trim();
  Serial.println("[CMD] " + c);
  if (c == "fan_on") fanManual = true;
  else if (c == "fan_auto") fanManual = false;
  else if (c == "mute") { muted = true; mutedUntil = millis() + MUTE_MS; }
  else if (c == "test") testUntil = millis() + 3000;
  publishData();
}

void handleNetwork(unsigned long now) {
  if (WiFi.status() != WL_CONNECTED) {
    if (now - tWifi > 10000) { tWifi = now; WiFi.disconnect(); WiFi.begin(WIFI_SSID, WIFI_PASS, 6); }
    return;
  }
  if (!mqtt.connected()) {
    if (now - tMqttTry > 5000) {
      tMqttTry = now;
      String cid = String("smartlab-") + String((uint32_t)ESP.getEfuseMac(), HEX);
      if (mqtt.connect(cid.c_str(), topic("data").c_str(), 0, true, "{\"offline\":true}")) {
        mqtt.subscribe(topic("cmd").c_str());
        Serial.println("[NET] MQTT connected");
      }
    }
    return;
  }
  mqtt.loop();
}

// ============================================================================
void setup() {
  Serial.begin(115200);
  pinMode(PIN_PIR, INPUT);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  for (int p : {PIN_RELAY_FAN, PIN_BUZZER, PIN_LED_GREEN, PIN_LED_YELLOW, PIN_LED_RED}) pinMode(p, OUTPUT);
  analogReadResolution(12);
  analogSetPinAttenuation(PIN_MQ135, ADC_11db);
  analogSetPinAttenuation(PIN_LDR, ADC_11db);

  if (!oled.begin(SSD1306_SWITCHCAPVCC, 0x3C)) Serial.println("[OLED] not found");
  oled.clearDisplay(); oled.setTextColor(SSD1306_WHITE); oled.setTextSize(1);
  oled.setCursor(10, 10); oled.print("Smart Lab Monitor");
  oled.setCursor(10, 30); oled.print("Calibrating...");
  oled.display();

  dht.setup(PIN_DHT, DHTesp::DHT22);
  for (int p : {PIN_LED_GREEN, PIN_LED_YELLOW, PIN_LED_RED}) { digitalWrite(p, HIGH); delay(150); digitalWrite(p, LOW); }
  tone(PIN_BUZZER, 1500); delay(80); noTone(PIN_BUZZER);
  calibrateMq135();
  mlSelfTest();

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS, 6);
  tWifi = millis();
  configTzTime(TZ_INFO, "pool.ntp.org", "time.google.com");
  mqtt.setServer(MQTT_HOST, 1883);
  mqtt.setCallback(onCommand);
  mqtt.setBufferSize(768);
  Serial.printf("[BOOT] MQTT topics: smartlab/%s/{data,alert,cmd}\n", DEVICE_ID);
}

void loop() {
  unsigned long now = millis();
  if (now - tSensor >= SENSOR_MS) {
    tSensor = now;
    readSensors(now);
    // escalate immediately, de-escalate only after STATUS_HOLD_MS (hysteresis in time)
    static unsigned long lowerSince = 0;
    String r;
    Status raw = evaluateStatus(r);
    if (raw >= status) { status = raw; reason = r; lowerSince = 0; }
    else if (lowerSince == 0) lowerSince = now;
    else if (now - lowerSince >= STATUS_HOLD_MS) { status = raw; reason = r; lowerSince = 0; }
  }
  if (now - tModel >= MODEL_MINUTE_MS) {
    tModel = now;
    updateModel();
    Serial.printf("T=%.1f RH=%.0f AQ=%d(%s) occ=%d lux=%d | status=%s | AI next10min=%s p=[%.2f %.2f %.2f] slopeT=%.2f slopeA=%.1f | fan=%d\n",
                  tempC, humidity, (int)airPpm, airLabel(airPpm), occupied, (int)lux, STATUS_NAME[status],
                  STATUS_NAME[mlClass], mlProb[0], mlProb[1], mlProb[2], slopeT, slopeA, fanOn);
  }
  handleButton(now);
  applyOutputs(now);
  checkNotifications(now);
  if (now - tOled >= OLED_MS) { tOled = now; updateOled(now); }
  handleNetwork(now);
  if (now - tMqtt >= MQTT_MS) { tMqtt = now; publishData(); }
  if (now - tCloud >= CLOUD_MS) { tCloud = now; uploadCloud(); }
}
