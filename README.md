# Smart Laboratory Environment Monitoring System
**An IoT Based Embedded System with AI Driven Environmental Safety Analysis**
Everything in the Phase 1 plan, built and tested in software (no hardware needed yet).

| Folder | What it is | Tool |
|---|---|---|
| `firmware/` | ESP32 code (`sketch.ino`), AI model (`model.h`), circuit (`diagram.json`), `libraries.txt` | [Wokwi](https://wokwi.com) |
| `ml/` | Dataset generator, training + evaluation, exports `model.h` and `dashboard/ml_model.js` | Python |
| `dashboard/` | Web/mobile dashboard (live MQTT, trends 1H–7D, AI prediction, OLED mirror, controls, demo mode) | Browser |
| `cloud/` | `mqtt_logger.py`: MQTT → SQLite "cloud database" + CSV export for retraining | Python |
| `blender/` | `smart_lab_twin.py`: 3D digital twin + AI early-warning animation (optional live MQTT mode) | Blender 3.6+ |
| `report/` | `Project_Report.docx` / `.pdf` (18 pages) + scripts that draw the figures | Word |

## Sensors → actions
| Status | Condition | Action |
|---|---|---|
| SAFE | everything in range | green LED, fan auto |
| WARNING | T > 27 / < 18 °C, RH > 60 / < 30 %, air > 1000 ppm, or occupied with light < 150 lx | yellow LED, fan ON (air/heat/humidity) |
| CRITICAL | T > 32 / < 15 °C, RH > 70 / < 20 %, air > 2000 ppm | red LED + siren, fan ON, Telegram alert |
| **AI early warning** | model predicts CRITICAL within 10 min (p ≥ 0.6) | fan ON early, yellow blink, chirp, Telegram |

## 0. Start everything, connected (one click)
Double-click **`start_all.bat`**. It starts:
- **Cloud logger:** MQTT → `cloud/lab_data.db`. It also sends a heartbeat, so the dashboard shows *Cloud: LOGGED n*.
- **Virtual ESP32** (`cloud/virtual_device.py`): the same rules, AI model and MQTT messages as the firmware.
- **Dashboard:** opens in your browser and connects automatically.

```
Virtual ESP32 / Wokwi ESP32 ──MQTT──► broker.hivemq.com ──► dashboard (live, charts, AI, OLED mirror)
          ▲                                   │          └──► cloud logger (SQLite) ──► ML retraining
          └──────── commands (fan, mute, test, scenarios) ◄── dashboard buttons
```
- **Scenario buttons:** they drive the virtual ESP32 (lab session, fumes, AC failure, lights, leave).
- **Using the real firmware:** when it runs in Wokwi, start with **`start_all.bat wokwi`** instead. That skips the virtual device, because Wokwi publishes on the same topics.

## 1. Run it in Wokwi
**Saved project:** https://wokwi.com/projects/476557350477755393
Open it (or run `start_all.bat wokwi`) and press ▶. Everything below is already in it.

To rebuild the Wokwi project from the files instead:
1. Go to https://wokwi.com/projects/new/esp32
2. Paste `sketch.ino` into **sketch.ino** and `diagram.json` into **diagram.json**.
3. Tab menu ▾ → **New file…** → `model.h` → paste `firmware/model.h`.
4. Library Manager → add: `DHT sensor library for ESPx`, `Adafruit SSD1306`, `Adafruit GFX Library`, `PubSubClient`.
5. Press ▶. To change the conditions, click the parts while the simulation runs:
   - **DHT22:** temperature and humidity sliders.
   - **Gas sensor (MQ-135):** air quality.
   - **LDR:** light (lux).
   - **PIR:** "Simulate motion" for occupancy.
6. To see the AI early warning, raise the DHT22 temperature a little at a time (e.g. +1 °C every few seconds).
   The model reacts to the **trend** before the reading reaches 32 °C.

> Free Wokwi builds can say "Build Servers Busy" when their servers are loaded. Press ▶ again later.

## 2. Dashboard
Double-click `dashboard/index.html` to open it in Chrome or Edge. Keep `ml_model.js` in the same folder. To serve it instead:
```bash
python -m http.server 8765 --directory dashboard
```
Then open http://localhost:8765:
- **Connect** (device ID `smartlab-cse24`) shows the Wokwi simulation live.
- **Demo mode** gives scenario buttons that run the same neural network as the ESP32.
- For a hands-free presentation, open http://localhost:8765/#autoplay (or `#autoplay-light`).

> Change `DEVICE_ID` in `sketch.ino` and in the dashboard to something unique, e.g. your roll number.
> The broker is public, so otherwise anyone else using the same ID could see or control your device.

## 3. Cloud database, notifications
- **Logger:** `pip install paho-mqtt pandas`, then `python cloud/mqtt_logger.py` stores every reading in `lab_data.db`.
  - `--summary` prints statistics.
  - `--export training.csv` makes a dataset for retraining.
- **ThingSpeak:** create a free channel with 8 fields and put its Write API key in `THINGSPEAK_API_KEY` in `sketch.ino`.
  - The dashboard can load this history (Control → Cloud database).
- **Telegram:**
  - Create a bot with @BotFather and put its token in `TELEGRAM_BOT_TOKEN`.
  - Get your chat id from @userinfobot and put it in `TELEGRAM_CHAT_ID`.

## 4. Machine learning
```bash
pip install numpy pandas scikit-learn pillow
cd ml
python generate_dataset.py   # 90 days x 1440 min synthetic lab data
python train_model.py        # compares models, writes model.h, metrics.json, confusion_matrix.png
```
Copy `ml/model.h` to `firmware/`. Results on the held-out test days:
- **Accuracy:** 97.6 %.
- **CRITICAL recall:** 95.9 %.
- **Early warning:** all 22 critical episodes were predicted in advance, with a median lead time of 9.5 min.

The dataset is synthetic until the hardware exists. Log real data with the logger, export it, and retrain.

## 5. Blender digital twin
Blender → **Scripting** → open `blender/smart_lab_twin.py` → **Run Script** → Space.
- The haze needs no baking.
- **Render → Render Animation** makes the video.
- `LIVE_MQTT = True` mirrors the live device. It needs `paho-mqtt` installed in Blender's Python.

## 6. Report
Fill in the institution/guide on the title page. Run the Wokwi tests T1–T8 and add screenshots in Chapter 11.
To rebuild: `python report/make_diagrams.py && python report/make_report.py`.
