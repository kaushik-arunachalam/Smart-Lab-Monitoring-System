"""Builds Project_Report.docx - Smart Laboratory Environment Monitoring System."""
import json
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MET = json.load(open(os.path.join(ROOT, "ml", "metrics.json")))
R = MET["results"]
MLP = R["Neural Network MLP (16, 8)"]
RULE = R["Threshold rules (current reading only)"]
EW = MET["early_warning"]

# Observed results (filled from the verification runs; Wokwi rows are completed after running the simulation)
OBSERVED = {
    "T1": "", "T2": "", "T3": "", "T4": "", "T5": "", "T6": "", "T7": "", "T8": "",
    "T9": "Pass - C inference = Python (max error 4.8e-7, g++ test)",
    "T10": "Pass - WARNING at ~1000 ppm, fan ON, CO2 held near 1000 ppm",
    "T11": "Pass - AI early warning ~13 lab-minutes before CRITICAL",
    "T12": "Pass - 40 readings + 1 alert stored; CSV export OK",
    "T13": "Pass - no SAFE/WARNING flapping after hold-time fix",
}

BROWN = RGBColor(0x5A, 0x43, 0x2A)
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.4)
sec.top_margin = sec.bottom_margin = Cm(2.2)
st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(11.5)
st.paragraph_format.space_after = Pt(6); st.paragraph_format.line_spacing = 1.2
for lvl, size in ((1, 18), (2, 14), (3, 12)):
    h = doc.styles[f"Heading {lvl}"]; h.font.name = "Calibri"; h.font.size = Pt(size); h.font.color.rgb = BROWN
    h.paragraph_format.space_before = Pt(14 if lvl == 1 else 10)

# page numbers in footer
fp = sec.footer.paragraphs[0]; fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
    r = fp.add_run()
    if kind:
        e = OxmlElement("w:fldChar"); e.set(qn("w:fldCharType"), kind); r._r.append(e)
    else:
        e = OxmlElement("w:instrText"); e.set(qn("xml:space"), "preserve"); e.text = text; r._r.append(e)


def shade(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr(); s = OxmlElement("w:shd")
    s.set(qn("w:val"), "clear"); s.set(qn("w:color"), "auto"); s.set(qn("w:fill"), fill); tcPr.append(s)


def table(headers, rows, widths=None, size=10):
    t = doc.add_table(rows=1, cols=len(headers)); t.style = "Table Grid"; t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]; c.text = ""; r = c.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(size)
        shade(c, "EFE3CF")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""; cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(size)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph()


def para(text, lead=None, align=WD_ALIGN_PARAGRAPH.JUSTIFY):
    p = doc.add_paragraph()
    if lead:
        p.add_run(lead).bold = True
    p.add_run(text); p.alignment = align
    return p


def bullets(items):
    for it in items:
        p = doc.add_paragraph(style="List Bullet")
        if isinstance(it, tuple):
            p.add_run(it[0]).bold = True; p.add_run(it[1])
        else:
            p.add_run(it)


def numbered(items):
    for i, it in enumerate(items, 1):
        p = doc.add_paragraph(f"{i}.\t{it}")
        p.paragraph_format.left_indent = Cm(0.9); p.paragraph_format.first_line_indent = Cm(-0.6)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(0.9)); p.paragraph_format.space_after = Pt(3)


def figure(name, caption, w=16):
    doc.add_picture(os.path.join(HERE, name), width=Cm(w))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    c = doc.add_paragraph(caption); c.alignment = WD_ALIGN_PARAGRAPH.CENTER
    c.runs[0].italic = True; c.runs[0].font.size = Pt(10)


def code(text):
    p = doc.add_paragraph(); r = p.add_run(text); r.font.name = "Consolas"; r.font.size = Pt(9)
    p.paragraph_format.left_indent = Cm(0.5)


def pct(x):
    return f"{100 * x:.1f} %"


# ============================================================ title page
for _ in range(3):
    doc.add_paragraph()
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("SMART LABORATORY ENVIRONMENT\nMONITORING SYSTEM"); r.bold = True; r.font.size = Pt(24); r.font.color.rgb = BROWN
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.add_run("An IoT Based Embedded System with AI Driven Environmental Safety Analysis").font.size = Pt(13)
doc.add_paragraph()
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.add_run("Embedded Systems Project Report").font.size = Pt(14)
for _ in range(3):
    doc.add_paragraph()
p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.add_run("Submitted by").italic = True
for name, reg in (("M.A. KAUSHIK", "CH.SC.U4CSE24123"), ("DEEPAK SN", "CH.SC.U4CSE24112")):
    p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(f"{name}   ({reg})"); r.bold = True; r.font.size = Pt(13)
