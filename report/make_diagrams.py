"""Draws the report figures (architecture, flowchart, ML pipeline, network) as PNG."""
import math
import os
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
INK, BROWN, GOLD = "#2b2118", "#6b5b4b", "#b08a4f"
CREAM, SENS, CPU, OUT, NET, ML = "#fbf7f0", "#f3e7d3", "#f1d9a7", "#e3efdc", "#e4e8f4", "#efe2f2"


def font(size, bold=False):
    for n in (("arialbd.ttf" if bold else "arial.ttf"), "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            pass
    return ImageFont.load_default()


def box(d, xy, text, fill, f=None, outline=GOLD, radius=16, color=INK, title=None):
    d.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=3)
    f = f or font(24)
    x0, y0, x1, y1 = xy
    if title:
        tw = d.textlength(title, font=font(20, True))
        d.rounded_rectangle((x0 + 14, y0 - 16, x0 + 34 + tw, y0 + 16), radius=8, fill=GOLD)
        d.text((x0 + 24, y0 - 12), title, font=font(20, True), fill="white")
    lines = text.split("\n")
    lh = f.size + 7
    ty = (y0 + y1) / 2 - lh * len(lines) / 2 + 3
    for ln in lines:
        w = d.textlength(ln, font=f)
        d.text(((x0 + x1) / 2 - w / 2, ty), ln, font=f, fill=color)
        ty += lh


