"""Animaciones BVH (100STYLE, captura XSens) al esqueleto normalizado de VRM 1.0 (17 nov 2026).

Lo usa scripts/convertir_animaciones.py con --estilos. Cada estilo de 100STYLE trae, sin editar, una toma larga de
andar hacia delante (<Estilo>_FW.bvh) y otra de estar de pie (<Estilo>_ID.bvh). De cada una se saca un bucle limpio:
- Andar: se buscan los ciclos de marcha (cuando el pie izquierdo va más adelantado) en un tramo recto y a ritmo
  constante, y se eligen dos ciclos seguidos cuyo final enlace mejor con el principio. Se quita el avance y el giro
  del recorrido (lo pone la ventana), pero no el vaivén de la cadera.
- De pie: el trozo de 4 a 7 s cuyo final se parece más al principio.
En los dos casos lo que aún no enlaza se reparte poco a poco a lo largo del clip, para que el bucle no dé un salto.

El espacio de salida es el mismo que el de los glTF: giro de cada hueso respecto a la pose en T, en local respecto a su
padre humanoide, en ángulos de Euler XYZ (los de three.js). Si la pose de reposo del BVH no es una T (brazos abajo),
se corrige con el giro que lleva cada hueso de su dirección de reposo a la de la T.
"""
import math
from pathlib import Path

import numpy as np

FPS = 30
# En las tomas de XSens el cuello va unos 18° hacia delante de media (la persona mira al suelo al andar por la sala):
# con el cuerpo de un personaje de anime parece que va cabizbajo. Se le quitan 15° (las tristes siguen mirando abajo).
NECK_FIX = math.radians(15)

# ---------------------------------------------------------------- cuaterniones en lote (x, y, z, w), forma (..., 4)
def qmul(a, b):
    ax, ay, az, aw = np.moveaxis(a, -1, 0)
    bx, by, bz, bw = np.moveaxis(b, -1, 0)
    return np.stack([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz], -1)


def qinv(q):
    return q * np.array([-1, -1, -1, 1.0])


def qrot(q, v):
    v4 = np.concatenate([v, np.zeros(v.shape[:-1] + (1,))], -1)
    return qmul(qmul(q, v4), qinv(q))[..., :3]


def qaxis(axis, ang):
    """Giro de `ang` (radianes, array) alrededor de un eje fijo."""
    ang = np.asarray(ang, dtype=float)
    s = np.sin(ang / 2)[..., None]
    return np.concatenate([np.asarray(axis, dtype=float) * s, np.cos(ang / 2)[..., None]], -1)


def qbetween(a, b):
    """El giro más corto que lleva la dirección a a la b."""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    c = np.cross(a, b)
    d = float(np.dot(a, b))
    if d < -0.9999:
        ax = np.cross(a, [1, 0, 0]) if abs(a[0]) < 0.9 else np.cross(a, [0, 1, 0])
        return qaxis(ax / np.linalg.norm(ax), math.pi)
    q = np.array([c[0], c[1], c[2], 1 + d])
    return q / np.linalg.norm(q)


def euler_xyz(q):
    """Como THREE.Euler.setFromQuaternion(q, 'XYZ'), en lote."""
    x, y, z, w = np.moveaxis(q, -1, 0)
    m11 = 1 - 2 * (y * y + z * z); m12 = 2 * (x * y - z * w); m13 = 2 * (x * z + y * w)
    m22 = 1 - 2 * (x * x + z * z); m23 = 2 * (y * z - x * w); m32 = 2 * (y * z + x * w); m33 = 1 - 2 * (x * x + y * y)
    ey = np.arcsin(np.clip(m13, -1, 1))
    lock = np.abs(m13) >= 0.9999999
    ex = np.where(lock, np.arctan2(m32, m22), np.arctan2(-m23, m33))
    ez = np.where(lock, 0.0, np.arctan2(-m12, m11))
    return np.stack([ex, ey, ez], -1)