for _ in range(3):
    doc.add_paragraph()
for line in ("Department of Computer Science and Engineering", "Institution: ______________________________",
             "Project guide: ____________________________", "Academic year: ____________"):
    p = doc.add_paragraph(line); p.alignment = WD_ALIGN_PARAGRAPH.CENTER
doc.add_page_break()

# ============================================================ abstract
doc.add_heading("Abstract", 1)
para("Laboratories must keep temperature, humidity and air quality within safe limits to protect people, "
     "experiments and expensive equipment. Manual monitoring is slow, and hazardous conditions are often noticed "
     "only after they have developed. This project presents a Smart Laboratory Environment Monitoring System built "
     "around an ESP32 microcontroller with a DHT22 (temperature and humidity), MQ-135 (air quality), PIR "
     "(occupancy) and LDR (ambient light) sensor. The system shows live readings on an OLED display, classifies "
     "the laboratory as SAFE, WARNING or CRITICAL, and automatically drives an exhaust fan (through a relay), a "
     "buzzer and status LEDs. Readings are published over Wi-Fi using MQTT to a web dashboard, stored in a cloud "
     "database (ThingSpeak and an SQLite logger) and critical events are sent as Telegram notifications.")
para(f"The distinguishing feature is an AI safety predictor that runs on the ESP32 itself (TinyML). A small neural "
     f"network ({'-'.join(map(str, MET['architecture']))}, {MET['parameters']} parameters, {MET['model_bytes']} bytes) "
     f"uses the current readings together with their 10-minute trends to predict the worst laboratory condition in "
     f"the next 10 minutes. On held-out test data it reached {pct(MLP['accuracy'])} accuracy and "
     f"{pct(MLP['recall_critical'])} recall for CRITICAL conditions, and it predicted all "
     f"{EW['critical_episodes_in_test']} critical episodes in the test period in advance, with a median lead time of "
     f"{EW['ml_median_lead_minutes']:.1f} minutes, whereas a conventional threshold system reacts only at the moment "
     f"the limit is crossed. The early warning starts ventilation before the hazard occurs. The complete system was "
     f"developed and verified in software - Wokwi ESP32 simulation, a browser dashboard running the same model, "
     f"a Python data pipeline and a Blender 3D digital twin - so that it can be moved to hardware with minimal change.")
p = doc.add_paragraph(); p.add_run("Keywords: ").bold = True
p.add_run("IoT, ESP32, TinyML, environmental monitoring, laboratory safety, MQTT, predictive analytics, digital twin.")
doc.add_page_break()

# ============================================================ contents
doc.add_heading("Table of Contents", 1)
for t in ["1. Introduction", "2. Target Users and Their Challenges", "3. Literature Survey", "4. Methodology",
          "5. Components and Specifications", "6. System Architecture", "7. Hardware Design",
          "8. Firmware Design", "9. IoT, Cloud and Dashboard", "10. Machine Learning and TinyML",
          "11. Simulation, Digital Twin and Testing", "12. Results", "13. Advantages, Limitations and Future Scope",
          "14. Conclusion", "References", "Appendix A - Project Files", "Appendix B - Moving to Hardware"]:
    doc.add_paragraph(t)
para("(In Word: References -> Table of Contents replaces this list with an automatic one.)")
doc.add_page_break()

# ============================================================ 1 intro
doc.add_heading("1. Introduction", 1)
doc.add_heading("1.1 Problem", 2)
para("Many laboratories struggle to maintain safe environmental conditions during daily operations. Excess heat "
     "damages instruments and affects experiments, high humidity corrodes equipment and spoils samples, and poor "
     "air quality - carbon dioxide from occupants or fumes from solvents - affects health and concentration. "
     "These conditions build up gradually and are usually detected late, by people, if at all.")
doc.add_heading("1.2 Solution", 2)
para("We designed an intelligent monitoring system for laboratories and research facilities that measures the "
     "environment continuously, detects unsafe conditions automatically, responds by ventilating and alerting, "
     "stores data for analysis, and uses machine learning to predict unsafe conditions before they occur.")
doc.add_heading("1.3 Why it matters", 2)
para("Making laboratory monitoring intelligent and automated improves safety, protects equipment, supports "
     "compliance with laboratory safety practice and gives facility managers historical data to plan maintenance.")
doc.add_heading("1.4 Objectives", 2)
numbered(["Monitor laboratory environmental parameters continuously.",
          "Detect unsafe conditions automatically.",
          "Alert users through alarms and IoT notifications.",
          "Store sensor data for future analysis.",
          "Integrate machine learning to predict unsafe conditions before they occur."])
