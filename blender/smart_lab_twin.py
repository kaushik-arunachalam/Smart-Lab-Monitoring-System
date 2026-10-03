"""
Smart Laboratory Environment Monitoring System - Blender digital twin
=======================================================================
Builds a 3D laboratory with the monitoring node (DHT22, MQ-135, PIR, LDR,
OLED, LEDs, buzzer), exhaust fan, lights, AC unit, students and a wall
dashboard, then animates the AI early-warning story (20 s @ 24 fps):

  f   1-60   lab empty, lights off, status SAFE
  f  60-140  students enter -> PIR "occupied", lights on (LDR lux rises)
  f 140-230  CO2 builds up (visible haze) and temperature rises -> WARNING
  f 230      AI model predicts CRITICAL within 10 min -> early warning:
             yellow LED blinks, exhaust fan starts, Telegram alert
  f 230-380  fan clears the air -> CRITICAL is never reached -> SAFE
  f 400-480  students leave, lights switch off

The OLED and the wall dashboard show live numbers for every frame.

Usage (Blender 3.6 / 4.x / 5.x):
  Scripting workspace -> Open this file -> Run Script -> press Space.
  Render -> Render Animation saves smart_lab_twin_####.mp4 next to the .blend.
  No simulation baking is needed (the air haze is an animated volume).
  Re-run the script after reopening the .blend (the text updater is a handler).

Live digital-twin mode (LIVE_MQTT = True):
  Mirrors the ESP32 in real time via MQTT (smartlab/<DEVICE_ID>/data).
  Needs paho-mqtt in Blender's Python:
      <blender>/<version>/python/bin/python -m pip install paho-mqtt
"""
import bpy
import math
from mathutils import Vector

FPS, FRAME_END = 24, 480
LIVE_MQTT = False
MQTT_HOST, DEVICE_ID = "broker.hivemq.com", "smartlab-cse24"

# ---------------------------------------------------------------------------
# Scenario timeline (frame -> value), linear interpolation between points
# ---------------------------------------------------------------------------
TIMELINE = {
    "temp":   [(1, 23.1), (140, 23.6), (230, 26.4), (300, 26.0), (380, 24.6), (480, 23.8)],
    "hum":    [(1, 45), (140, 47), (230, 52), (380, 49), (480, 46)],
    "aq":     [(1, 450), (80, 460), (140, 620), (230, 1180), (260, 1260), (320, 980), (380, 760), (480, 560)],
    "lux":    [(1, 40), (71, 40), (73, 520), (431, 520), (433, 40), (480, 40)],
    "occ":    [(1, 0), (72, 0), (73, 1), (430, 1), (431, 0)],
    "pcrit":  [(1, 0.0), (200, 0.05), (230, 0.78), (270, 0.66), (320, 0.2), (360, 0.02), (480, 0.0)],
}
F_ENTER, F_LIGHTS, F_WARN, F_AI, F_SAFE, F_LEAVE, F_DARK = 70, 72, 205, 230, 345, 400, 433


def val(key, f):
    pts = TIMELINE[key]
    if f <= pts[0][0]:
        return pts[0][1]
    for (f0, v0), (f1, v1) in zip(pts, pts[1:]):
        if f0 <= f <= f1:
            return v0 + (v1 - v0) * (f - f0) / (f1 - f0)
    return pts[-1][1]


def status_at(f):
    t, h, a, o, l = val("temp", f), val("hum", f), val("aq", f), val("occ", f) > 0.5, val("lux", f)
    if t > 32 or t < 15 or h > 70 or h < 20 or a > 2000:
        return "CRITICAL", "Critical conditions"
    if a > 1000:
        return "WARNING", "Poor air quality"
    if t > 27 or t < 18:
        return "WARNING", "Temperature abnormal"
    if h > 60 or h < 30:
        return "WARNING", "Humidity abnormal"
    if o and l < 150:
        return "WARNING", "Insufficient light"
    return "SAFE", ("Lab empty, lights on" if (not o and l > 300) else "Environment Stable")


