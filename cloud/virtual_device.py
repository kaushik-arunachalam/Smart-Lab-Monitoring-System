"""
Virtual ESP32 - software stand-in for the Wokwi / hardware device.

Runs the same status rules, status hold-time and neural network as
firmware/sketch.ino, on a small physics model of the lab, and talks the same
MQTT protocol (smartlab/<id>/data, /alert, /cmd). Use it to connect the whole
system (dashboard, cloud logger, Blender twin) when the Wokwi build queue is
busy or before the hardware exists. Stop it when the real device is online,
because both would publish on the same topic.

  pip install paho-mqtt numpy
  python virtual_device.py                 # interactive: scenarios from the dashboard
  python virtual_device.py --autoplay      # loops a demo story by itself

Time scale: 1 real second = 1 lab minute (same as MODEL_MINUTE_MS in the simulator).
Extra commands (dashboard scenario buttons): scenario:session | chemical | hvac | lights | clear
"""
import argparse
import json
import os
import random
import time

import numpy as np
import paho.mqtt.client as mqtt

HERE = os.path.dirname(os.path.abspath(__file__))
CLASSES = ["SAFE", "WARNING", "CRITICAL"]


def load_model():
    src = open(os.path.join(HERE, "..", "dashboard", "ml_model.js")).read()
    m = json.loads(src[src.index("{"):src.rindex("}") + 1])
    return (np.array(m["mean"]), np.array(m["scale"]),
            [(np.array(L["W"]), np.array(L["b"])) for L in m["layers"]])


MEAN, SCALE, LAYERS = load_model()


def predict(x):
    a = (np.asarray(x, float) - MEAN) / SCALE
    for i, (W, b) in enumerate(LAYERS):
        a = a @ W + b
        if i < len(LAYERS) - 1:
            a = np.maximum(a, 0)
    e = np.exp(a - a.max())
    return e / e.sum()


def status_of(t, h, aq, occ, lux):
    if t > 32: return 2, "High temperature!"
    if t < 15: return 2, "Low temperature!"
    if h > 70: return 2, "Humidity too high!"
    if h < 20: return 2, "Humidity too low!"
    if aq > 2000: return 2, "Hazardous air!"
    if aq > 1000: return 1, "Poor air quality"
    if t > 27 or t < 18: return 1, "Temperature abnormal"
    if h > 60 or h < 30: return 1, "Humidity abnormal"
    if occ and lux < 150: return 1, "Insufficient light"
    return 0, ("Lab empty, lights on" if (not occ and lux > 300) else "Environment Stable")


def aq_label(p):
    return "Good" if p < 800 else "Moderate" if p < 1000 else "Poor" if p < 2000 else "Hazardous"