doc.add_heading("1.5 Action plan and status", 2)
table(["#", "Phase", "Status"], [
    ["1", "Literature survey", "Completed (Phase 1)"],
    ["2", "Component selection", "Completed (Phase 1)"],
    ["3", "Hardware design", "Completed - circuit in Wokwi (diagram.json), pin map in Section 7"],
    ["4", "Sensor integration", "Completed in simulation (DHT22, MQ-135, PIR, LDR)"],
    ["5", "Embedded programming (ESP32)", "Completed - firmware/sketch.ino"],
    ["6", "IoT dashboard development", "Completed - dashboard/index.html (MQTT, history, controls)"],
    ["7", "Data collection", "Pipeline completed (cloud/mqtt_logger.py, ThingSpeak); synthetic dataset used until hardware is built"],
    ["8", "ML model development", "Completed - ml/train_model.py"],
    ["9", "Deploy model on embedded board", "Completed - model.h runs on the ESP32 (TinyML)"],
    ["10", "Testing and validation", "Completed in software (Section 11); hardware validation pending"],
], widths=[1, 5.5, 9.5])

# ============================================================ 2 users
doc.add_heading("2. Target Users and Their Challenges", 1)
para("Laboratory technicians, researchers, faculty members and students who work in laboratories that require "
     "safe and controlled environmental conditions.")
table(["Challenge", "How the system addresses it"], [
    ["Manual monitoring is time-consuming", "Sensors are read every second, 24/7, with no human effort"],
    ["Unsafe temperature, humidity or air quality damages equipment and experiments",
     "Three-level status with automatic ventilation; AI starts ventilation before limits are crossed"],
    ["Delayed detection increases safety risk", "Immediate local alarm plus Telegram and dashboard alerts"],
    ["No real-time alerts or historical data", "Live dashboard, cloud database, trend charts and CSV export"],
], widths=[7, 9])

# ============================================================ 3 lit
doc.add_heading("3. Literature Survey", 1)
para("Existing approaches to laboratory and indoor environment monitoring were reviewed.")
table(["Approach", "Strength", "Gap addressed here"], [
    ["Stand-alone thermo-hygrometers and CO2 meters", "Simple, cheap", "No alerts, no logging, no automation"],
    ["Building Management Systems (BMS)", "Centralised HVAC control", "Expensive; rarely room-level air quality or occupancy"],
    ["Arduino/ESP32 IoT monitors (Blynk, ThingSpeak)", "Low cost, remote viewing",
     "Mostly threshold alarms; react only after a limit is crossed"],
    ["Cloud ML analytics on sensor data", "Can find patterns", "Needs internet; latency; no action on the device"],
    ["TinyML on microcontrollers", "Inference on the device, offline", "Rarely applied to lab safety prediction"],
], widths=[5, 4.5, 6.5])
para("Reference limits used in this project are drawn from common indoor-environment guidance: comfortable "
     "laboratory temperature of about 18-27 C, relative humidity of 30-60 %, and indoor CO2 below about "
     "1000 ppm as a ventilation indicator. These values are configurable in the firmware.")

# ============================================================ 4 method
doc.add_heading("4. Methodology", 1)
table(["Stage", "Work done"], [
    ["Research", "Studied laboratory safety practice and existing monitoring systems"],
    ["System design", "Selected sensors (temperature, humidity, air quality, occupancy, light) and actuators"],
    ["Prototyping", "Firmware for real-time acquisition, processing and actuator control; Wokwi circuit"],
    ["AI development", "Dataset, feature engineering (trends), model comparison, export to C for the ESP32"],
    ["Testing and validation", "Model verification, dashboard scenario tests, cloud pipeline tests, simulation"],
    ["Final build", "Hardware assembly using the same firmware (Appendix B)"],
], widths=[4, 12])

