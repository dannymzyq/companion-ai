"""Convierte animaciones grabadas (glTF/GLB de esqueleto humanoide) al esqueleto normalizado de VRM 1.0 y las guarda
en web/anim/clips.json, que avatar.js mezcla con su animación por código (17 nov 2026).

Fuentes incluidas: Universal Animation Library 1 y 2 de Quaternius (CC0, dominio público) y estilos de andar y de
estar de pie de 100STYLE (Ian Mason, CC BY 4.0); ver web/anim/CREDITOS.md.
Uso (los .zip «Standard» de OpenGameArt y 100STYLE.zip de Zenodo, ya descomprimidos):
    .venv\\Scripts\\python.exe scripts\\convertir_animaciones.py <AnimationLibrary_Godot_Standard.glb> <UAL2_Standard.glb>
        --estilos <carpeta 100STYLE>
Los BVH de 100STYLE los lee scripts/anim_bvh.py.

Cómo se adapta: para cada hueso se calcula su giro en el mundo respecto a la pose en T de referencia (la animación
«A_TPose» del propio paquete) y se pasa a giro local respecto a su padre humanoide. Ese es justo el espacio de los
huesos normalizados de three-vrm (en T todos los giros son cero), así que vale para cualquier VRM, sean cuales sean
sus proporciones. Se guarda en ángulos de Euler XYZ (los de avatar.js), sin saltos de ±π entre cuadros.
"""
import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "anim" / "clips.json"
FPS = 30

# ---------------------------------------------------------------- nombres de huesos de cada esqueleto
def _rigify():
    m = {"hips": "DEF-hips", "spine": "DEF-spine.001", "chest": "DEF-spine.002", "upperChest": "DEF-spine.003",
         "neck": "DEF-neck", "head": "DEF-head"}
    for side, s in (("left", "L"), ("right", "R")):
        m.update({side + "Shoulder": f"DEF-shoulder.{s}", side + "UpperArm": f"DEF-upper_arm.{s}",
                  side + "LowerArm": f"DEF-forearm.{s}", side + "Hand": f"DEF-hand.{s}",
                  side + "UpperLeg": f"DEF-thigh.{s}", side + "LowerLeg": f"DEF-shin.{s}",
                  side + "Foot": f"DEF-foot.{s}", side + "Toes": f"DEF-toe.{s}"})
        for f, src in (("Index", "f_index"), ("Middle", "f_middle"), ("Ring", "f_ring"), ("Little", "f_pinky")):
            for i, seg in enumerate(("Proximal", "Intermediate", "Distal")):
                m[side + f + seg] = f"DEF-{src}.0{i + 1}.{s}"
        for i, seg in enumerate(("Metacarpal", "Proximal", "Distal")):
            m[side + "Thumb" + seg] = f"DEF-thumb.0{i + 1}.{s}"
    return m


def _unreal():
    m = {"hips": "pelvis", "spine": "spine_01", "chest": "spine_02", "upperChest": "spine_03", "neck": "neck_01",
         "head": "Head"}
    for side, s in (("left", "l"), ("right", "r")):
        m.update({side + "Shoulder": f"clavicle_{s}", side + "UpperArm": f"upperarm_{s}",
                  side + "LowerArm": f"lowerarm_{s}", side + "Hand": f"hand_{s}", side + "UpperLeg": f"thigh_{s}",
                  side + "LowerLeg": f"calf_{s}", side + "Foot": f"foot_{s}", side + "Toes": f"ball_{s}"})
        for f, src in (("Index", "index"), ("Middle", "middle"), ("Ring", "ring"), ("Little", "pinky")):
            for i, seg in enumerate(("Proximal", "Intermediate", "Distal")):
                m[side + f + seg] = f"{src}_0{i + 1}_{s}"
        for i, seg in enumerate(("Metacarpal", "Proximal", "Distal")):
            m[side + "Thumb" + seg] = f"thumb_0{i + 1}_{s}"
    return m


RIGS = {"DEF-hips": _rigify(), "pelvis": _unreal()}

