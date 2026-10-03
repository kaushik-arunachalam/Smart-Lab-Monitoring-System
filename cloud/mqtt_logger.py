"""
Cloud data logger: MQTT -> SQLite database (+ CSV export for ML retraining)

Runs on any PC / Raspberry Pi / cloud VM. Subscribes to the device's live
data and stores every reading, building the historical dataset that the
ML model is trained on (architecture blocks 5 "Cloud database" and
8 "Historical sensor data").

  pip install paho-mqtt pandas
  python mqtt_logger.py                          # log live data (Ctrl+C to stop)
  python mqtt_logger.py --export training.csv    # 1-minute dataset for ml/train_model.py
  python mqtt_logger.py --summary                # quick statistics

The export has the same columns as ml/lab_environment_dataset.csv, so real
data can replace the synthetic data:  python ../ml/train_model.py
(after copying the export over ml/lab_environment_dataset.csv).
"""
import argparse
import json
import sqlite3
import time
from datetime import datetime

BROKER = "broker.hivemq.com"
DEVICE_ID = "smartlab-cse24"
DB_PATH = "lab_data.db"
STATUS = {"SAFE": 0, "WARNING": 1, "CRITICAL": 2}

SCHEMA = """CREATE TABLE IF NOT EXISTS readings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  received_at REAL NOT NULL,
  temperature REAL, humidity REAL, air_quality_ppm REAL,
  occupancy INTEGER, light_lux REAL, status INTEGER,
  ai_pred INTEGER, p_critical REAL, fan INTEGER, early_warning INTEGER, raw TEXT);
CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, received_at REAL NOT NULL, status TEXT, message TEXT);"""


def open_db(path=DB_PATH):
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def store(con, topic, payload):
    try:
        d = json.loads(payload)
    except ValueError:
        return None
    now = time.time()
    if topic.endswith("/alert"):
        con.execute("INSERT INTO alerts(received_at,status,message) VALUES (?,?,?)",
                    (now, d.get("status"), d.get("msg")))
        con.commit()
        return f"ALERT {d.get('status')}: {d.get('msg')}"
    if d.get("offline"):
        return "device offline"
    con.execute("""INSERT INTO readings(received_at,temperature,humidity,air_quality_ppm,occupancy,light_lux,
                   status,ai_pred,p_critical,fan,early_warning,raw) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (now, d.get("temp"), d.get("hum"), d.get("aq"), int(bool(d.get("occ"))), d.get("lux"),
                 STATUS.get(d.get("status"), 0), STATUS.get(d.get("pred"), 0), d.get("pCrit"),
                 int(bool(d.get("fan"))), int(bool(d.get("early"))), payload))
    con.commit()
    return (f"{datetime.now():%H:%M:%S}  T={d.get('temp')}C RH={d.get('hum')}% AQ={d.get('aq')}ppm "
            f"occ={d.get('occ')} lux={d.get('lux')}  {d.get('status')}  AI={d.get('pred')} "
            f"p_crit={d.get('pCrit')}")


def run_logger(device, broker):
    import paho.mqtt.client as mqtt
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.executescript(SCHEMA)

    def on_connect(client, *_):
        client.subscribe([(f"smartlab/{device}/data", 0), (f"smartlab/{device}/alert", 0)])
        print(f"connected to {broker}, logging smartlab/{device}/# into {DB_PATH}", flush=True)

    def on_message(_c, _u, msg):
        line = store(con, msg.topic, msg.payload.decode(errors="ignore"))
        if line:
            print(line, flush=True)

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(broker, 1883, 30)
    client.loop_start()
    try:
        while True:                      # heartbeat so the dashboard shows "Cloud: LOGGED n"
            n = con.execute("SELECT COUNT(*) FROM readings").fetchone()[0]
            client.publish(f"smartlab/{device}/logger", json.dumps({"rows": n, "db": DB_PATH}))
            time.sleep(10)
    except KeyboardInterrupt:
        print("stopped")


def export_training(out_csv, horizon=10, trend=10):
    """Resample to 1-minute rows and add the same features/labels as the synthetic dataset."""
    import pandas as pd
    con = open_db()
    df = pd.read_sql_query("SELECT * FROM readings ORDER BY received_at", con)
    if df.empty:
        raise SystemExit("no readings logged yet")
    df["time"] = pd.to_datetime(df["received_at"], unit="s")
    m = df.set_index("time")[["temperature", "humidity", "air_quality_ppm", "occupancy", "light_lux",
                              "fan", "status"]].resample("1min").mean().dropna()
    m["occupancy"] = (m["occupancy"] > 0.5).astype(int)
    m["fan"] = (m["fan"] > 0.5).astype(int)
    m["status_now"] = m["status"].round().astype(int)
    m["day"] = (m.index.normalize() - m.index.normalize()[0]).days
    m["minute"] = m.index.hour * 60 + m.index.minute
    m["people"] = m["occupancy"]
    for col, name in (("temperature", "temp_slope"), ("air_quality_ppm", "aq_slope"), ("humidity", "hum_slope")):
        m[name] = (m[col] - m[col].shift(trend)) / trend
    fut = pd.concat([m["status_now"].shift(-k) for k in range(horizon + 1)], axis=1)
    m["status_next"] = fut.max(axis=1)
    m = m.dropna()
    m["status_next"] = m["status_next"].astype(int)
    cols = ["day", "minute", "temperature", "humidity", "air_quality_ppm", "occupancy", "light_lux", "people",
            "fan", "status_now", "temp_slope", "aq_slope", "hum_slope", "status_next"]
    m[cols].round(3).to_csv(out_csv, index=False)
    print(f"exported {len(m)} one-minute rows -> {out_csv}")


def summary():
    con = open_db()
    n, t0, t1 = con.execute("SELECT COUNT(*), MIN(received_at), MAX(received_at) FROM readings").fetchone()
    if not n:
        print("no readings yet"); return
    print(f"{n} readings from {datetime.fromtimestamp(t0)} to {datetime.fromtimestamp(t1)}")
    for name, s in STATUS.items():
        c = con.execute("SELECT COUNT(*) FROM readings WHERE status=?", (s,)).fetchone()[0]
        print(f"  {name:8s} {c:6d}  ({100 * c / n:.1f} %)")
    print("  AI early warnings:", con.execute("SELECT COUNT(*) FROM readings WHERE early_warning=1").fetchone()[0])
    print("  alerts:", con.execute("SELECT COUNT(*) FROM alerts").fetchone()[0])


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default=DEVICE_ID)
    ap.add_argument("--broker", default=BROKER)
    ap.add_argument("--export", metavar="CSV")
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args()
    if a.export:
        export_training(a.export)
    elif a.summary:
        summary()
    else:
        run_logger(a.device, a.broker)