# ---------------------------------------------------------------- BVH
class BVH:
    def __init__(self, path):
        toks = Path(path).read_text(encoding="latin-1").split()
        self.names, self.parent, self.offset, self.chans, self.end = [], [], [], [], {}
        i, stack, last = 0, [], None
        while toks[i] != "MOTION":
            t = toks[i]
            if t in ("ROOT", "JOINT"):
                self.names.append(toks[i + 1])
                self.parent.append(stack[-1] if stack else -1)
                last = len(self.names) - 1
                i += 2
            elif t == "End":
                last = ("end", stack[-1])
                i += 2
            elif t == "{":
                stack.append(last)
                i += 1
            elif t == "}":
                stack.pop()
                i += 1
            elif t == "OFFSET":
                off = [float(x) for x in toks[i + 1:i + 4]]
                if isinstance(last, tuple):
                    self.end[last[1]] = np.array(off)
                else:
                    self.offset.append(np.array(off))
                i += 4
            elif t == "CHANNELS":
                n = int(toks[i + 1])
                self.chans.append(toks[i + 2:i + 2 + n])
                i += 2 + n
            else:
                i += 1
        n_frames = int(toks[i + 2])
        self.dt = float(toks[i + 5])
        data = np.array(toks[i + 6:i + 6 + n_frames * sum(len(c) for c in self.chans)], dtype=float)
        self.data = data.reshape(n_frames, -1)
        self.index = {n: k for k, n in enumerate(self.names)}
        self.offset = np.array(self.offset)

    def world(self, step=1):
        """Giro (F, J, 4) y posición (F, J, 3) en el mundo de cada articulación, un cuadro de cada `step`."""
        d = self.data[::step]
        F, J = len(d), len(self.names)
        rot = np.zeros((F, J, 4))
        pos = np.zeros((F, J, 3))
        col = 0
        axes = {"X": [1, 0, 0], "Y": [0, 1, 0], "Z": [0, 0, 1]}
        for j in range(J):
            q = np.tile([0, 0, 0, 1.0], (F, 1))
            p = np.tile(self.offset[j], (F, 1))
            for c in self.chans[j]:
                v = d[:, col]
                col += 1
                if c.endswith("rotation"):
                    q = qmul(q, qaxis(axes[c[0]], np.radians(v)))
                else:
                    p[:, "XYZ".index(c[0])] = v
            par = self.parent[j]
            if par < 0:
                rot[:, j], pos[:, j] = q, p
            else:
                rot[:, j] = qmul(rot[:, par], q)
                pos[:, j] = pos[:, par] + qrot(rot[:, par], p)
        return rot, pos

    def rest(self):
        """Posiciones en la pose de reposo (todos los giros a cero)."""
        pos = np.zeros((len(self.names), 3))
        for j, par in enumerate(self.parent):
            pos[j] = self.offset[j] + (pos[par] if par >= 0 else 0)
        return pos


# Nombres de XSens (los de 100STYLE) → huesos de VRM. Entre «spine» y «upperChest» hay más vértebras en la captura: el
# método (giros en el mundo) las reparte solo.
XSENS = {"hips": "Hips", "spine": "Chest", "chest": "Chest2", "upperChest": "Chest4", "neck": "Neck", "head": "Head"}
for _s, _S in (("left", "Left"), ("right", "Right")):
    XSENS.update({_s + "Shoulder": _S + "Collar", _s + "UpperArm": _S + "Shoulder", _s + "LowerArm": _S + "Elbow",
                  _s + "Hand": _S + "Wrist", _s + "UpperLeg": _S + "Hip", _s + "LowerLeg": _S + "Knee",
                  _s + "Foot": _S + "Ankle", _s + "Toes": _S + "Toe"})


def _child(b, bones):
    """El hueso hijo que marca la dirección de `b` en la pose en T."""
    seq = {"hips": "spine", "spine": "chest", "chest": "upperChest", "upperChest": "neck", "neck": "head"}
    for s in ("left", "right"):
        seq.update({s + "Shoulder": s + "UpperArm", s + "UpperArm": s + "LowerArm", s + "LowerArm": s + "Hand",
                    s + "UpperLeg": s + "LowerLeg", s + "LowerLeg": s + "Foot"})
    c = seq.get(b)
    return c if c in bones else None


def _tdir(b):
    if "Arm" in b or "Shoulder" in b or b.endswith("Hand"):
        return np.array([1.0 if b.startswith("left") else -1.0, 0, 0])
    if "Leg" in b:
        return np.array([0, -1.0, 0])
    if b in ("spine", "chest", "upperChest", "neck", "head", "hips"):
        return np.array([0, 1.0, 0])
    return None