def ai_early(f):
    return val("pcrit", f) >= 0.6


def aq_label(p):
    return "Good" if p < 800 else "Moderate" if p < 1000 else "Poor" if p < 2000 else "Hazardous"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def clear_scene():
    for h in list(bpy.app.handlers.frame_change_pre):
        if getattr(h, "__name__", "") == "smartlab_update_texts":
            bpy.app.handlers.frame_change_pre.remove(h)
    if bpy.context.object and bpy.context.object.mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete(use_global=False)
    for coll in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras, bpy.data.curves):
        for b in list(coll):
            if b.users == 0:
                coll.remove(b)


def set_input(node, names, value):
    for n in names if isinstance(names, (list, tuple)) else [names]:
        if n in node.inputs:
            node.inputs[n].default_value = value
            return


def mat(name, color, metallic=0.0, rough=0.5, emit=None, strength=0.0, alpha=1.0, transmission=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    set_input(b, "Base Color", (*color, 1))
    set_input(b, "Metallic", metallic)
    set_input(b, "Roughness", rough)
    if transmission:
        set_input(b, ["Transmission Weight", "Transmission"], transmission)
    if emit is not None:
        set_input(b, ["Emission Color", "Emission"], (*emit, 1))
        set_input(b, "Emission Strength", strength)
    if alpha < 1:
        set_input(b, "Alpha", alpha)
        try:
            m.surface_render_method = 'BLENDED'
        except AttributeError:
            m.blend_method = 'BLEND'
    return m


def emission(m):
    return m.node_tree.nodes.get("Principled BSDF").inputs["Emission Strength"]


def key_emit(m, f, s):
    sock = emission(m)
    sock.default_value = s
    sock.keyframe_insert("default_value", frame=f)


def fcurves_of(id_block):
    ad = getattr(id_block, "animation_data", None)
    if not ad or not ad.action:
        return []
    try:
        return list(ad.action.fcurves)
    except AttributeError:                       # Blender 5 layered actions
        out = []
        for layer in ad.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    out.extend(bag.fcurves)
        return out


def interp(id_block, mode):
    for fc in fcurves_of(id_block):
        for kp in fc.keyframe_points:
            kp.interpolation = mode


def box(name, size, loc, m=None, bevel=0.0, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=loc, rotation=rot)
    o = bpy.context.object
    o.name = name
    o.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        md = o.modifiers.new("Bevel", 'BEVEL'); md.width = bevel; md.segments = 3
    if m:
        o.data.materials.append(m)
    return o


def cyl(name, r, d, loc, m=None, rot=(0, 0, 0), v=32):
    bpy.ops.mesh.primitive_cylinder_add(radius=r, depth=d, location=loc, rotation=rot, vertices=v)
    o = bpy.context.object; o.name = name
    bpy.ops.object.shade_smooth()
    if m:
        o.data.materials.append(m)
    return o


def sphere(name, r, loc, m=None):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=r, location=loc)
    o = bpy.context.object; o.name = name
    bpy.ops.object.shade_smooth()
    if m:
        o.data.materials.append(m)
    return o


def text(name, body, loc, size, m, rot=(math.radians(90), 0, 0), align='LEFT', font_mono=False):
    bpy.ops.object.text_add(location=loc, rotation=rot)
    o = bpy.context.object; o.name = name
    o.data.body = body
    o.data.size = size
    o.data.align_x = align
    if m:
        o.data.materials.append(m)
    return o


def key_vis(o, ranges):
    o.hide_render = o.hide_viewport = True
    o.keyframe_insert("hide_render", frame=1); o.keyframe_insert("hide_viewport", frame=1)
    for s, e in ranges:
        o.hide_render = o.hide_viewport = False
        o.keyframe_insert("hide_render", frame=s); o.keyframe_insert("hide_viewport", frame=s)
        o.hide_render = o.hide_viewport = True
        o.keyframe_insert("hide_render", frame=e); o.keyframe_insert("hide_viewport", frame=e)