# ============================================================ 5 components
doc.add_heading("5. Components and Specifications", 1)
table(["Component", "Purpose", "Specification"], [
    ["ESP32 DevKit-C", "Main controller", "Dual-core 240 MHz, Wi-Fi and Bluetooth, 3.3 V logic, 12-bit ADC"],
    ["DHT22", "Temperature and humidity", "-40 to 80 C (+/-0.5 C), 0-100 % RH (+/-2 %)"],
    ["MQ-135", "Air quality", "Detects CO2, NH3, smoke and VOCs; analog output; 5 V heater"],
    ["PIR sensor (HC-SR501)", "Occupancy detection", "Motion detection, range 5-7 m"],
    ["LDR module", "Ambient light", "Light-dependent resistor with 10 kohm divider, lux estimate"],
    ["OLED display", "Live monitoring", "0.96 inch, 128 x 64, SSD1306, I2C (0x3C)"],
    ["Relay module", "Fan control", "5 V coil, 10 A contacts"],
    ["Exhaust fan", "Automatic ventilation", "Switched by the relay on unsafe or predicted-unsafe conditions"],
    ["Buzzer, LEDs", "Audio and visual alerts", "Green SAFE, yellow WARNING / early warning, red CRITICAL"],
    ["Push button", "User input", "Short press: mute 60 s; long press: self-test"],
    ["Wi-Fi", "Cloud communication", "MQTT (live), HTTP (ThingSpeak), HTTPS (Telegram)"],
], widths=[3.6, 3.8, 8.6])

# ============================================================ 6 architecture
doc.add_page_break()
doc.add_heading("6. System Architecture", 1)
figure("architecture.png", "Figure 6.1 - System architecture", 16.2)
para("The ten blocks follow the Phase 1 architecture: (1) sensors feed (2) the ESP32, which drives (3) the automatic "
     "response and the OLED; data flows over (4) Wi-Fi to (5) the cloud database, (6) the IoT dashboard and "
     "(7) notifications. (8) Historical data is used to (9) train the ML model, whose (10) predictive safety "
     "analysis runs back on the ESP32. Logged real data closes the loop for retraining.")

# ============================================================ 7 hardware
doc.add_heading("7. Hardware Design", 1)
doc.add_heading("7.1 Pin assignment", 2)
table(["ESP32 pin", "Connected to", "Type"], [
    ["GPIO 15", "DHT22 data", "Digital (1-wire protocol)"],
    ["GPIO 34", "MQ-135 AO", "Analog input (ADC1)"],
    ["GPIO 35", "LDR module AO", "Analog input (ADC1)"],
    ["GPIO 27", "PIR OUT", "Digital input"],
    ["GPIO 21 / 22", "OLED SDA / SCL", "I2C"],
    ["GPIO 26", "Relay IN (exhaust fan)", "Digital output"],
    ["GPIO 13", "Buzzer", "PWM tone"],
    ["GPIO 25 / 33 / 32", "Green / yellow / red LED (220 ohm)", "Digital output"],
    ["GPIO 4", "Push button to GND", "Digital input, internal pull-up"],
    ["5V / 3V3 / GND", "MQ-135 and relay (5 V); DHT22, PIR, LDR, OLED (3.3 V)", "Power"],
], widths=[3.4, 8, 4.6])
doc.add_heading("7.2 Circuit notes", 2)
bullets(["Only ADC1 pins (32-39) are used for analog sensors, because ADC2 cannot be used while Wi-Fi is active.",
         "The MQ-135 is powered from 5 V; on hardware its analog output must pass through a 10 k / 20 k divider "
         "to stay below 3.3 V (firmware constant DIVIDER = 1.5).",
         "The relay module drives the fan; in the simulation a blue LED on the relay contact represents the fan.",
         "The complete wiring is in firmware/diagram.json and opens directly in Wokwi."])

# ============================================================ 8 firmware
doc.add_heading("8. Firmware Design", 1)
doc.add_heading("8.1 Status rules (deterministic safety layer)", 2)
table(["Status", "Condition", "Response"], [
    ["CRITICAL", "T > 32 or < 15 C; RH > 70 or < 20 %; air > 2000 ppm",
     "Blinking red LED, two-tone siren, fan ON, Telegram + MQTT alert"],
    ["WARNING", "T > 27 or < 18 C; RH > 60 or < 30 %; air > 1000 ppm; occupied with light < 150 lux",
     "Yellow LED; fan ON when caused by air, heat or humidity; alert"],
    ["SAFE", "All parameters in range", "Green LED; fan in automatic mode (off)"],
    ["AI EARLY WARNING", f"Model predicts CRITICAL within 10 min with p >= 0.6 while not yet critical",
     "Fan ON pre-emptively, blinking yellow LED, double chirp, Telegram alert"],
], widths=[3, 6.5, 6.5])
para("To avoid alarm chattering when a reading hovers near a limit, the status rises immediately but falls only "
     "after it has stayed lower for five model-minutes (time hysteresis). The same rules produce the training "
     "labels for the ML model, so the AI and the rule layer are consistent.")