class Source:
    """Una toma BVH ya en el espacio de VRM: de frente a +Z, su izquierda en +X, con su pose en T de referencia."""

    def __init__(self, path, parent_map):
        bvh = BVH(path)
        step = max(1, int(round(1 / (bvh.dt * 60))))          # trabajamos a 60 cuadros por segundo
        self.fps = 1 / (bvh.dt * step)
        self.map = {b: bvh.index[n] for b, n in XSENS.items() if n in bvh.index}
        rot, pos = bvh.world(step)
        rest = bvh.rest()
        # Ejes: arriba = +Y (BVH); si su izquierda queda en -X, mira a -Z: se gira media vuelta.
        lx = rest[self.map["leftUpperLeg"]][0] - rest[self.map["rightUpperLeg"]][0]
        g = qaxis([0, 1, 0], 0.0 if lx > 0 else math.pi)
        rot = qmul(np.broadcast_to(g, rot.shape), rot)
        pos = qrot(np.broadcast_to(g, rot.shape), pos)
        rest = qrot(np.broadcast_to(g, rest.shape[:-1] + (4,)), rest)
        # Referencia: el giro en el mundo que tendría cada hueso en la pose en T (si el reposo no lo es, se corrige).
        self.ref = {}
        for b, j in self.map.items():
            c = _child(b, self.map)
            want = _tdir(b)
            q = g.copy()
            if c is not None and want is not None and b != "hips":
                cur = rest[self.map[c]] - rest[j]
                if np.linalg.norm(cur) > 1e-6:
                    ang = math.acos(np.clip(np.dot(cur / np.linalg.norm(cur), want), -1, 1))
                    if ang > math.radians(8):
                        q = qmul(qbetween(cur, want), g)
            self.ref[b] = q
        self.parent_map = parent_map
        self.rot, self.pos = rot, pos
        self.F = len(rot)
        hi, la = self.map["hips"], self.map["leftFoot"]
        self.hip_above_ankle = float(rest[hi][1] - rest[la][1])
        self.hips_h = self.hip_above_ankle * 1.08
        # Locales (salvo la cadera, que depende del rumbo que se quite): no cambian con el giro del recorrido.
        self.delta = {b: qmul(self.rot[:, j], qinv(np.broadcast_to(self.ref[b], (self.F, 4)))) for b, j in self.map.items()}
        self.local = {}
        for b in self.map:
            if b == "hips":
                continue
            par = parent_map.get(b)
            while par and par not in self.delta:
                par = parent_map.get(par)
            self.local[b] = qmul(qinv(self.delta[par]), self.delta[b])

    def heading(self):
        """Rumbo (yaw) de la cadera en cada cuadro, sin saltos."""
        f = qrot(self.delta["hips"], np.tile([0, 0, 1.0], (self.F, 1)))
        return np.unwrap(np.arctan2(f[:, 0], f[:, 2]))

    def joint(self, b):
        return self.pos[:, self.map[b]]

    def mismatch(self, i, k):
        """Lo que se diferencian dos cuadros (giros de los huesos, sin la cadera)."""
        s = 0.0
        for q in self.local.values():
            d = abs(float(np.dot(q[i], q[k])))
            s += 2 * math.acos(min(1.0, d))
        return s

    def clip(self, a, b, cycles, yaw, travel):
        """El trozo [a, b) como clip en bucle: yaw(t) y travel(t) son el rumbo y el avance que se quitan."""
        idx = np.arange(a, b + 1)
        n = len(idx)
        yq = qaxis([0, 1, 0], -yaw)                                       # (n, 4)
        hips_d = qmul(yq, self.delta["hips"][idx])
        tracks = {"hips": hips_d}
        for k, q in self.local.items():
            tracks[k] = q[idx]
        # Euler, sin saltos de ±π, y luego el desajuste final repartido para cerrar el bucle.
        out = {}
        ramp = np.linspace(0, 1, n)[:, None]
        for k, q in tracks.items():
            e = euler_xyz(q)
            e = np.unwrap(e, axis=0)
            e = e - ramp * (e[-1] - e[0])
            if k == "neck":
                e[:, 0] -= NECK_FIX
            out[k] = e
        hp = self.joint("hips")[idx] - travel
        hp = qrot(yq, hp)
        floor = float(np.percentile(np.minimum(self.joint("leftFoot")[idx, 1], self.joint("rightFoot")[idx, 1]), 5))
        hips = np.stack([hp[:, 0], hp[:, 1] - floor - self.hip_above_ankle, hp[:, 2]], -1) / self.hips_h
        hips[:, 0] -= hips[:, 0].mean()
        hips[:, 2] -= hips[:, 2].mean()
        hips = hips - ramp * (hips[-1] - hips[0])
        # Paso: lo que se separan los pies de delante atrás (en el rumbo del recorrido).
        lf = qrot(yq, self.joint("leftFoot")[idx] - self.joint("rightFoot")[idx])
        stride = float(np.max(np.abs(lf[:, 2]))) / self.hips_h
        # A 30 cuadros por segundo; el último (igual que el primero) no se guarda.
        dur = (n - 1) / self.fps
        frames = max(2, int(round(dur * FPS)))
        src_t = np.arange(n) / self.fps
        dst_t = np.arange(frames) * (dur / frames)

        def res(arr):
            return np.stack([np.interp(dst_t, src_t, arr[:, c]) for c in range(arr.shape[1])], -1)

        bones = {}
        for k, e in out.items():
            r = res(e)
            if np.abs(r).max() < 1e-3:
                continue
            if np.ptp(r, axis=0).max() < 1e-3:
                bones[k] = [round(float(x), 3) for x in r[0]]
            else:
                bones[k] = [round(float(x), 3) for x in r.reshape(-1)]
        return {"frames": frames, "fps": FPS, "loop": True, "dur": round(dur, 4), "cycles": cycles,
                "stride": round(stride, 3), "bones": bones,
                "hips": [round(float(x), 4) for x in res(hips).reshape(-1)]}