# ---------------------------------------------------------------------------
# Build the lab
# ---------------------------------------------------------------------------
clear_scene()
scene = bpy.context.scene
scene.frame_start, scene.frame_end, scene.render.fps = 1, FRAME_END, FPS

M = {
    "floor": mat("Floor", (0.62, 0.6, 0.56), rough=0.35),
    "wall": mat("Wall", (0.93, 0.9, 0.85), rough=0.85),
    "bench": mat("BenchTop", (0.12, 0.1, 0.09), rough=0.3),
    "cab": mat("Cabinet", (0.78, 0.74, 0.66), rough=0.5),
    "steel": mat("Steel", (0.8, 0.8, 0.82), metallic=1, rough=0.25),
    "dark": mat("DarkPlastic", (0.04, 0.04, 0.045), rough=0.5),
    "white": mat("WhitePlastic", (0.95, 0.95, 0.95), rough=0.4),
    "glass": mat("Glass", (0.9, 0.95, 1), rough=0.05, transmission=1, alpha=0.3),
    "blue": mat("DHT22Blue", (0.1, 0.35, 0.8), rough=0.5),
    "pcb": mat("PCB", (0.05, 0.3, 0.12), rough=0.4),
    "gold": mat("Accent", (0.69, 0.54, 0.31), metallic=0.4, rough=0.4),
    "screen": mat("ScreenBG", (0.01, 0.01, 0.01), emit=(0.02, 0.02, 0.03), strength=1),
    "oledtxt": mat("OLEDText", (0.8, 0.95, 1), emit=(0.8, 0.95, 1), strength=6),
    "dashtxt": mat("DashText", (1, 0.95, 0.85), emit=(1, 0.93, 0.8), strength=4),
    "caption": mat("Caption", (1, 1, 1), emit=(1, 1, 1), strength=2),
    "ledG": mat("LED_Green", (0.05, 0.3, 0.05), emit=(0.1, 1, 0.1)),
    "ledY": mat("LED_Yellow", (0.3, 0.25, 0.02), emit=(1, 0.75, 0.05)),
    "ledR": mat("LED_Red", (0.3, 0.03, 0.03), emit=(1, 0.05, 0.03)),
    "lamp": mat("CeilingPanel", (0.9, 0.9, 0.9), emit=(1, 0.97, 0.9)),
    "acled": mat("AC_LED", (0.1, 0.3, 0.1), emit=(0.1, 1, 0.2), strength=8),
    "skin": mat("Skin", (0.72, 0.52, 0.4), rough=0.6),
    "coat": mat("LabCoat", (0.95, 0.95, 0.97), rough=0.7),
    "phone": mat("PhoneScreen", (0.1, 0.12, 0.2), emit=(0.35, 0.6, 1), strength=3),
}

W, D, H = 9.0, 7.0, 3.2
box("Floor", (W, D, 0.1), (0, 0, -0.05), M["floor"])
box("BackWall", (W, 0.15, H), (0, D / 2, H / 2), M["wall"])
box("LeftWall", (0.15, D, H), (-W / 2, 0, H / 2), M["wall"])
box("RightWall", (0.15, D, H), (W / 2, 0, H / 2), M["wall"])
box("Ceiling", (W, D, 0.1), (0, 0, H + 0.05), M["wall"])
box("Window", (2.4, 0.05, 1.2), (2.2, D / 2 - 0.08, 1.9), M["glass"])

# benches with glassware
for i, (x, y) in enumerate([(-2.3, 2.6), (1.9, 2.6), (-2.0, 0.2), (1.6, 0.2)]):
    box(f"BenchCab{i}", (2.8, 0.8, 0.85), (x, y, 0.425), M["cab"], bevel=0.01)
    box(f"BenchTop{i}", (2.9, 0.9, 0.05), (x, y, 0.875), M["bench"], bevel=0.01)
    for j in range(3):
        cyl(f"Flask{i}_{j}", 0.05 + 0.015 * j, 0.16 + 0.04 * j, (x - 0.8 + 0.7 * j, y + 0.1, 0.98 + 0.02 * j), M["glass"])