# Padre humanoide de cada hueso (el de VRM, aunque en el esqueleto de origen haya nodos intermedios).
PARENT = {"spine": "hips", "chest": "spine", "upperChest": "chest", "neck": "upperChest", "head": "neck"}
for _s in ("left", "right"):
    PARENT.update({_s + "Shoulder": "upperChest", _s + "UpperArm": _s + "Shoulder", _s + "LowerArm": _s + "UpperArm",
                   _s + "Hand": _s + "LowerArm", _s + "UpperLeg": "hips", _s + "LowerLeg": _s + "UpperLeg",
                   _s + "Foot": _s + "LowerLeg", _s + "Toes": _s + "Foot"})
    for _f in ("Index", "Middle", "Ring", "Little", "Thumb"):
        segs = ("Metacarpal", "Proximal", "Distal") if _f == "Thumb" else ("Proximal", "Intermediate", "Distal")
        prev = _s + "Hand"
        for _seg in segs:
            PARENT[_s + _f + _seg] = prev
            prev = _s + _f + _seg

# Qué se queda de cada paquete: nombre en clips.json ← (animación, ¿en bucle?).
WANTED = {
    "idle": ("Idle_Loop", True),
    "talk": ("Idle_Talking_Loop", True),
    "walk": ("Walk_Loop", True),
    "walk_formal": ("Walk_Formal_Loop", True),
    "sit": ("Sitting_Idle_Loop", True),
    "sit_talk": ("Sitting_Talking_Loop", True),
    "crouch": ("Crouch_Idle_Loop", True),
    "kneel_work": ("Fixing_Kneeling", True),
    "interact": ("Interact", False),
    "jump_start": ("Jump_Start", False),
    "jump_loop": ("Jump_Loop", True),
    "jump_land": ("Jump_Land", False),
    "hit_head": ("Hit_Head", False),
    "hit_chest": ("Hit_Chest", False),
    "dance": ("Dance_Loop", True),
    "fold_arms": ("Idle_FoldArms_Loop", True),
    "no": ("Idle_No_Loop", True),
    "yes": ("Yes", False),
    "phone": ("Idle_TalkingPhone_Loop", True),
    "consume": ("Consume", False),
    "spell": ("Spell_Simple_Shoot", False),          # pasatiempos (17 nov 2026): un hechizo de juguete
    "lay_up": ("LayToIdle", False),                 # siesta: al revés se tumba, hacia delante se levanta
}


# ---------------------------------------------------------------- glTF
def read_glb(path):
    b = Path(path).read_bytes()
    jlen = struct.unpack_from("<I", b, 12)[0]
    j = json.loads(b[20:20 + jlen])
    off = 20 + jlen
    blen = struct.unpack_from("<I", b, off)[0]
    return j, b[off + 8:off + 8 + blen]


def accessor(j, buf, i):
    a = j["accessors"][i]
    v = j["bufferViews"][a["bufferView"]]
    n = {"SCALAR": 1, "VEC3": 3, "VEC4": 4}[a["type"]]
    assert a["componentType"] == 5126, "solo float"
    start = v.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = v.get("byteStride", 4 * n)
    raw = np.frombuffer(buf, dtype=np.uint8, count=stride * (a["count"] - 1) + 4 * n, offset=start)
    out = np.empty((a["count"], n), dtype=np.float32)
    for k in range(a["count"]):
        out[k] = np.frombuffer(raw[k * stride:k * stride + 4 * n].tobytes(), dtype=np.float32)
    return out


# ---------------------------------------------------------------- cuaterniones (x, y, z, w)
def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz])


def qinv(q):
    return np.array([-q[0], -q[1], -q[2], q[3]]) / np.dot(q, q)


def qrot(q, v):
    return qmul(qmul(q, np.array([v[0], v[1], v[2], 0.0])), qinv(q))[:3]


def slerp(a, b, t):
    d = np.dot(a, b)
    if d < 0:
        b, d = -b, -d
    if d > 0.9995:
        r = a + (b - a) * t
        return r / np.linalg.norm(r)
    th = math.acos(d)
    return (math.sin((1 - t) * th) * a + math.sin(t * th) * b) / math.sin(th)


def euler_xyz(q):
    """Igual que THREE.Euler.setFromQuaternion(q, 'XYZ')."""
    x, y, z, w = q
    m11 = 1 - 2 * (y * y + z * z); m12 = 2 * (x * y - z * w); m13 = 2 * (x * z + y * w)
    m22 = 1 - 2 * (x * x + z * z); m23 = 2 * (y * z - x * w); m32 = 2 * (y * z + x * w); m33 = 1 - 2 * (x * x + y * y)
    ey = math.asin(max(-1.0, min(1.0, m13)))
    if abs(m13) < 0.9999999:
        return [math.atan2(-m23, m33), ey, math.atan2(-m12, m11)]
    return [math.atan2(m32, m22), ey, 0.0]