def _smooth(x, n):
    n = max(1, int(n))
    k = np.ones(n) / n
    pad = np.pad(x, (n // 2, n - 1 - n // 2), mode="edge")
    return np.convolve(pad, k, mode="valid")


def walk_clip(path, parent_map, cycles=2):
    src = Source(path, parent_map)
    fps, F = src.fps, src.F
    yaw = src.heading()
    ys = _smooth(yaw, fps * 1.2)
    hip = src.joint("hips")
    vel = np.gradient(hip, axis=0) * fps
    speed = _smooth(np.hypot(vel[:, 0], vel[:, 2]), fps * 0.6) / src.hips_h
    turn = np.abs(np.gradient(ys) * fps)
    fwd = np.stack([np.sin(ys), np.zeros(F), np.cos(ys)], -1)
    sep = np.sum((src.joint("leftFoot") - src.joint("rightFoot")) * fwd, -1)
    # Ciclos: el pie izquierdo en su punto más adelantado.
    sm = _smooth(sep, fps * 0.08)
    peaks = [i for i in range(2, F - 2) if sm[i] > 0 and sm[i] == max(sm[i - 2:i + 3]) and sm[i] > 0.25 * src.hips_h]
    best = None
    typ = np.median(speed)
    for i in range(len(peaks) - cycles):
        a, b = peaks[i], peaks[i + cycles]
        span = (b - a) / fps
        if not (0.6 * cycles < span < 2.2 * cycles):
            continue
        seg = slice(a, b + 1)
        # Casi recto (las tomas van en curvas por la sala: un giro suave y constante se quita con el rumbo).
        tr = np.gradient(ys[seg]) * fps
        if np.ptp(tr) > 0.6 or abs(tr.mean()) > 0.8 or speed[seg].min() < 0.5 * typ or speed[seg].min() < 0.2:
            continue
        lens = np.diff(peaks[i:i + cycles + 1])
        score = src.mismatch(a, b) + 2.0 * float(np.ptp(lens)) / fps + 1.5 * abs(float(tr.mean())) + float(np.ptp(tr))
        if best is None or score < best[0]:
            best = (score, a, b)
    if best is None:
        if cycles > 1:                                    # tomas con mucha curva: basta un ciclo
            return walk_clip(path, parent_map, cycles - 1)
        raise RuntimeError(f"{path}: no hay un tramo recto con un ciclo de marcha")
    _, a, b = best
    idx = np.arange(a, b + 1)
    t = (idx - a) / fps
    # Rumbo y avance del recorrido: una recta ajustada al tramo (el vaivén de la cadera se queda).
    yfit = np.polyval(np.polyfit(t, yaw[idx], 1), t)
    travel = np.stack([np.polyval(np.polyfit(t, hip[idx, c], 1), t) for c in range(3)], -1)
    travel[:, 1] = 0
    clip = src.clip(a, b, cycles, yfit, travel)
    clip["speed"] = round(float(np.median(speed[a:b + 1])), 3)          # alturas de cadera por segundo
    return clip


def idle_clip(path, parent_map, lo=4.0, hi=7.0):
    src = Source(path, parent_map)
    fps, F = src.fps, src.F
    start = int(1.5 * fps)
    hip = src.joint("hips")
    yaw = src.heading()
    best = None
    stepf = max(1, int(0.1 * fps))
    for a in range(start, F - int(lo * fps) - 1, stepf):
        for b in range(a + int(lo * fps), min(F - 1, a + int(hi * fps)), stepf):
            # Que no ande: la cadera se queda en su sitio.
            if np.ptp(hip[a:b, 0]) > 0.25 * src.hips_h or np.ptp(hip[a:b, 2]) > 0.25 * src.hips_h:
                continue
            score = src.mismatch(a, b) + 6 * float(np.linalg.norm(hip[a] - hip[b])) / src.hips_h
            if best is None or score < best[0]:
                best = (score, a, b)
    if best is None:
        raise RuntimeError(f"{path}: no hay un trozo quieto de {lo} s")
    _, a, b = best
    idx = np.arange(a, b + 1)
    mean_yaw = math.atan2(float(np.mean(np.sin(yaw[idx]))), float(np.mean(np.cos(yaw[idx]))))
    yawc = np.full(len(idx), mean_yaw)
    travel = np.zeros((len(idx), 3))
    travel[:, 0] = hip[idx, 0].mean()
    travel[:, 2] = hip[idx, 2].mean()
    return src.clip(a, b, 1, yawc, travel)