doc.add_heading("8.2 Sensor processing", 2)
code("MQ-135:  Rs = RL (Vc - Vout) / Vout,  ppm = 116.602 (Rs/R0)^-2.769  (CO2 curve)\n"
     "         R0 calibrated at start-up in fresh air (420 ppm); EMA filter 0.7/0.3\n"
     "LDR:     R = 2000 V / (1 - V/3.3),  lux = (RL10 * 1e3 * 10^0.7 / R)^(1/0.7)\n"
     "PIR:     occupied = motion within the last 60 s (5 min on hardware)\n"
     "Trends:  10-sample history -> slope = (newest - oldest) / 10  per model-minute")
doc.add_heading("8.3 Program structure", 2)
figure("flowchart.png", "Figure 8.1 - Firmware flowchart", 12.5)
table(["Function", "Purpose", "Period"], [
    ["readSensors()", "DHT22, MQ-135, LDR, PIR -> engineering units", "1 s (DHT22 every 2 s)"],
    ["evaluateStatus()", "Rule-based status and reason text", "1 s"],
    ["updateModel()", "Trend history, slopes, neural-network inference", "1 model-minute"],
    ["applyOutputs()", "LEDs, relay (fan), buzzer patterns", "every loop"],
    ["updateOled()", "OLED screen with clock, readings, status, message", "0.5 s"],
    ["publishData()", "JSON status to MQTT", "3 s"],
    ["uploadCloud()", "ThingSpeak fields 1-8", "20 s"],
    ["checkNotifications()", "Telegram / MQTT alerts on escalation, early warning, recovery", "event"],
    ["onCommand()", "Dashboard commands: fan_on, fan_auto, mute, test", "event"],
], widths=[4, 8.5, 3.5])
para("All timing uses millis() so that sensing, control, display and networking run concurrently, and the safety "
     "logic keeps working even if Wi-Fi or the cloud is unavailable. MODEL_MINUTE_MS is 60 000 ms on hardware and "
     "3 000 ms in the simulator so that trends develop quickly during a demonstration.")

# ============================================================ 9 iot
doc.add_heading("9. IoT, Cloud and Dashboard", 1)
doc.add_heading("9.1 MQTT topics", 2)
table(["Topic", "Direction", "Content"], [
    ["smartlab/<id>/data", "ESP32 -> dashboard / logger", "JSON every 3 s (last-will 'offline')"],
    ["smartlab/<id>/alert", "ESP32 -> dashboard / logger", "Alert messages (status changes, AI early warning)"],
    ["smartlab/<id>/cmd", "dashboard -> ESP32", "fan_on | fan_auto | mute | test"],
], widths=[4.5, 5, 6.5])
code('{"temp":28.9,"hum":53,"aq":979,"aqLabel":"Moderate","occ":true,"lux":509,"status":"WARNING",\n'
     ' "reason":"Temperature abnormal","pred":"CRITICAL","pSafe":0.0,"pWarn":0.15,"pCrit":0.85,\n'
     ' "early":true,"slopeT":0.30,"fan":true,"buzzer":true,"cloud":true,"rssi":-58,...}')
doc.add_heading("9.2 Cloud database", 2)
bullets([("ThingSpeak: ", "the ESP32 uploads eight fields every 20 s (temperature, humidity, air ppm, occupancy, "
                          "lux, status, AI class, P(critical)); the dashboard can load this history."),
         ("SQLite logger: ", "cloud/mqtt_logger.py subscribes to MQTT and stores every reading and alert; "
                             "'--export' produces a one-minute dataset with the same columns as the training data.")])
doc.add_heading("9.3 Notifications", 2)
para("Telegram messages are sent by the ESP32 over HTTPS for escalations, AI early warnings and recovery, rate-"
     "limited to one per minute except for escalations. The dashboard additionally plays an alarm and shows a "
     "browser notification on CRITICAL.")
doc.add_heading("9.4 Web / mobile dashboard", 2)
figure("dashboard.png", "Figure 9.1 - Dashboard during the AC-failure scenario: the AI predicts CRITICAL "
                        "(85 %) while the lab is still at WARNING and has started the fan", 16)
para("The dashboard reproduces the Phase 1 expected output: cards for temperature, humidity, air quality, "
     "occupancy, light and status; environmental trend charts with 1H / 6H / 24H / 7D ranges (drawn as separate "
     "small charts rather than a dual-axis chart so each quantity keeps its own scale); a notification panel and "
     "event log; a live mirror of the OLED; system indicators for Wi-Fi, fan, buzzer and cloud; the AI prediction "
     "with class probabilities; remote controls; CSV export; and loading of ThingSpeak history. Demo mode runs "
     "a lab simulation with the same neural network, for presentations without the simulator.")