# fume hood
box("FumeHood", (1.6, 0.9, 2.2), (-3.6, 2.9, 1.1), M["cab"], bevel=0.02)
box("FumeHoodGlass", (1.3, 0.02, 0.9), (-3.6, 2.44, 1.35), M["glass"])
box("Door", (0.06, 1.1, 2.1), (W / 2 - 0.05, -2.3, 1.05), M["cab"], bevel=0.01)

# ceiling lights (emission keyed from the lux timeline)
for i, x in enumerate((-2.2, 2.2)):
    box(f"LightPanel{i}", (1.4, 0.6, 0.03), (x, 1.0, H - 0.02), M["lamp"])
    bpy.ops.object.light_add(type='AREA', location=(x, 1.0, H - 0.06))
    L = bpy.context.object; L.name = f"LightArea{i}"; L.data.size = 1.4
    for f, e in ((1, 20), (F_LIGHTS - 2, 20), (F_LIGHTS, 500), (F_DARK - 2, 500), (F_DARK, 20)):
        L.data.energy = e; L.data.keyframe_insert("energy", frame=f)
for f, e in ((1, 0.2), (F_LIGHTS - 2, 0.2), (F_LIGHTS, 12), (F_DARK - 2, 12), (F_DARK, 0.2)):
    key_emit(M["lamp"], f, e)
bpy.ops.object.light_add(type='SUN', location=(0, -6, 6), rotation=(math.radians(60), 0, math.radians(-25)))
bpy.context.object.data.energy = 1.2

# AC unit on the right wall
box("ACUnit", (0.25, 1.2, 0.35), (W / 2 - 0.15, 1.0, 2.6), M["white"], bevel=0.03)
cyl("ACLed", 0.02, 0.01, (W / 2 - 0.28, 1.45, 2.55), M["acled"], rot=(0, math.radians(90), 0))

# --- exhaust fan on the left wall --------------------------------------------
FAN = Vector((-W / 2 + 0.1, -0.8, 2.3))
box("FanHousing", (0.14, 0.7, 0.7), FAN, M["dark"], bevel=0.02)
rotor = bpy.data.objects.new("FanRotor", None); scene.collection.objects.link(rotor)
rotor.location = FAN + Vector((0.09, 0, 0))
for b in range(5):
    piv = bpy.data.objects.new(f"BladePivot{b}", None); scene.collection.objects.link(piv)
    piv.parent = rotor; piv.rotation_euler = (b * 2 * math.pi / 5, 0, 0)
    bl = box(f"FanBlade{b}", (0.01, 0.09, 0.28), (0, 0, 0.15), M["steel"]); bl.rotation_euler = (math.radians(15), 0, 0)
    bl.parent = piv
cyl("FanHub", 0.05, 0.05, FAN + Vector((0.1, 0, 0)), M["steel"], rot=(0, math.radians(90), 0))
text("FanLabel", "EXHAUST FAN", FAN + Vector((0.09, 0.32, 0.42)), 0.07, M["bench"], rot=(math.radians(90), 0, math.radians(90)))
rotor.rotation_euler = (0, 0, 0); rotor.keyframe_insert("rotation_euler", frame=F_AI)
rotor.rotation_euler = (math.radians(540), 0, 0); rotor.keyframe_insert("rotation_euler", frame=F_AI + 24)
spin_end = 540 + 900 * (F_LEAVE - F_AI - 24) / 24
rotor.rotation_euler = (math.radians(spin_end), 0, 0); rotor.keyframe_insert("rotation_euler", frame=F_LEAVE)
rotor.rotation_euler = (math.radians(spin_end + 400), 0, 0); rotor.keyframe_insert("rotation_euler", frame=F_LEAVE + 30)
interp(rotor, 'LINEAR')