class Rig:
    def __init__(self, j, buf):
        self.j, self.buf = j, buf
        self.nodes = j["nodes"]
        self.parent = {}
        for i, nd in enumerate(self.nodes):
            for c in nd.get("children", []):
                self.parent[c] = i
        self.index = {nd.get("name"): i for i, nd in enumerate(self.nodes)}
        self.map = next(m for k, m in RIGS.items() if k in self.index)
        self.anims = {a["name"]: a for a in j["animations"]}

    def channels(self, anim):
        out = {}
        for c in anim["channels"]:
            s = anim["samplers"][c["sampler"]]
            t = accessor(self.j, self.buf, s["input"])[:, 0]
            v = accessor(self.j, self.buf, s["output"])
            if s.get("interpolation") == "CUBICSPLINE":
                v = v[1::3]
            out[(c["target"]["node"], c["target"]["path"])] = (t, v, s.get("interpolation", "LINEAR"))
        return out

    @staticmethod
    def sample(ch, time, rot):
        t, v, mode = ch
        if time <= t[0]:
            return v[0].astype(float)
        if time >= t[-1]:
            return v[-1].astype(float)
        k = int(np.searchsorted(t, time) - 1)
        if mode == "STEP":
            return v[k].astype(float)
        f = (time - t[k]) / max(1e-9, t[k + 1] - t[k])
        a, b = v[k].astype(float), v[k + 1].astype(float)
        return slerp(a, b, f) if rot else a + (b - a) * f

    def world(self, chans, time):
        """Giro y posición en el mundo de cada nodo en ese instante."""
        rot, pos = {}, {}

        def get(i):
            if i in rot:
                return
            nd = self.nodes[i]
            q = np.array(nd.get("rotation", [0, 0, 0, 1]), dtype=float)
            p = np.array(nd.get("translation", [0, 0, 0]), dtype=float)
            if (i, "rotation") in chans:
                q = self.sample(chans[(i, "rotation")], time, True)
            if (i, "translation") in chans:
                p = self.sample(chans[(i, "translation")], time, False)
            q = q / np.linalg.norm(q)
            par = self.parent.get(i)
            if par is None:
                rot[i], pos[i] = q, p
            else:
                get(par)
                rot[i] = qmul(rot[par], q)
                pos[i] = pos[par] + qrot(rot[par], p)

        for i in range(len(self.nodes)):
            get(i)
        return rot, pos


def convert(rig, ref_rot, ref_pos, hips_h, name, loop):
    anim = rig.anims[name]
    chans = rig.channels(anim)
    dur = max(float(c[0][-1]) for c in chans.values())
    frames = max(2, int(round(dur * FPS)) + (0 if loop else 1))
    bones = [b for b in rig.map if rig.map[b] in rig.index]
    tracks = {b: [] for b in bones}
    hips = []
    feet = {"left": [], "right": []}
    for k in range(frames):
        time = min(dur, k / FPS)
        rot, pos = rig.world(chans, time)
        delta = {}
        for b in bones:
            i = rig.index[rig.map[b]]
            delta[b] = qmul(rot[i], qinv(ref_rot[i]))
        for b in bones:
            par = PARENT.get(b)
            while par and par not in delta:
                par = PARENT.get(par)
            local = qmul(qinv(delta[par]), delta[b]) if par else delta[b]
            e = euler_xyz(local)
            prev = tracks[b][-1] if tracks[b] else None
            if prev:                                              # sin saltos de ±π de un cuadro a otro
                e = [v + 2 * math.pi * round((p - v) / (2 * math.pi)) for v, p in zip(e, prev)]
            tracks[b].append(e)
        hi = rig.index[rig.map["hips"]]
        hips.append(((pos[hi] - ref_pos[hi]) / hips_h).tolist())
        for side in feet:
            fi = rig.index[rig.map[side + "Foot"]]
            feet[side].append(pos[fi][2] / hips_h)
    hips = np.array(hips)
    if loop:                                                      # en bucle: sin avance (lo pone la ventana)
        hips[:, 0] -= hips[:, 0].mean()
        hips[:, 2] -= hips[:, 2].mean()
    # Largo del paso (respecto a la altura de la cadera): lo que se separan los pies de delante atrás.
    stride = float(np.max(np.abs(np.array(feet["left"]) - np.array(feet["right"]))))
    # Se quitan las pistas que no se mueven y son cero (menos datos que bajar).
    out = {}
    for b, tr in tracks.items():
        a = np.array(tr)
        if np.abs(a).max() < 1e-3:
            continue
        if np.ptp(a, axis=0).max() < 1e-3:
            out[b] = [round(float(x), 4) for x in a[0]]
        else:
            out[b] = [round(float(x), 4) for x in a.reshape(-1)]
    return {"frames": frames, "fps": FPS, "loop": loop, "dur": round(frames / FPS if loop else dur, 4),
            "stride": round(stride, 3), "bones": out,
            "hips": [round(float(x), 4) for x in hips.reshape(-1)]}