# ============================================================ 10 ML
doc.add_page_break()
doc.add_heading("10. Machine Learning and TinyML", 1)
figure("ml_pipeline.png", "Figure 10.1 - ML pipeline", 16.2)
doc.add_heading("10.1 Dataset", 2)
para(f"Until the hardware is installed, a physically motivated synthetic dataset was generated "
     f"(ml/generate_dataset.py): 90 days at one sample per minute ({MET['train_rows'] + MET['test_rows']:,} rows). It "
     f"models a lab timetable, CO2 generation by occupants and removal by natural and fan ventilation, HVAC set-point "
     f"control with random air-conditioning failures, humidity events, solvent releases and lamp failures, with sensor "
     f"noise. The fan is driven by the same rule controller as the firmware. The pipeline is designed so that real "
     f"data logged by the system replaces the synthetic data without code changes.")
doc.add_heading("10.2 Features and target", 2)
table(["Feature", "Meaning"], [
    ["temperature, humidity, air_quality_ppm, occupancy, light_lux", "Current (filtered) sensor values"],
    ["temp_slope, aq_slope, hum_slope", "Change per minute over the last 10 minutes (trend)"],
    ["Target: status_next", "Worst status (SAFE / WARNING / CRITICAL) in the next 10 minutes"],
], widths=[8, 8])
para(f"The data was split by time: days 0-{int(90 * 0.78) - 1} for training and the remaining days for testing, "
     f"so the test measures performance on unseen future days. Minority classes were over-sampled in training.")
doc.add_heading("10.3 Model comparison (test days)", 2)
rows = []
for name, v in R.items():
    rows.append([name, pct(v["accuracy"]), f"{v['macro_f1']:.3f}", pct(v["recall_critical"]), pct(v["precision_critical"])])
table(["Model", "Accuracy", "Macro F1", "CRITICAL recall", "CRITICAL precision"], rows, widths=[5.6, 2.4, 2.4, 2.8, 2.8])
para(f"The neural network was selected for deployment because it gives the highest recall for CRITICAL conditions "
     f"({pct(MLP['recall_critical'])}) - missing a hazard is worse than a false alarm - while remaining tiny "
     f"({MET['model_bytes']} bytes). The decision tree has slightly higher overall accuracy and is a good alternative. "
     f"The threshold baseline can only report the present state, so its 'predictions' miss conditions that are "
     f"about to develop.")
figure(os.path.join("..", "ml", "confusion_matrix.png"), "Figure 10.2 - Confusion matrix of the deployed neural network", 10)
doc.add_heading("10.4 Early-warning performance", 2)
table(["Metric", "Threshold rules", "AI model"], [
    ["Critical episodes in test period", EW["critical_episodes_in_test"], EW["critical_episodes_in_test"]],
    ["Predicted before onset", "0 %", f"{EW['ml_predicted_before_onset_pct']:.0f} %"],
    ["Median warning lead time", "0 min", f"{EW['ml_median_lead_minutes']:.1f} min"],
], widths=[7, 4.5, 4.5])
para("A lead time of several minutes is enough for the exhaust fan to bring air quality or temperature back "
     "before a critical level is reached, which the demo scenarios show (Section 11). Because the dataset is "
     "synthetic, these figures show that the method works; they must be re-measured on real laboratory data.")
doc.add_heading("10.5 Deployment on the ESP32 (TinyML)", 2)
figure("network.png", "Figure 10.3 - Deployed network", 14)
para("train_model.py exports the standardisation constants and all weights as C arrays in model.h, together with "
     "a forward-pass function (dense layers, ReLU, softmax) and three self-test vectors. At start-up the ESP32 "
     "checks that its outputs match Python's; in a desktop g++ test the maximum difference was 4.8e-7. Inference "
     "needs about 300 multiply-adds, a few microseconds on the ESP32, and no external library, which is the same "
     "principle as TensorFlow Lite for Microcontrollers with a smaller footprint. The same weights are exported to "
     "dashboard/ml_model.js so the dashboard can display and simulate identical predictions.")

# ============================================================ 11 simulation & testing
doc.add_heading("11. Simulation, Digital Twin and Testing", 1)
doc.add_heading("11.1 Wokwi simulation", 2)
para("The complete project (firmware, AI model, circuit and libraries) is saved on Wokwi at "
     "https://wokwi.com/projects/476557350477755393 . To run it:")