# --- monitoring node on the left wall (the ESP32 system) ----------------------
N = Vector((-W / 2 + 0.1, 0.9, 1.45))
box("NodeEnclosure", (0.05, 0.62, 0.42), N, M["white"], bevel=0.01)
screen = box("OLEDGlass", (0.012, 0.32, 0.17), N + Vector((0.03, -0.08, 0.06)), M["screen"])
box("DHT22", (0.03, 0.07, 0.1), N + Vector((0.035, 0.21, 0.1)), M["blue"])
box("MQ135Board", (0.012, 0.09, 0.09), N + Vector((0.03, 0.21, -0.06)), M["pcb"])
cyl("MQ135Head", 0.03, 0.03, N + Vector((0.05, 0.21, -0.06)), M["steel"], rot=(0, math.radians(90), 0))
sphere("PIRDome", 0.035, N + Vector((0.035, -0.23, -0.12)), M["white"])
cyl("LDR", 0.012, 0.012, N + Vector((0.035, 0.1, 0.17)), M["gold"], rot=(0, math.radians(90), 0))
for k, (m, dy) in enumerate([(M["ledG"], -0.19), (M["ledY"], -0.13), (M["ledR"], -0.07)]):
    cyl(f"StatusLED{k}", 0.013, 0.02, N + Vector((0.035, dy, -0.13)), m, rot=(0, math.radians(90), 0))
cyl("Buzzer", 0.025, 0.02, N + Vector((0.035, 0.04, -0.13)), M["dark"], rot=(0, math.radians(90), 0))
text("NodeLabel", "SMART LAB MONITOR  (ESP32)\nDHT22 . MQ-135 . PIR . LDR", N + Vector((0.035, -0.28, 0.25)), 0.035, M["bench"],
     rot=(math.radians(90), 0, math.radians(90)))
OLED_ROT = (math.radians(90), 0, math.radians(90))
oled_text = text("OLEDText", "", N + Vector((0.038, -0.225, 0.125)), 0.017, M["oledtxt"], rot=OLED_ROT)
oled_text.data.space_line = 0.95

# LED program derived from the timeline
key_emit(M["ledG"], 1, 25); key_emit(M["ledY"], 1, 0); key_emit(M["ledR"], 1, 0)
for f in range(2, FRAME_END + 1):
    st, _ = status_at(f); prev, _ = status_at(f - 1)
    early, pearly = ai_early(f), ai_early(f - 1)
    if (st, early) != (prev, pearly) or (early and f % 6 == 0):
        blink_on = (f // 6) % 2 == 0
        key_emit(M["ledG"], f, 25 if st == "SAFE" and not early else 0)
        key_emit(M["ledY"], f, 25 if st == "WARNING" or (early and blink_on) else 0)
        key_emit(M["ledR"], f, 25 if st == "CRITICAL" else 0)
for _m in (M["ledG"], M["ledY"], M["ledR"]):
    interp(_m.node_tree, 'CONSTANT')

# --- wall dashboard (big screen on back wall) ----------------------------------
DB = Vector((-0.3, D / 2 - 0.1, 2.1))
box("DashFrame", (2.2, 0.05, 1.15), DB, M["dark"], bevel=0.01)
box("DashScreen", (2.08, 0.01, 1.03), DB + Vector((0, -0.03, 0)), M["screen"])
dash_title = text("DashTitle", "SMART LAB  -  LIVE DASHBOARD", DB + Vector((-0.98, -0.045, 0.4)), 0.075, M["gold"])
dash_text = text("DashText", "", DB + Vector((-0.98, -0.045, 0.27)), 0.07, M["dashtxt"])
dash_text.data.space_line = 1.15

# --- phone notification (Telegram) ----------------------------------------------
phone = box("Phone", (0.36, 0.02, 0.7), (0, 0, 0), M["dark"], bevel=0.02)
phone_scr = box("PhoneScreen", (0.32, 0.005, 0.62), (0, -0.012, 0), M["phone"])
phone_scr.parent = phone
ptxt = text("PhoneText", "Telegram\n\nSmart Lab:\nAI EARLY\nWARNING\nCRITICAL in\n< 10 min\nFan started", (-0.14, -0.02, 0.25),
            0.035, M["caption"])
ptxt.parent = phone

# --- CO2 / air-quality haze (animated volume, no baking) ----------------------
haze = box("AirHaze", (W - 0.3, D - 0.3, H - 0.1), (0, 0, H / 2))
hm = bpy.data.materials.new("HazeVolume"); hm.use_nodes = True
nt = hm.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)
out = nt.nodes.new("ShaderNodeOutputMaterial")
vol = nt.nodes.new("ShaderNodeVolumePrincipled")
set_input(vol, "Color", (0.75, 0.65, 0.9, 1))
nt.links.new(vol.outputs[0], out.inputs["Volume"])
haze.data.materials.append(hm)
haze.display_type = 'BOUNDS'
dens = vol.inputs["Density"]
for f in range(1, FRAME_END + 1, 10):
    dens.default_value = max(0.0, (val("aq", f) - 550) / 1000) * 0.06
    dens.keyframe_insert("default_value", frame=f)