# Estilos de 100STYLE (Ian Mason, CC BY 4.0): nombre en clips.json ← carpeta del estilo. De cada uno, su andar
# (walk_<estilo>, de <Estilo>_FW.bvh) y su estar de pie (idle_<estilo>, de <Estilo>_ID.bvh). avatar.js los elige
# según la emoción y la personalidad (EMO_STYLE).
STYLES = {
    "neutro": "Neutral",
    "alegre": "Elated",
    "triste": "Depressed",
    "enfado": "Angry",
    "timido": "PigeonToed",
    "orgullo": "Proud",
    "pensar": "ArmsBehindBack",
    "ligero": "FairySteps",
    "nervioso": "Tiptoe",
}


def styles(folder, clips):
    import anim_bvh
    folder = Path(folder)
    for key, name in STYLES.items():
        d = folder / name
        for kind, suffix, fn in (("walk", "FW", anim_bvh.walk_clip), ("idle", "ID", anim_bvh.idle_clip)):
            f = d / f"{name}_{suffix}.bvh"
            if not f.exists():
                print(f"Falta {f}")
                continue
            c = fn(f, PARENT)
            c["source"] = f"100STYLE {name}_{suffix}"
            clips[f"{kind}_{key}"] = c
            extra = f"  {c['cycles'] / c['dur']:.2f} Hz  {c.get('speed', 0)} cad/s" if kind == "walk" else ""
            print(f"{kind}_{key:9s} <- {name}_{suffix:3s} {c['dur']:5.2f} s  paso {c['stride']}{extra}")


def main(args):
    clips = {}
    paths = []
    folder = None
    while args:
        a = args.pop(0)
        if a == "--estilos":
            folder = args.pop(0)
        else:
            paths.append(a)
    for path in paths:
        rig = Rig(*read_glb(path))
        tpose = rig.channels(rig.anims["A_TPose"])
        ref_rot, ref_pos = rig.world(tpose, 0.0)
        hi = rig.index[rig.map["hips"]]
        lf = rig.index[rig.map["leftFoot"]]
        hips_h = float(ref_pos[hi][1] - ref_pos[lf][1]) * 1.08     # cadera sobre el suelo (el tobillo, algo alto)
        # Comprobaciones: de frente a +Z, su izquierda en +X y los brazos en horizontal en la pose de referencia.
        la, lh = rig.index[rig.map["leftUpperArm"]], rig.index[rig.map["leftHand"]]
        arm = ref_pos[lh] - ref_pos[la]
        assert arm[0] > 0 and abs(arm[1]) < 0.15 * np.linalg.norm(arm), f"{path}: la referencia no es una pose en T"
        for key, (name, loop) in WANTED.items():
            if name in rig.anims and key not in clips:
                clips[key] = convert(rig, ref_rot, ref_pos, hips_h, name, loop)
                clips[key]["source"] = name
                print(f"{key:12s} <- {name:24s} {clips[key]['dur']:5.2f} s  paso {clips[key]['stride']}")
    if folder:
        styles(folder, clips)
    missing = set(WANTED) - set(clips)
    if missing:
        print("No encontradas:", ", ".join(sorted(missing)))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    lic = "CC0 1.0 (Quaternius, Universal Animation Library 1 y 2)"
    if folder:
        lic += "; walk_*/idle_*: CC BY 4.0, The 100STYLE Dataset - Ian Mason"
    OUT.write_text(json.dumps({"version": 1, "license": lic,
                               "clips": clips}, separators=(",", ":")), encoding="utf-8")
    print(f"{OUT.relative_to(ROOT)}: {OUT.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main(sys.argv[1:])