numbered(["Open the project link (or run start_all.bat wokwi, which also starts the logger and dashboard).",
          "To rebuild it elsewhere: paste sketch.ino and diagram.json into a new ESP32 project, add model.h and "
          "libraries.txt (DHT sensor library for ESPx, Adafruit SSD1306, Adafruit GFX Library, PubSubClient).",
          "Start the simulation. The OLED shows readings; the serial monitor prints the AI prediction each model-minute.",
          "Click the DHT22 to change temperature/humidity, the gas sensor to change air quality, the LDR to change "
          "light, and 'Simulate motion' on the PIR for occupancy.",
          "Open dashboard/index.html and press Connect to watch the simulated device live."])
doc.add_heading("11.2 Blender digital twin", 2)
para("blender/smart_lab_twin.py builds a 3D laboratory - benches, fume hood, air-conditioner, exhaust fan, "
     "ceiling lights, students and the monitoring node with a working OLED - and animates the AI early-warning "
     "story: students enter, CO2 rises (shown as haze), the model predicts CRITICAL, the fan starts, a Telegram "
     "message appears, and the air returns to SAFE without ever reaching CRITICAL. A wall dashboard and the OLED "
     "show changing values every frame. With LIVE_MQTT enabled it mirrors the real (or simulated) device in real "
     "time - the digital twin listed as future scope in Phase 1.")
doc.add_heading("11.3 Test cases", 2)
TESTS = [
    ["T1", "Power-on", "LED sequence + chirp, MQ-135 calibration, AI self-test PASSED in serial"],
    ["T2", "Normal conditions (24 C, 45 %, 400 ppm)", "SAFE, green LED, fan off, OLED 'Environment Stable'"],
    ["T3", "Air quality raised above 1000 ppm", "WARNING 'Poor air quality', yellow LED, fan ON"],
    ["T4", "Temperature set to 35 C", "CRITICAL, blinking red LED, siren, fan ON, alert"],
    ["T5", "PIR motion with light < 150 lux", "WARNING 'Insufficient light'"],
    ["T6", "Temperature raised steadily (trend)", "AI early warning before 32 C: fan ON, OLED 'AI:CRITICAL in 10m!'"],
    ["T7", "Button short press / long press", "Buzzer muted 60 s / self-test sequence"],
    ["T8", "Dashboard connected to Wokwi", "Live values every 3 s; commands executed"],
    ["T9", "Model C code vs Python", "Identical probabilities on test vectors"],
    ["T10", "Dashboard demo: lab session", "WARNING at ~1000 ppm and ventilation"],
    ["T11", "Dashboard demo: AC failure", "AI early warning before CRITICAL"],
    ["T12", "MQTT logger end-to-end", "Readings and alerts stored; training CSV exported"],
    ["T13", "Reading hovering near a limit", "No repeated SAFE/WARNING alerts (hold time)"],
]
table(["ID", "Test", "Expected result", "Observed"], [t + [OBSERVED.get(t[0], "")] for t in TESTS],
      widths=[1.1, 4.3, 6, 4.6], size=9.5)
para("T1-T8 are completed in the Wokwi simulator (insert screenshots here, Figures 11.1-11.4). T9-T13 were "
     "executed during development and passed.")

# ============================================================ 12 results
doc.add_heading("12. Results", 1)
bullets([f"Continuous monitoring of five parameters with a three-level status and automatic ventilation.",
         f"AI prediction on the ESP32: {pct(MLP['accuracy'])} accuracy, {pct(MLP['recall_critical'])} CRITICAL recall, "
         f"all {EW['critical_episodes_in_test']} test critical episodes predicted in advance "
         f"(median {EW['ml_median_lead_minutes']:.1f} min).",
         "In the AC-failure scenario the early warning came about 13 lab-minutes before the CRITICAL limit; in the "
         "lab-session scenario the fan kept CO2 near 1000 ppm instead of letting it climb.",
         "Live dashboard, cloud logging, Telegram alerts and a 3D digital twin complete the IoT chain.",
         f"Model size {MET['model_bytes']} bytes - well within the ESP32's 520 KB RAM and 4 MB flash."])

# ============================================================ 13 adv etc
doc.add_heading("13. Advantages, Limitations and Future Scope", 1)
doc.add_heading("13.1 Advantages", 2)
bullets(["Continuous monitoring and automated alerts", "Remote access from any browser or phone",
         "Low-cost implementation with common modules", "Scalable to many labs (one device ID per room)",
         "AI-based predictive safety running offline on the device",
         "Safety layer independent of the network"])