# --- students (simple figures) walking in ----------------------------------------
seats = [(-3.0, 1.9), (-2.1, 1.9), (-1.2, 1.9), (1.2, 1.9), (2.1, 1.9), (2.9, 1.9),
         (-2.6, -0.5), (-1.5, -0.5), (1.0, -0.5), (2.2, -0.5)]
door = Vector((W / 2 - 0.5, -2.3, 0))
for i, (sx, sy) in enumerate(seats):
    root = bpy.data.objects.new(f"Student{i}", None); scene.collection.objects.link(root)
    body = cyl(f"StudentBody{i}", 0.18, 1.1, (0, 0, 0.75), M["coat"]); body.parent = root
    head = sphere(f"StudentHead{i}", 0.12, (0, 0, 1.45), M["skin"]); head.parent = root
    s_in = F_ENTER + i * 5
    root.location = door; root.keyframe_insert("location", frame=s_in)
    root.location = (sx, sy, 0); root.keyframe_insert("location", frame=s_in + 40)
    root.keyframe_insert("location", frame=F_LEAVE + i * 2)
    root.location = door; root.keyframe_insert("location", frame=F_LEAVE + i * 2 + 30)
    for part in (body, head):
        key_vis(part, [(s_in, F_LEAVE + i * 2 + 31)])

# ---------------------------------------------------------------------------
# Camera, captions
# ---------------------------------------------------------------------------
bpy.ops.object.camera_add(location=(3.6, -6.2, 2.6))
cam = bpy.context.object; cam.name = "Camera"; scene.camera = cam; cam.data.lens = 24
tgt = bpy.data.objects.new("CamTarget", None); scene.collection.objects.link(tgt)
tr = cam.constraints.new('TRACK_TO'); tr.target = tgt; tr.track_axis = 'TRACK_NEGATIVE_Z'; tr.up_axis = 'UP_Y'
for f, loc, t in ((1, (3.6, -6.2, 2.6), (-0.8, 1.2, 1.3)),
                  (F_ENTER + 50, (2.4, -4.8, 2.2), (-1.5, 1.2, 1.3)),
                  (F_AI - 30, (-1.9, -0.9, 1.6), (-4.4, 0.9, 1.45)),
                  (F_AI + 60, (-1.9, -0.7, 1.6), (-4.4, 0.9, 1.45)),
                  (F_SAFE, (1.5, -2.6, 2.0), (-0.3, 3.4, 2.0)),
                  (FRAME_END, (3.6, -6.2, 2.6), (-0.8, 1.2, 1.3))):
    cam.location = loc; cam.keyframe_insert("location", frame=f)
    tgt.location = t; tgt.keyframe_insert("location", frame=f)

