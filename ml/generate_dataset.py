"""
Synthetic laboratory environment dataset (1 sample per minute).

Because the hardware is not built yet, this script produces a physically
motivated dataset to develop and test the ML pipeline. Once the real system is
running, replace it with logged data (cloud/mqtt_logger.py writes a CSV with
the same columns) and re-run train_model.py.

Simulated physics
  - Occupancy follows a lab timetable (weekday sessions 09-12 and 14-17,
    occasional evening work); PIR output = people > 0.
  - CO2-equivalent air quality (MQ-135): each person adds ~2 ppm/min to a
    ~150 m^3 lab; natural ventilation ~0.6 air changes/h, exhaust fan ~5 ACH.
  - Temperature: HVAC set-point + body/equipment heat; random HVAC failures.
  - Humidity: seasonal baseline + people; water-bath / HVAC failure events.
  - Chemical / solvent release events raise the MQ-135 reading sharply.
  - Lighting: lamps when occupied + daylight; random lamp failures.
  - The exhaust fan is driven by the same rule-based controller as the
    firmware, so the data reflects the controlled system.

Labels
  status_now  : rule-based status of the current reading (0 SAFE, 1 WARNING, 2 CRITICAL)
  status_next : worst status within the NEXT 10 minutes  <- ML target (prediction)
"""
import numpy as np
import pandas as pd
import os

rng = np.random.default_rng(42)
DAYS = 90
MIN_PER_DAY = 1440
HORIZON = 10          # minutes ahead the model must predict
TREND_WIN = 10        # minutes used for slope features

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lab_environment_dataset.csv")


def status(t, h, aq, occ, lux):
    crit = (t > 32) | (t < 15) | (h > 70) | (h < 20) | (aq > 2000)
    warn = (t > 27) | (t < 18) | (h > 60) | (h < 30) | (aq > 1000) | ((occ > 0) & (lux < 150))
    return np.where(crit, 2, np.where(warn, 1, 0))


rows = []
temp, hum, co2 = 23.0, 45.0, 450.0
fan = False
events = []  # (type, start_minute, duration, magnitude)
N = DAYS * MIN_PER_DAY

# pre-schedule random events
for _ in range(int(DAYS * 0.55)):
    events.append(("hvac_fail", rng.integers(0, N), rng.integers(40, 180), rng.uniform(0.06, 0.2)))
for _ in range(int(DAYS * 0.7)):
    events.append(("chemical", rng.integers(0, N), rng.integers(10, 60), rng.uniform(60, 320)))
for _ in range(int(DAYS * 0.35)):
    events.append(("humid", rng.integers(0, N), rng.integers(30, 120), rng.uniform(0.6, 1.6)))
for _ in range(int(DAYS * 0.25)):
    events.append(("lamp_fail", rng.integers(0, N), rng.integers(20, 150), 0))
ev_active = np.zeros((N, 4), dtype=float)   # hvac, chemical, humid, lamp
idx = {"hvac_fail": 0, "chemical": 1, "humid": 2, "lamp_fail": 3}
for typ, s, d, m in events:
    ev_active[s:min(N, s + d), idx[typ]] = m if typ != "lamp_fail" else 1

people_today = 0
for day in range(DAYS):
    weekday = day % 7 < 5
    season_h = 45 + 12 * np.sin(2 * np.pi * day / 90)          # drifting humidity baseline
    sessions = []
    if weekday:
        sessions = [(9 * 60 + rng.integers(-10, 15), 12 * 60 + rng.integers(-20, 10), rng.integers(12, 35)),
                    (14 * 60 + rng.integers(-10, 15), 17 * 60 + rng.integers(-20, 30), rng.integers(8, 32))]
        if rng.random() < 0.3:
            sessions.append((18 * 60 + rng.integers(0, 60), 20 * 60 + rng.integers(0, 60), rng.integers(1, 5)))
    elif rng.random() < 0.3:
        sessions.append((10 * 60, 13 * 60 + rng.integers(0, 60), rng.integers(1, 6)))

    for m in range(MIN_PER_DAY):
        g = day * MIN_PER_DAY + m
        people = 0
        for s, e, n in sessions:
            if s <= m < e:
                people = max(0, int(n + rng.integers(-2, 3)))
        occ = 1 if people > 0 else 0
        hvac_fail, chem, humid_ev, lamp_fail = ev_active[g]

        # --- air quality (CO2 eq. ppm) ---
        vent = 0.012 + (0.085 if fan else 0.0)
        co2 += people * 2.0 * rng.uniform(0.8, 1.2) - vent * (co2 - 420) + chem * rng.uniform(0.6, 1.4)
        co2 = max(400, co2)

        # --- temperature ---
        setpoint = 22.5 + 0.8 * np.sin(2 * np.pi * (m - 15 * 60) / MIN_PER_DAY)
        heat = 0.012 * people + (0.08 if occ else 0)
        if hvac_fail:
            temp += hvac_fail + heat * 0.5
        else:
            temp += 0.06 * (setpoint - temp) + heat * 0.3
        if fan:
            temp -= 0.008 * max(0, temp - 24)
        temp = float(np.clip(temp, 10, 42))

        # --- humidity ---
        target_h = season_h + 0.25 * people
        hum += 0.05 * (target_h - hum) + humid_ev + (0.08 if hvac_fail else 0)
        hum = float(np.clip(hum, 8, 95))

        # --- light (lux) ---
        daylight = max(0, 180 * np.sin(np.pi * (m - 6 * 60) / (12 * 60))) if 6 * 60 < m < 18 * 60 else 0
        lamps = 450 if occ and not lamp_fail else (0 if lamp_fail or not occ else 0)
        lux = daylight * rng.uniform(0.7, 1.1) + lamps + rng.normal(0, 8)
        lux = max(0, lux)

        # --- sensor noise ---
        t_s = temp + rng.normal(0, 0.15)
        h_s = hum + rng.normal(0, 0.8)
        aq_s = co2 * rng.normal(1, 0.02)

        st = int(status(np.array(t_s), np.array(h_s), np.array(aq_s), np.array(occ), np.array(lux)))
        fan = st >= 1 and (aq_s > 900 or t_s > 26.5 or h_s > 58)   # firmware's rule controller
        rows.append((day, m, t_s, h_s, aq_s, occ, lux, people, int(fan), st))

df = pd.DataFrame(rows, columns=["day", "minute", "temperature", "humidity", "air_quality_ppm",
                                 "occupancy", "light_lux", "people", "fan", "status_now"])
# trend features (per-minute slope over the last TREND_WIN minutes)
for col, name in (("temperature", "temp_slope"), ("air_quality_ppm", "aq_slope"), ("humidity", "hum_slope")):
    df[name] = (df[col] - df[col].shift(TREND_WIN)) / TREND_WIN
# prediction target: worst status in the next HORIZON minutes (including now)
fut = pd.concat([df["status_now"].shift(-k) for k in range(0, HORIZON + 1)], axis=1)
df["status_next"] = fut.max(axis=1)
df = df.dropna().reset_index(drop=True)
df["status_next"] = df["status_next"].astype(int)
df.round(3).to_csv(OUT, index=False)

print(f"rows: {len(df):,}  ->  {OUT}")
print("status_now distribution :", df["status_now"].value_counts().sort_index().to_dict())
print("status_next distribution:", df["status_next"].value_counts().sort_index().to_dict())