def arrow(d, p0, p1, color=BROWN, width=4, head=15, dashed=False):
    if dashed:
        L = math.dist(p0, p1); n = int(L // 18)
        for i in range(n):
            a = i / n; b = min(1, (i + 0.55) / n)
            d.line([(p0[0] + (p1[0] - p0[0]) * a, p0[1] + (p1[1] - p0[1]) * a),
                    (p0[0] + (p1[0] - p0[0]) * b, p0[1] + (p1[1] - p0[1]) * b)], fill=color, width=width)
    else:
        d.line([p0, p1], fill=color, width=width)
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    d.polygon([p1, (p1[0] - head * math.cos(ang - .45), p1[1] - head * math.sin(ang - .45)),
               (p1[0] - head * math.cos(ang + .45), p1[1] - head * math.sin(ang + .45))], fill=color)


def poly_arrow(d, pts, **kw):
    for a, b in zip(pts[:-2], pts[1:-1]):
        d.line([a, b], fill=kw.get("color", BROWN), width=kw.get("width", 4))
    arrow(d, pts[-2], pts[-1], **kw)


def title(d, W, t):
    f = font(40, True)
    d.text((W / 2 - d.textlength(t, font=f) / 2, 24), t, font=f, fill=INK)
    d.line([(W / 2 - 180, 82), (W / 2 + 180, 82)], fill=GOLD, width=3)


def architecture():
    W, H = 2000, 1250
    im = Image.new("RGB", (W, H), CREAM); d = ImageDraw.Draw(im)
    title(d, W, "System Architecture - Smart Laboratory Environment Monitoring System")
    sens = [("DHT22\nTemperature & Humidity", 170), ("MQ-135\nAir quality (CO2-eq ppm)", 330),
            ("PIR sensor\nOccupancy", 490), ("LDR\nAmbient light (lux)", 650)]
    d.rounded_rectangle((50, 120, 470, 790), radius=18, outline=GOLD, width=3, fill="#fffdf9")
    d.rounded_rectangle((64, 104, 250, 136), radius=8, fill=GOLD); d.text((78, 108), "1. SENSORS", font=font(20, True), fill="white")
    for t, y in sens:
        box(d, (80, y - 10, 440, y + 120), t, SENS, f=font(24))
    box(d, (620, 300, 980, 640), "ESP32\nMicrocontroller\n\nsensing + rules\n+ TinyML model\n(8-16-8-3 NN)", CPU,
        f=font(26, True), title="2. ESP32")
    arrow(d, (470, 455), (620, 470))
    box(d, (1130, 130, 1480, 250), "OLED display\n(live monitoring)", OUT, f=font(24))
    box(d, (1130, 330, 1480, 520), "Relay module\nautomatic response", OUT, f=font(24), title="3. RESPONSE")
    for i, t in enumerate(("Exhaust fan", "Buzzer", "Warning LEDs (G/Y/R)")):
        box(d, (1600, 300 + i * 90, 1940, 370 + i * 90), t, OUT, f=font(23))
        arrow(d, (1480, 425), (1600, 335 + i * 90))
    arrow(d, (980, 400), (1130, 190)); arrow(d, (980, 450), (1130, 425))
    box(d, (1060, 640, 1240, 780), "4. Wi-Fi\nMQTT", NET, f=font(24, True))
    box(d, (1320, 620, 1580, 800), "5. CLOUD\nDATABASE\nThingSpeak /\nSQLite logger", NET, f=font(22, True))
    box(d, (1640, 620, 1940, 800), "6. IoT DASHBOARD\n(web / mobile)\nlive + history", NET, f=font(22, True))
    box(d, (1640, 880, 1940, 1040), "7. NOTIFICATIONS\nTelegram bot\n(+ browser alerts)", NET, f=font(22, True))
    poly_arrow(d, [(980, 580), (1010, 580), (1010, 710), (1060, 710)])
    arrow(d, (1240, 710), (1320, 710)); arrow(d, (1580, 710), (1640, 710)); arrow(d, (1790, 800), (1790, 880))
    box(d, (80, 930, 400, 1110), "8. HISTORICAL\nSENSOR DATA\n(1-min dataset)", ML, f=font(22, True))
    box(d, (500, 930, 820, 1110), "9. ML TRAINING\nscikit-learn MLP\n-> model.h (C)", ML, f=font(22, True))
    box(d, (920, 930, 1240, 1110), "10. PREDICTIVE\nSAFETY ANALYSIS\n(next 10 min)", ML, f=font(22, True))
    arrow(d, (400, 1020), (500, 1020)); arrow(d, (820, 1020), (920, 1020))
    poly_arrow(d, [(1080, 930), (1080, 880), (800, 880), (800, 640)], dashed=True)
    d.text((830, 850), "deployed on ESP32 (TinyML)", font=font(20), fill=BROWN)
    poly_arrow(d, [(1450, 800), (1450, 1180), (240, 1180), (240, 1110)], dashed=True)
    d.text((620, 1150), "logged data used to retrain the model", font=font(20), fill=BROWN)
    im.save(os.path.join(HERE, "architecture.png"))


def flowchart():
    W, H = 1500, 2250
    im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
    f = font(25); cx = 650

    def proc(y, t, h=96, x=cx, w=500, fill=SENS):
        box(d, (x - w / 2, y, x + w / 2, y + h), t, fill, f=f, radius=10)

    def dec(y, t, x=cx, w=470, h=170):
        pts = [(x, y), (x + w / 2, y + h / 2), (x, y + h), (x - w / 2, y + h / 2)]
        d.polygon(pts, fill=CPU); d.line(pts + [pts[0]], fill=GOLD, width=3)
        box(d, (x - w / 2, y, x + w / 2, y + h), t, None, outline=None, f=f)

    d.ellipse((cx - 170, 20, cx + 170, 100), fill="#eee6da", outline=GOLD, width=3)
    box(d, (cx - 170, 20, cx + 170, 100), "START", None, outline=None, f=font(26, True))
    arrow(d, (cx, 100), (cx, 140))
    proc(140, "Init OLED, DHT22, relay, LEDs;\nself-test LEDs + buzzer")
    arrow(d, (cx, 236), (cx, 276))
    proc(276, "Calibrate MQ-135 (R0 at 420 ppm);\nAI model self-test vs Python")
    arrow(d, (cx, 372), (cx, 412))
    proc(412, "Connect Wi-Fi, NTP clock, MQTT")
    arrow(d, (cx, 508), (cx, 548))
    proc(548, "Every 1 s: read DHT22, MQ-135,\nLDR, PIR -> ppm, lux, occupancy")
    arrow(d, (cx, 644), (cx, 684))
    proc(684, "Rule check -> SAFE / WARNING /\nCRITICAL + reason", fill=CPU)
    arrow(d, (cx, 780), (cx, 820))
    proc(820, "Every model-minute: update 10-min\nhistory, slopes -> run neural network", fill=ML)
    arrow(d, (cx, 916), (cx, 956))
    dec(956, "AI predicts CRITICAL\n(p >= 0.6) while\nnot yet critical?")
    arrow(d, (cx + 235, 1041), (1020, 1041)); d.text((cx + 245, 1000), "Yes", font=f, fill=INK)
    proc(986, "EARLY WARNING:\nfan ON, yellow blink,\nchirp, Telegram", h=120, x=1230, w=420, fill="#fdf1d6")
    arrow(d, (cx, 1126), (cx, 1166)); d.text((cx + 12, 1128), "No", font=f, fill=INK)
    dec(1166, "Status?")
    arrow(d, (cx + 235, 1251), (1020, 1251)); d.text((cx + 245, 1212), "CRITICAL", font=f, fill=INK)
    proc(1196, "Red LED, siren, fan ON,\nTelegram alert", h=110, x=1230, w=420, fill="#fbe4e1")
    d.line([(cx - 235, 1251), (210, 1251)], fill=BROWN, width=4); d.text((cx - 380, 1212), "WARNING", font=f, fill=INK)
    arrow(d, (cx, 1336), (cx, 1376)); d.text((cx + 12, 1338), "SAFE", font=f, fill=INK)
    proc(1376, "Green LED; fan auto-off", fill=OUT)
    arrow(d, (cx, 1472), (cx, 1512))
    proc(1512, "Update OLED (every 0.5 s)")
    arrow(d, (cx, 1608), (cx, 1648))
    proc(1648, "Publish JSON to MQTT (3 s);\nThingSpeak upload (20 s)", fill=NET)
    arrow(d, (cx, 1744), (cx, 1784))
    proc(1784, "Handle button (mute / test) and\ndashboard commands", fill=NET)
    # warning branch box on left
    box(d, (60, 1300, 360, 1440), "WARNING:\nyellow LED,\nfan ON if air/heat", "#fdf1d6", f=font(22), radius=10)
    arrow(d, (210, 1251), (210, 1300))
    poly_arrow(d, [(210, 1440), (210, 1560), (cx - 250, 1560)])
    # join right branches
    d.line([(1440, 1046), (1470, 1046), (1470, 1560)], fill=BROWN, width=4)
    d.line([(1440, 1251), (1470, 1251)], fill=BROWN, width=4)
    arrow(d, (1470, 1560), (cx + 250, 1560))
    # loop
    d.line([(cx, 1880), (cx, 1960), (25, 1960), (25, 596)], fill=BROWN, width=4)
    arrow(d, (25, 596), (cx - 250, 596))
    d.text((35, 1700), "loop", font=f, fill=BROWN)
    im = im.crop((0, 0, W, 1990))
    im.save(os.path.join(HERE, "flowchart.png"))


def ml_pipeline():
    W, H = 2000, 420
    im = Image.new("RGB", (W, H), CREAM); d = ImageDraw.Draw(im)
    title(d, W, "ML / TinyML Pipeline")
    steps = [("Data collection\nsensors -> MQTT ->\nSQLite / ThingSpeak", SENS),
             ("Pre-processing\n1-min resampling,\n10-min slopes", SENS),
             ("Labelling\nworst status in\nnext 10 minutes", CPU),
             ("Training\nMLP 8-16-8-3,\nclass balancing", ML),
             ("Evaluation\ntime-split test,\nlead-time analysis", ML),
             ("Export\nweights -> model.h\n(1.2 KB, C code)", OUT),
             ("Edge inference\non ESP32 every\nmodel-minute", OUT)]
    w, gap, x = 240, 32, 40
    for i, (t, c) in enumerate(steps):
        box(d, (x, 140, x + w, 340), t, c, f=font(22))
        if i < len(steps) - 1:
            arrow(d, (x + w, 240), (x + w + gap, 240))
        x += w + gap
    im.save(os.path.join(HERE, "ml_pipeline.png"))


def network():
    W, H = 1500, 760
    im = Image.new("RGB", (W, H), "white"); d = ImageDraw.Draw(im)
    title(d, W, "Neural network deployed on the ESP32")
    inputs = ["Temperature", "Humidity", "Air quality", "Occupancy", "Light", "Temp slope", "Air slope", "Hum. slope"]
    layers = [8, 16, 8, 3]
    xs = [260, 620, 960, 1260]
    pos = []
    for li, n in enumerate(layers):
        top, bot = 130, 700
        ys = [top + (bot - top) * (i + 0.5) / n for i in range(n)]
        pos.append([(xs[li], y) for y in ys])
    for li in range(3):
        for a in pos[li]:
            for b in pos[li + 1]:
                d.line([a, b], fill="#e2d6c3", width=1)
    colors = [SENS, ML, ML, OUT]
    for li, pts in enumerate(pos):
        r = 13 if li in (1, 2) else 18
        for i, (x, y) in enumerate(pts):
            d.ellipse((x - r, y - r, x + r, y + r), fill=colors[li], outline=GOLD, width=2)
            if li == 0:
                d.text((x - 30 - d.textlength(inputs[i], font=font(22)), y - 12), inputs[i], font=font(22), fill=INK)
            if li == 3:
                d.text((x + 30, y - 12), ["P(SAFE)", "P(WARNING)", "P(CRITICAL)"][i], font=font(22), fill=INK)
    for x, t in zip(xs, ["Input (8)\nstandardised", "Dense 16\nReLU", "Dense 8\nReLU", "Dense 3\nSoftmax"]):
        for k, ln in enumerate(t.split("\n")):
            d.text((x - d.textlength(ln, font=font(20, True)) / 2, 712 + k * 22 - 4), ln, font=font(20, True), fill=BROWN)
    im.save(os.path.join(HERE, "network.png"))


if __name__ == "__main__":
    architecture(); flowchart(); ml_pipeline(); network()
    print("figures written")