phone.parent = cam
phone.location = (0.33, -0.12, -1.2)
phone.rotation_euler = (math.radians(90), 0, 0)
phone.scale = (0.55, 0.55, 0.55)
for o in (phone, phone_scr, ptxt):
    key_vis(o, [(F_AI + 6, F_AI + 110)])

captions = [
    (1, F_ENTER, "Empty laboratory - sensors monitoring 24/7"),
    (F_ENTER, F_WARN, "Students enter - PIR detects occupancy, LDR confirms lights ON"),
    (F_WARN, F_AI, "CO2 builds up - status WARNING (poor air quality)"),
    (F_AI, F_AI + 115, "AI predicts CRITICAL within 10 minutes - fan starts early, Telegram alert"),
    (F_AI + 115, F_LEAVE, "Hazard prevented - CRITICAL never reached, air back to SAFE"),
    (F_LEAVE, FRAME_END + 1, "Lab empties - lights off, data logged to the cloud for retraining"),
]
for i, (s, e, t) in enumerate(captions):
    c = text(f"Caption{i}", t, (0, 0, 0), 0.028, M["caption"], rot=(0, 0, 0), align='CENTER')
    c.parent = cam; c.location = (0, -0.34, -1.0)
    key_vis(c, [(s, e)])
title = text("Title", "SMART LABORATORY ENVIRONMENT MONITORING SYSTEM  -  AI early warning demo", (0, 0, 0), 0.022,
             M["caption"], rot=(0, 0, 0), align='CENTER')
title.parent = cam; title.location = (0, 0.36, -1.0)


# ---------------------------------------------------------------------------
# Live numbers on OLED + wall dashboard (frame handler)
# ---------------------------------------------------------------------------
def frame_texts(t, h, a, occ, lux, st, reason, pcrit, early, fan, clock):
    oled = (f"{clock}\n"
            f"Temp    : {t:.1f} C\n"
            f"Humidity: {h:.0f} %\n"
            f"Air     : {aq_label(a)} {a:.0f}\n"
            f"Occupied: {'YES' if occ else 'NO'} {lux:.0f}lx\n"
            f"Status  : {st}\n"
            f"{'AI:CRITICAL in 10m!' if early else reason}")
    dash = (f"Temperature   {t:5.1f} C        Humidity   {h:3.0f} %\n"
            f"Air quality   {a:5.0f} ppm ({aq_label(a)})\n"
            f"Occupancy     {'Occupied' if occ else 'Vacant'}       Light {lux:4.0f} lx\n"
            f"STATUS        {st}\n"
            f"AI next 10 min: P(critical) = {pcrit * 100:3.0f} %\n"
            f"Fan {'ON ' if fan else 'OFF'}   Buzzer {'CHIRP' if early else 'OFF'}   Cloud SYNCED")
    return oled, dash


def smartlab_update_texts(scn, *_):
    f = scn.frame_current
    t, h, a, lux = val("temp", f), val("hum", f), val("aq", f), val("lux", f)
    occ = val("occ", f) > 0.5
    st, reason = status_at(f)
    early = ai_early(f)
    fan = f >= F_AI and f < F_LEAVE + 30
    minutes = 9 * 60 + int(f / 4)                     # 1 lab minute every 4 frames from 09:00
    clock = f"{(minutes // 60 - 1) % 12 + 1:02d}:{minutes % 60:02d} {'AM' if minutes < 720 else 'PM'}"
    o, d = frame_texts(t, h, a, occ, lux, st, reason, val("pcrit", f), early, fan, clock)
    ob = bpy.data.objects.get("OLEDText"); db = bpy.data.objects.get("DashText")
    if ob:
        ob.data.body = o
    if db:
        db.data.body = d