class Lab:
    def __init__(self):
        self.temp, self.hum, self.co2 = 23.2, 46.0, 460.0
        self.people, self.chem, self.hvac_fail, self.lamp_fail = 0, 0.0, 0, False
        self.fan = self.fan_manual = False
        self.muted_until = 0.0
        self.hist = []
        self.status, self.reason, self.lower = 0, "Environment Stable", 0
        self.notified_status, self.notified_early = 0, False
        self.start = time.time()

    def scenario(self, ev):
        if ev == "session": self.people = 28
        elif ev == "chemical": self.chem = 240
        elif ev == "hvac": self.hvac_fail = 70
        elif ev == "lights": self.lamp_fail = not self.lamp_fail
        elif ev == "clear": self.people, self.hvac_fail = 0, 0
        return f"Scenario: {ev}"

    def step(self):
        occ = self.people > 0
        self.co2 += (self.people * 2.0 * random.uniform(0.9, 1.1)
                     - (0.012 + (0.085 if self.fan else 0)) * (self.co2 - 420) + self.chem)
        self.co2 = max(400.0, self.co2)
        self.chem = max(0.0, self.chem - 6)
        if self.hvac_fail > 0:
            self.temp += 0.16 + 0.006 * self.people; self.hvac_fail -= 1
        else:
            self.temp += 0.06 * (22.8 - self.temp) + ((0.03 + 0.004 * self.people) if occ else 0)
        if self.fan:
            self.temp -= 0.008 * max(0.0, self.temp - 24)
        self.hum += 0.05 * (46 + 0.25 * self.people - self.hum) + random.uniform(-0.2, 0.2)
        lux = (450 if occ and not self.lamp_fail else 0) + 60 + random.uniform(-5, 5)
        t = self.temp + random.uniform(-0.1, 0.1); h = self.hum; aq = self.co2 * random.uniform(0.99, 1.01)

        self.hist.append((t, h, aq)); self.hist = self.hist[-11:]
        n = len(self.hist) - 1; o = self.hist[0]
        sT, sH, sA = ((t - o[0]) / n, (h - o[1]) / n, (aq - o[2]) / n) if n else (0, 0, 0)

        raw, reason = status_of(t, h, aq, occ, lux)
        if raw >= self.status:
            self.status, self.reason, self.lower = raw, reason, 0
        else:
            self.lower += 1
            if self.lower >= 5:
                self.status, self.reason, self.lower = raw, reason, 0

        p = predict([t, h, aq, 1.0 if occ else 0.0, lux, sT, sA, sH])
        k = int(np.argmax(p))
        early = k == 2 and p[2] >= 0.6 and self.status != 2
        air_or_heat = aq > 900 or t > 26.5 or h > 58
        self.fan = self.fan_manual or (self.status >= 1 and air_or_heat) or early
        muted = time.time() < self.muted_until
        return {
            "id": None, "ts": int(time.time()), "temp": round(t, 1), "hum": round(h, 1), "aq": int(aq),
            "aqLabel": aq_label(aq), "occ": occ, "lux": int(lux), "status": CLASSES[self.status],
            "reason": self.reason, "pred": CLASSES[k], "pSafe": round(float(p[0]), 3),
            "pWarn": round(float(p[1]), 3), "pCrit": round(float(p[2]), 3), "early": bool(early),
            "slopeT": round(sT, 3), "slopeA": round(sA, 1), "fan": self.fan, "fanManual": self.fan_manual,
            "buzzer": (not muted) and (self.status == 2 or early), "muted": muted, "cloud": False,
            "rssi": -55, "uptime": int(time.time() - self.start), "virtual": True,
        }

    def alerts(self, d):
        out = []
        st, early = self.status, d["early"]
        if st > self.notified_status:
            out.append(f"{CLASSES[st]}: {self.reason} | T {d['temp']}C RH {d['hum']:.0f}% Air {d['aq']}ppm")
        elif early and not self.notified_early:
            out.append(f"AI EARLY WARNING: CRITICAL expected within 10 min (p={d['pCrit'] * 100:.0f}%). Fan started.")
        elif st == 0 and self.notified_status != 0:
            out.append(f"Back to SAFE. T {d['temp']}C RH {d['hum']:.0f}% Air {d['aq']}ppm")
        if out:
            self.notified_status = st
        self.notified_early = early
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="smartlab-cse24")
    ap.add_argument("--broker", default="broker.hivemq.com")
    ap.add_argument("--autoplay", action="store_true")
    ap.add_argument("--minutes", type=int, default=0, help="stop after N lab-minutes (0 = forever)")
    a = ap.parse_args()
    base = f"smartlab/{a.device}"
    lab = Lab()

    def on_connect(c, *_):
        c.subscribe(f"{base}/cmd")
        print(f"[virtual ESP32] online as {a.device} on {a.broker}", flush=True)

    def on_message(c, _u, msg):
        cmd = msg.payload.decode(errors="ignore").strip()
        print(f"[CMD] {cmd}", flush=True)
        note = None
        if cmd == "fan_on": lab.fan_manual = True
        elif cmd == "fan_auto": lab.fan_manual = False
        elif cmd == "mute": lab.muted_until = time.time() + 60
        elif cmd == "test": note = "Self-test: LEDs, buzzer and fan relay cycled"
        elif cmd.startswith("scenario:"): note = lab.scenario(cmd.split(":", 1)[1])
        if note:
            c.publish(f"{base}/alert", json.dumps({"status": CLASSES[lab.status], "msg": note}))

    try:
        cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"virtual-esp32-{random.randint(0, 99999)}")
    except AttributeError:
        cli = mqtt.Client()
    cli.will_set(f"{base}/data", json.dumps({"offline": True}), retain=True)
    cli.on_connect, cli.on_message = on_connect, on_message
    cli.connect(a.broker, 1883, 30)
    cli.loop_start()
    story = {10: "session", 60: "hvac", 150: "clear", 200: "chemical", 260: "session", 330: "clear"}
    minute = 0
    try:
        while not a.minutes or minute < a.minutes:
            minute += 1
            if a.autoplay and (minute % 380) in story:
                ev = story[minute % 380]
                cli.publish(f"{base}/alert", json.dumps({"status": CLASSES[lab.status], "msg": lab.scenario(ev)}))
            d = lab.step(); d["id"] = a.device
            cli.publish(f"{base}/data", json.dumps(d))
            for msg in lab.alerts(d):
                cli.publish(f"{base}/alert", json.dumps({"status": d["status"], "msg": msg}))
                print(f"[ALERT] {msg}", flush=True)
            print(f"min {minute:4d}  T={d['temp']:5.1f} RH={d['hum']:4.0f} AQ={d['aq']:5d} occ={int(d['occ'])} "
                  f"lux={d['lux']:3d} | {d['status']:8s} | AI {d['pred']:8s} pCrit={d['pCrit']:.2f} "
                  f"{'EARLY ' if d['early'] else ''}fan={int(d['fan'])}", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    cli.publish(f"{base}/data", json.dumps({"offline": True}), retain=True)
    time.sleep(0.5)
    cli.loop_stop()


if __name__ == "__main__":
    main()
