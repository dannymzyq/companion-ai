// Animaciones grabadas (17 nov 2026): web/anim/clips.json, hechas con scripts/convertir_animaciones.py a partir de la
// Universal Animation Library de Quaternius (CC0). Están en el esqueleto normalizado de VRM 1.0 (giros respecto a la
// pose en T, en ángulos de Euler XYZ, los mismos que usa avatar.js), así que sirven para cualquier VRM: los
// incluidos y los que cargue el usuario.
//
// avatar.js no las reproduce «a pelo»: las usa de base (el cuerpo de verdad: peso, cadera, piernas, brazos que
// acompañan) y encima sigue poniendo lo suyo (respiración, mirada, gestos al hablar, emociones, toques). Cada capa
// tiene su peso y su máscara por zonas del cuerpo, y entra y sale fundiéndose.

const lerp = (a, b, t) => a + (b - a) * t;

// Zonas del cuerpo, para las máscaras de las capas.
export const ZONES = {
  legs: ['leftUpperLeg', 'leftLowerLeg', 'leftFoot', 'leftToes', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot', 'rightToes'],
  hips: ['hips'],
  spine: ['spine', 'chest', 'upperChest'],
  head: ['neck', 'head'],
  arms: ['leftShoulder', 'leftUpperArm', 'leftLowerArm', 'leftHand', 'rightShoulder', 'rightUpperArm', 'rightLowerArm', 'rightHand'],
};
const BODY = Object.values(ZONES).flat();
const _tmp = [0, 0, 0];

export class ClipLib {
  constructor(data) {
    this.clips = data.clips || {};
    for (const c of Object.values(this.clips)) {
      c.n = c.frames;
      c.static = {};
      c.mean = {};
      for (const [b, v] of Object.entries(c.bones)) {
        if (v.length === 3) { c.static[b] = true; c.mean[b] = v; continue; }
        const m = [0, 0, 0];
        for (let i = 0; i < v.length; i += 3) { m[0] += v[i]; m[1] += v[i + 1]; m[2] += v[i + 2]; }
        c.mean[b] = m.map((x) => x / (v.length / 3));
      }
      c.cycles = c.cycles || 1;
    }
    this._a = {};
  }

  static async load(url = '/anim/clips.json') {
    const r = await fetch(url);
    if (!r.ok) throw new Error(`No se pudieron cargar las animaciones (${r.status})`);
    return new ClipLib(await r.json());
  }

  has(name) { return !!this.clips[name]; }
  dur(name) { return this.clips[name] ? this.clips[name].dur : 0; }

  // El cuadro de `name` en el segundo `time` (en bucle si el clip lo es; si no, se queda en el último). Devuelve
  // { get(bone) → [x, y, z] | null, hips: [x, y, z] } (la cadera, en alturas de cadera). Reutiliza sus arrays.
  at(name, time) {
    const c = this.clips[name];
    if (!c) return null;
    let f = time * c.fps;
    let i0, i1, k;
    if (c.loop) {
      f = ((f % c.n) + c.n) % c.n;
      i0 = Math.floor(f); i1 = (i0 + 1) % c.n; k = f - i0;
    } else {
      f = Math.max(0, Math.min(c.n - 1, f));
      i0 = Math.floor(f); i1 = Math.min(c.n - 1, i0 + 1); k = f - i0;
    }
    const out = this._a[name] || (this._a[name] = { v: {}, hips: [0, 0, 0], get: null });
    out.get = (b) => {
      const tr = c.bones[b];
      if (!tr) return null;
      if (c.static[b]) return tr;
      const v = out.v[b] || (out.v[b] = [0, 0, 0]);
      const a = i0 * 3, d = i1 * 3;
      v[0] = lerp(tr[a], tr[d], k); v[1] = lerp(tr[a + 1], tr[d + 1], k); v[2] = lerp(tr[a + 2], tr[d + 2], k);
      return v;
    };
    const h = c.hips, a = i0 * 3, d = i1 * 3;
    out.hips[0] = lerp(h[a], h[d], k); out.hips[1] = lerp(h[a + 1], h[d + 1], k); out.hips[2] = lerp(h[a + 2], h[d + 2], k);
    return out;
  }
}

// Una capa que se está reproduciendo. mask: { legs, hips, spine, head, arms, fingers } (0..1, lo que falte = 1).
// amp: cuánto se marca el movimiento alrededor de la postura media del clip (1 = tal cual; 1,2 = un 20 % más vivo,
// como la animación de anime, que exagera lo que la captura hace en pequeño; 0,8 = más apagado).
export class Layer {
  constructor(name, { rate = 1, mask = {}, loop = null, fade = 4, t = 0, amp = 1 } = {}) {
    Object.assign(this, { name, rate, mask, fade, t, w: 0, goal: 1, loop, amp });
  }
  zone(bone) {
    for (const [z, list] of Object.entries(ZONES)) if (list.includes(bone)) return this.mask[z] ?? 1;
    return this.mask.fingers ?? 1;
  }
}

// Pone la capa sobre la pose: cada hueso va hacia el giro del clip con su peso (los que se suman después —respirar,
// gestos, emociones— siguen encima). `hipsY` = altura de la cadera del modelo, para la posición de la cadera.
export function applyLayer(p, lib, layer, w, hipsY) {
  if (w < 0.005) return;
  const fr = lib.at(layer.name, layer.t);
  if (!fr) return;
  const amp = layer.amp, mean = lib.clips[layer.name].mean, tmp = _tmp;
  for (const b of BODY) {
    let v = fr.get(b);
    if (!v || !p.r[b]) continue;
    if (amp !== 1) {
      const m = mean[b];
      tmp[0] = m[0] + (v[0] - m[0]) * amp; tmp[1] = m[1] + (v[1] - m[1]) * amp; tmp[2] = m[2] + (v[2] - m[2]) * amp;
      v = tmp;
    }
    p.set(b, v, w * layer.zone(b));
  }
  // Dedos: los guarda aparte (avatar.js los mezcla con los suyos, que van por «cerrar / abrir»).
  const fw = w * (layer.mask.fingers ?? 1);
  if (fw > 0.005) {
    p.fingerW = Math.max(p.fingerW, fw);
    for (const name of FINGER_BONES) {
      const v = fr.get(name);
      if (!v) continue;
      const cur = p.fingers[name] || (p.fingers[name] = [0, 0, 0]);
      const k = fw / Math.max(fw, p.fingerW);
      cur[0] = lerp(cur[0], v[0], k); cur[1] = lerp(cur[1], v[1], k); cur[2] = lerp(cur[2], v[2], k);
    }
  }
  const hw = w * (layer.mask.hips ?? 1);
  p.lift = lerp(p.lift, fr.hips[1] * hipsY, hw);
  p.shift = lerp(p.shift, fr.hips[0] * hipsY, hw);
  p.fwd = lerp(p.fwd, fr.hips[2] * hipsY, hw);
}

export const FINGER_BONES = ['left', 'right'].flatMap((s) => ['Thumb', 'Index', 'Middle', 'Ring', 'Little'].flatMap((f) =>
  (f === 'Thumb' ? ['Metacarpal', 'Proximal', 'Distal'] : ['Proximal', 'Intermediate', 'Distal']).map((seg) => s + f + seg)));