bpy.app.handlers.frame_change_pre.append(smartlab_update_texts)
scene.frame_set(1)
smartlab_update_texts(scene)

# ---------------------------------------------------------------------------
# Render settings
# ---------------------------------------------------------------------------
for eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
    try:
        scene.render.engine = eng
        break
    except TypeError:
        continue
try:
    scene.eevee.use_bloom = True
except AttributeError:
    pass
scene.render.resolution_x, scene.render.resolution_y = 1920, 1080
scene.render.filepath = "//smart_lab_twin_"
try:
    scene.render.image_settings.file_format = 'FFMPEG'
    scene.render.ffmpeg.format = 'MPEG4'
    scene.render.ffmpeg.codec = 'H264'
except TypeError:
    pass
world = scene.world or bpy.data.worlds.new("World"); scene.world = world
world.use_nodes = True
bg = world.node_tree.nodes.get("Background")
if bg:
    bg.inputs[0].default_value = (0.03, 0.028, 0.025, 1)
    bg.inputs[1].default_value = 0.6
print("Smart Lab digital twin built - press Space to play.")

# ---------------------------------------------------------------------------
# Live digital twin (optional)
# ---------------------------------------------------------------------------
if LIVE_MQTT:
    import json, queue
    try:
        import paho.mqtt.client as paho
    except ImportError:
        raise SystemExit("Install paho-mqtt into Blender's Python first (see docstring)")
    bpy.app.handlers.frame_change_pre.remove(smartlab_update_texts)
    for o in list(bpy.data.objects):
        if o.name.startswith(("Caption", "Student", "Phone")):
            o.animation_data_clear(); o.hide_viewport = o.hide_render = True
    rotor.animation_data_clear()
    for m in (M["ledG"], M["ledY"], M["ledR"]):
        m.node_tree.animation_data_clear()
    hm.node_tree.animation_data_clear()
    inbox = queue.Queue()
    st_live = {"fan": False, "blink": False, "early": False}

    def on_msg(_c, _u, msg):
        try:
            inbox.put(json.loads(msg.payload.decode()))
        except ValueError:
            pass
    try:
        cli = paho.Client(paho.CallbackAPIVersion.VERSION2)
    except AttributeError:
        cli = paho.Client()
    cli.on_message = on_msg
    cli.connect(MQTT_HOST, 1883, 30)
    cli.subscribe(f"smartlab/{DEVICE_ID}/data")
    cli.loop_start()

    def apply(d):
        if d.get("offline"):
            return
        st = d.get("status", "SAFE"); early = bool(d.get("early"))
        emission(M["ledG"]).default_value = 25 if st == "SAFE" and not early else 0
        emission(M["ledR"]).default_value = 25 if st == "CRITICAL" else 0
        st_live.update(fan=bool(d.get("fan")), early=early, status=st)
        dens.default_value = max(0.0, (float(d.get("aq", 400)) - 550) / 1000) * 0.06
        on = float(d.get("lux", 0)) > 150
        emission(M["lamp"]).default_value = 12 if on else 0.2
        o, dsh = frame_texts(float(d.get("temp", 0)), float(d.get("hum", 0)), float(d.get("aq", 0)), bool(d.get("occ")),
                             float(d.get("lux", 0)), st, d.get("reason", ""), float(d.get("pCrit", 0)), early,
                             st_live["fan"], "LIVE")
        oled_text.data.body = o; dash_text.data.body = dsh

    def tick():
        while not inbox.empty():
            apply(inbox.get())
        if st_live["fan"]:
            rotor.rotation_euler.x += math.radians(40)
        st_live["blink"] = not st_live["blink"]
        warn = st_live.get("status") == "WARNING" or (st_live["early"] and st_live["blink"])
        emission(M["ledY"]).default_value = 25 if warn else 0
        return 0.1
    bpy.app.timers.register(tick)
    print(f"Live digital twin: smartlab/{DEVICE_ID}/data")
