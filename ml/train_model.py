"""
Train the predictive safety model and export it for the ESP32 (TinyML).

Input : lab_environment_dataset.csv (synthetic, or real data logged by
        cloud/mqtt_logger.py with the same columns)
Output: model.h            -> C header with the neural network, copied into firmware/
        metrics.json       -> numbers used in the report
        confusion_matrix.png

Task: from the current readings AND their 10-minute trends, predict the worst
laboratory status in the next 10 minutes (SAFE / WARNING / CRITICAL), so the
system can act before a hazard actually occurs.
"""
import json
import os
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import accuracy_score, f1_score, confusion_matrix, recall_score, precision_score
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
FEATURES = ["temperature", "humidity", "air_quality_ppm", "occupancy", "light_lux",
            "temp_slope", "aq_slope", "hum_slope"]
CLASSES = ["SAFE", "WARNING", "CRITICAL"]
TARGET = "status_next"
HIDDEN = (16, 8)

df = pd.read_csv(os.path.join(HERE, "lab_environment_dataset.csv"))
split_day = int(df["day"].max() * 0.78)
train, test = df[df["day"] <= split_day], df[df["day"] > split_day]
print(f"train {len(train):,} rows (days 0-{split_day}), test {len(test):,} rows")

# balance classes by oversampling minority classes in the training set
rng = np.random.default_rng(0)
parts = []
n_max = train[TARGET].value_counts().max()
for c, g in train.groupby(TARGET):
    parts.append(g.sample(n=n_max // (1 if c == 0 else 2), replace=True, random_state=int(c)))
train_bal = pd.concat(parts)

scaler = StandardScaler().fit(train[FEATURES].values)
Xtr, ytr = scaler.transform(train_bal[FEATURES].values), train_bal[TARGET].values
Xte, yte = scaler.transform(test[FEATURES].values), test[TARGET].values

# ---------------------------------------------------------------- models
models = {
    "Logistic Regression": LogisticRegression(max_iter=2000),
    "Decision Tree (depth 8)": DecisionTreeClassifier(max_depth=8, random_state=0),
    f"Neural Network MLP {HIDDEN}": MLPClassifier(hidden_layer_sizes=HIDDEN, activation="relu",
                                                   max_iter=400, early_stopping=True,
                                                   random_state=1, alpha=1e-4),
}
results = {}
for name, m in models.items():
    m.fit(Xtr, ytr)
    p = m.predict(Xte)
    results[name] = {
        "accuracy": round(accuracy_score(yte, p), 4),
        "macro_f1": round(f1_score(yte, p, average="macro"), 4),
        "recall_critical": round(recall_score(yte, p, labels=[2], average="macro"), 4),
        "precision_critical": round(precision_score(yte, p, labels=[2], average="macro", zero_division=0), 4),
    }
    print(f"{name:32s} {results[name]}")

# baseline: classic threshold system (uses only the CURRENT reading)
p_rule = test["status_now"].values
results["Threshold rules (current reading only)"] = {
    "accuracy": round(accuracy_score(yte, p_rule), 4),
    "macro_f1": round(f1_score(yte, p_rule, average="macro"), 4),
    "recall_critical": round(recall_score(yte, p_rule, labels=[2], average="macro"), 4),
    "precision_critical": round(precision_score(yte, p_rule, labels=[2], average="macro", zero_division=0), 4),
}
print(f"{'Threshold rules':32s} {results['Threshold rules (current reading only)']}")

mlp = models[f"Neural Network MLP {HIDDEN}"]
p_mlp = mlp.predict(Xte)
cm = confusion_matrix(yte, p_mlp, labels=[0, 1, 2])

# ---------------------------------------------------------------- early-warning lead time
now = test["status_now"].values
lead_ml, lead_rule_warn = [], []
onsets = [i for i in range(1, len(now)) if now[i] == 2 and now[i - 1] < 2]
for i in onsets:
    lead = 0
    for k in range(1, 16):              # look back up to 15 minutes
        if i - k < 0 or p_mlp[i - k] < 2:
            break
        lead = k
    lead_ml.append(lead)
    # how early did the plain threshold system at least show WARNING?
    w = 0
    for k in range(1, 16):
        if i - k < 0 or now[i - k] < 1:
            break
        w = k
    lead_rule_warn.append(w)
lead_stats = {
    "critical_episodes_in_test": len(onsets),
    "ml_predicted_before_onset_pct": round(100 * np.mean([l > 0 for l in lead_ml]), 1) if onsets else 0,
    "ml_median_lead_minutes": float(np.median(lead_ml)) if onsets else 0,
    "ml_mean_lead_minutes": round(float(np.mean(lead_ml)), 2) if onsets else 0,
    "rules_critical_lead_minutes": 0.0,
}
print("early warning:", lead_stats)

# ---------------------------------------------------------------- export to C
layers = list(zip(mlp.coefs_, mlp.intercepts_))
n_params = sum(w.size + b.size for w, b in layers)


def carr(name, arr):
    flat = ", ".join(f"{v:.6f}f" for v in np.asarray(arr).ravel())
    return f"static const float {name}[{np.asarray(arr).size}] = {{{flat}}};\n"


# test vectors to verify the ESP32 gives identical output
tv_idx = [int(np.where(yte == c)[0][len(np.where(yte == c)[0]) // 2]) for c in (0, 1, 2)]
tv_x = test[FEATURES].values[tv_idx]
tv_p = mlp.predict_proba(scaler.transform(tv_x))

h = []
h.append("// Auto-generated by ml/train_model.py - do not edit by hand.\n")
h.append("// Predictive lab-safety neural network (TinyML) for ESP32.\n")
h.append(f"// Architecture: {len(FEATURES)} inputs -> " + " -> ".join(str(n) for n in HIDDEN) +
         f" (ReLU) -> 3 outputs (softmax). Parameters: {n_params} ({n_params * 4} bytes).\n")
h.append("// Inputs: " + ", ".join(FEATURES) + "\n")
h.append("// Output: probability of SAFE, WARNING, CRITICAL within the next 10 minutes.\n")
h.append("#pragma once\n#include <math.h>\n\n")
h.append(f"#define ML_N_FEATURES {len(FEATURES)}\n#define ML_N_CLASSES 3\n\n")
h.append(carr("ML_MEAN", scaler.mean_))
h.append(carr("ML_SCALE", scaler.scale_))
for li, (w, b) in enumerate(layers):
    h.append(f"#define ML_L{li}_IN {w.shape[0]}\n#define ML_L{li}_OUT {w.shape[1]}\n")
    h.append(carr(f"ML_W{li}", w))      # row-major [in][out]
    h.append(carr(f"ML_B{li}", b))
h.append(f"#define ML_N_LAYERS {len(layers)}\n\n")
h.append("""static void ml_dense(const float* in, int nIn, const float* W, const float* B,
                     int nOut, float* out, bool relu) {
  for (int o = 0; o < nOut; o++) {
    float s = B[o];
    for (int i = 0; i < nIn; i++) s += in[i] * W[i * nOut + o];
    out[o] = (relu && s < 0) ? 0 : s;
  }
}

// features: raw (unscaled) values in the order listed above.
// probs   : receives 3 class probabilities. Returns the predicted class.
static int ml_predict(const float* features, float* probs) {
  float a[16], b[16];
  for (int i = 0; i < ML_N_FEATURES; i++) a[i] = (features[i] - ML_MEAN[i]) / ML_SCALE[i];
""")
cur, nxt = "a", "b"
for li in range(len(layers)):
    last = li == len(layers) - 1
    h.append(f"  ml_dense({cur}, ML_L{li}_IN, ML_W{li}, ML_B{li}, ML_L{li}_OUT, {nxt}, {'false' if last else 'true'});\n")
    cur, nxt = nxt, cur
h.append(f"""  float mx = {cur}[0];
  for (int i = 1; i < ML_N_CLASSES; i++) if ({cur}[i] > mx) mx = {cur}[i];
  float sum = 0;
  for (int i = 0; i < ML_N_CLASSES; i++) {{ probs[i] = expf({cur}[i] - mx); sum += probs[i]; }}
  int best = 0;
  for (int i = 0; i < ML_N_CLASSES; i++) {{ probs[i] /= sum; if (probs[i] > probs[best]) best = i; }}
  return best;
}}

// Self-test vectors (inputs and expected probabilities from Python)
""")
h.append(carr("ML_TEST_X", tv_x))
h.append(carr("ML_TEST_P", tv_p))
h.append("#define ML_N_TESTS 3\n")
open(os.path.join(HERE, "model.h"), "w").write("".join(h))

# same network for the web dashboard (demo mode runs identical inference)
js_model = {"features": FEATURES, "classes": CLASSES, "mean": scaler.mean_.round(6).tolist(),
            "scale": scaler.scale_.round(6).tolist(),
            "layers": [{"W": w.round(6).tolist(), "b": b.round(6).tolist()} for w, b in layers]}
os.makedirs(os.path.join(HERE, "..", "dashboard"), exist_ok=True)
with open(os.path.join(HERE, "..", "dashboard", "ml_model.js"), "w") as f:
    f.write("// Auto-generated by ml/train_model.py - same network as firmware/model.h\n")
    f.write("window.LAB_MODEL = " + json.dumps(js_model) + ";\n")


# verify: re-implement the C maths in numpy and compare with sklearn
def c_like(x):
    a = (x - scaler.mean_) / scaler.scale_
    for li, (w, b) in enumerate(layers):
        a = a @ w + b
        if li < len(layers) - 1:
            a = np.maximum(a, 0)
    e = np.exp(a - a.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


diff = np.abs(c_like(test[FEATURES].values[:2000]) - mlp.predict_proba(Xte[:2000])).max()
print(f"C-equivalent inference max |diff| vs sklearn: {diff:.2e}")
assert diff < 1e-5


# ---------------------------------------------------------------- confusion matrix image
def draw_cm(cm, path):
    W, H, cell = 760, 640, 170
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    try:
        f, fb = ImageFont.truetype("arial.ttf", 24), ImageFont.truetype("arialbd.ttf", 28)
    except OSError:
        f = fb = ImageFont.load_default()
    ox, oy = 230, 110
    d.text((W / 2 - 230, 20), "Confusion matrix - MLP (test days)", font=fb, fill="#111")
    row_tot = cm.sum(axis=1, keepdims=True)
    for r in range(3):
        d.text((20, oy + r * cell + cell / 2 - 12), f"true {CLASSES[r]}", font=f, fill="#111")
        for c in range(3):
            frac = cm[r, c] / max(1, row_tot[r, 0])
            shade = int(255 - 190 * frac)
            fill = (shade, shade, 255) if r == c else (255, shade, shade)
            d.rectangle((ox + c * cell, oy + r * cell, ox + (c + 1) * cell, oy + (r + 1) * cell),
                        fill=fill, outline="#555", width=2)
            txt = f"{cm[r, c]}\n{100 * frac:.1f}%"
            for k, line in enumerate(txt.split("\n")):
                wdt = d.textlength(line, font=fb if k == 0 else f)
                d.text((ox + c * cell + cell / 2 - wdt / 2, oy + r * cell + 50 + k * 36), line,
                       font=fb if k == 0 else f, fill="#111")
    for c in range(3):
        wdt = d.textlength(f"pred {CLASSES[c]}", font=f)
        d.text((ox + c * cell + cell / 2 - wdt / 2, oy + 3 * cell + 14), f"pred {CLASSES[c]}", font=f, fill="#111")
    im.save(path)


draw_cm(cm, os.path.join(HERE, "confusion_matrix.png"))

json.dump({
    "features": FEATURES, "classes": CLASSES, "horizon_minutes": 10,
    "train_rows": int(len(train)), "test_rows": int(len(test)),
    "architecture": [len(FEATURES), *HIDDEN, 3], "parameters": int(n_params),
    "model_bytes": int(n_params * 4),
    "results": results, "confusion_matrix_mlp": cm.tolist(), "early_warning": lead_stats,
}, open(os.path.join(HERE, "metrics.json"), "w"), indent=2)
print("wrote model.h, metrics.json, confusion_matrix.png")