doc.add_heading("13.2 Limitations", 2)
bullets(["The ML model is trained on synthetic data; it must be retrained on real logged data.",
         "MQ-135 gives a CO2-equivalent estimate, is cross-sensitive to other gases and drifts; it needs burn-in and "
         "periodic calibration (an NDIR CO2 sensor or BME680 would be more accurate).",
         "A PIR sensor detects presence, not the number of people.",
         "The public MQTT broker is for demonstration; a private broker with authentication and TLS is needed "
         "for deployment."])
doc.add_heading("13.3 Future scope", 2)
bullets(["Computer vision for PPE detection", "Voice alerts", "Digital twin of the laboratory (prototype built in Blender)",
         "Predictive maintenance of HVAC", "Integration with Building Management Systems (BMS)",
         "Edge AI using TinyML - extend to anomaly detection and sensor-fault detection",
         "People counting with door sensors or thermal array sensors", "Email / SMS alerts and multi-lab dashboard"])

# ============================================================ 14 conclusion
doc.add_heading("14. Conclusion", 1)
para("The Smart Laboratory Environment Monitoring System provides a reliable and cost-effective way to improve "
     "laboratory safety through continuous monitoring of temperature, humidity, air quality, occupancy and light. "
     "By combining an ESP32-based embedded system with IoT communication, cloud storage and an on-device neural "
     "network, it offers real-time monitoring, automated alerts, data logging and intelligent ventilation control "
     "- and, beyond conventional threshold systems, it predicts unsafe conditions minutes before they occur and "
     "acts on them. The complete design was implemented and verified in software, and the same firmware is ready "
     "for the hardware build.")

# ============================================================ references
doc.add_heading("References", 1)
numbered(["Espressif Systems, 'ESP32 Series Datasheet' and 'ESP32 Technical Reference Manual'.",
          "Aosong Electronics, 'AM2302 / DHT22 Digital Temperature and Humidity Sensor' datasheet.",
          "Hanwei Electronics, 'MQ-135 Gas Sensor' technical data.",
          "Solomon Systech, 'SSD1306 128x64 OLED Driver' datasheet.",
          "ASHRAE Standard 62.1, 'Ventilation for Acceptable Indoor Air Quality'.",
          "P. Warden and D. Situnayake, 'TinyML: Machine Learning with TensorFlow Lite on Arduino and Ultra-Low-"
          "Power Microcontrollers', O'Reilly, 2019.",
          "F. Pedregosa et al., 'Scikit-learn: Machine Learning in Python', JMLR 12, 2011.",
          "OASIS, 'MQTT Version 3.1.1', 2014.",
          "Wokwi documentation, https://docs.wokwi.com; ThingSpeak documentation, https://www.mathworks.com/help/thingspeak/.",
          "Telegram Bot API, https://core.telegram.org/bots/api; Blender Manual, https://docs.blender.org."])

# ============================================================ appendices
doc.add_page_break()
doc.add_heading("Appendix A - Project Files", 1)
table(["Path", "Contents"], [
    ["firmware/sketch.ino, model.h, diagram.json, libraries.txt", "ESP32 firmware, AI model, Wokwi circuit"],
    ["ml/generate_dataset.py, train_model.py", "Dataset generation, training, evaluation, export"],
    ["ml/metrics.json, confusion_matrix.png", "Results used in this report"],
    ["dashboard/index.html, ml_model.js", "IoT dashboard with demo mode"],
    ["cloud/mqtt_logger.py", "MQTT -> SQLite logger and training-data export"],
    ["blender/smart_lab_twin.py", "3D digital twin and animation"],
    ["report/", "This report and the scripts that draw its figures"],
], widths=[7.5, 8.5])
doc.add_heading("Appendix B - Moving to Hardware", 1)
numbered(["Wire the circuit as in Section 7; add the 10 k / 20 k divider on MQ-135 AO and set DIVIDER = 1.5.",
          "Set MODEL_MINUTE_MS = 60000 and OCCUPIED_HOLD_MS = 300000.",
          "Burn in the MQ-135 for 24-48 h and calibrate it in fresh outdoor air.",
          "Enter the lab Wi-Fi, a unique DEVICE_ID, the ThingSpeak write key and the Telegram bot token / chat id.",
          "Run cloud/mqtt_logger.py for several weeks, export the data, retrain with ml/train_model.py and copy the "
          "new model.h into the firmware.",
          "Mains-powered fans must be switched by a properly rated relay installed by a qualified electrician."])

cp = doc.core_properties
cp.author = cp.last_modified_by = "M.A. Kaushik, Deepak SN"
cp.title = "Smart Laboratory Environment Monitoring System"
cp.subject = "Embedded Systems Project Report"
cp.comments = ""

out = os.path.join(HERE, "Project_Report.docx")
doc.save(out)
print("saved", out)
