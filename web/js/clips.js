// Animaciones grabadas (17 nov 2026): web/anim/clips.bin (o clips.json de respaldo), generadas con
// scripts/herramientas/convertir_animaciones.py a partir de Universal Animation Library (CC0) y 100STYLE (CC BY 4.0).
// Al cargar, canonicaliza ramas equivalentes de Euler XYZ cerca de ±π/2 (evitando torsiones al mezclar con T-pose)
// y desenvuelve saltos de ±2π entre fotogramas consecutivos.

const lerp = (a, b, t) => a + (b - a) * t;
const TWO_PI = Math.PI * 2;

function wrapPi(a) {
  let x = (a + Math.PI) % TWO_PI;
  if (x < 0) x += TWO_PI;
  return x - Math.PI;
}

function unwrapNear(v, ref) {
  return v + TWO_PI * Math.round((ref - v) / TWO_PI);
}

// En Euler intrínseco XYZ, (x, y, z) y (x + π, π - y, z + π) representan exactamente la misma rotación 3D.
// Si una pista cayó en la rama con |x|≈π y |z|≈π, mezclarla linealmente con (0,0,0) retuerce el antebrazo ~100°.
function canonicalizeTrack(arr) {
  if (!arr || arr.length < 3) return arr;
  if (arr.length === 3) {
    const x1 = wrapPi(arr[0]), y1 = wrapPi(arr[1]), z1 = wrapPi(arr[2]);
    const x2 = wrapPi(arr[0] + Math.PI), y2 = wrapPi(Math.PI - arr[1]), z2 = wrapPi(arr[2] + Math.PI);
    const n1 = x1 * x1 + y1 * y1 + z1 * z1;
    const n2 = x2 * x2 + y2 * y2 + z2 * z2;
    const out = arr instanceof Float32Array ? new Float32Array(3) : [0, 0, 0];
    if (n2 + 1e-4 < n1) { out[0] = x2; out[1] = y2; out[2] = z2; }
    else { out[0] = x1; out[1] = y1; out[2] = z1; }
    return out;
  }
  const out = arr instanceof Float32Array ? new Float32Array(arr.length) : new Array(arr.length);
  for (let i = 0; i < arr.length; i += 3) {
    const rx = arr[i], ry = arr[i + 1], rz = arr[i + 2];
    let ax = wrapPi(rx), ay = wrapPi(ry), az = wrapPi(rz);
    let bx = wrapPi(rx + Math.PI), by = wrapPi(Math.PI - ry), bz = wrapPi(rz + Math.PI);
    if (i === 0) {
      const na = ax * ax + ay * ay + az * az;
      const nb = bx * bx + by * by + bz * bz;
      if (nb + 1e-4 < na) { out[0] = bx; out[1] = by; out[2] = bz; }
      else { out[0] = ax; out[1] = ay; out[2] = az; }
    } else {
      const px = out[i - 3], py = out[i - 2], pz = out[i - 1];
      ax = unwrapNear(ax, px); ay = unwrapNear(ay, py); az = unwrapNear(az, pz);
      bx = unwrapNear(bx, px); by = unwrapNear(by, py); bz = unwrapNear(bz, pz);
      const da = (ax - px) ** 2 + (ay - py) ** 2 + (az - pz) ** 2;
      const db = (bx - px) ** 2 + (by - py) ** 2 + (bz - pz) ** 2;
      if (db + 1e-4 < da) { out[i] = bx; out[i + 1] = by; out[i + 2] = bz; }
      else { out[i] = ax; out[i + 1] = ay; out[i + 2] = az; }
    }
  }
  return out;
}

function decodeClipsBin(buf) {
  const bytes = new Uint8Array(buf);
  if (bytes.length < 8 || bytes[0] !== 0x43 || bytes[1] !== 0x4c || bytes[2] !== 0x50 || bytes[3] !== 0x42) {
    throw new Error('Formato clips.bin inválido');
  }
  const view = new DataView(buf);
  const hlen = view.getUint32(4, true);
  const headerJson = new TextDecoder().decode(bytes.subarray(8, 8 + hlen));
  const meta = JSON.parse(headerJson);
  const floatByteOffset = (8 + hlen + 3) & ~3;
  const floats = new Float32Array(buf, floatByteOffset);
  const clips = {};
  for (const [name, c] of Object.entries(meta.clips || {})) {
    const bones = {};
    for (const [b, [off, len]] of Object.entries(c.bones || {})) {
      bones[b] = floats.subarray(off, off + len);
    }
    const [hOff, hLen] = c.hips;
    clips[name] = {
      frames: c.frames,
      fps: c.fps,
      loop: c.loop,
      dur: c.dur,
      stride: c.stride,
      cycles: c.cycles || 1,
      speed: c.speed || 0,
      source: c.source || '',
      bones,
      hips: floats.subarray(hOff, hOff + hLen),
    };
  }
  return { version: meta.version || 1, license: meta.license || '', clips };
}

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
      for (const [b, raw] of Object.entries(c.bones)) {
        const v = canonicalizeTrack(raw);
        c.bones[b] = v;
        if (v.length === 3) { c.static[b] = true; c.mean[b] = v; continue; }
        let mx = 0, my = 0, mz = 0;
        for (let i = 0; i < v.length; i += 3) { mx += v[i]; my += v[i + 1]; mz += v[i + 2]; }
        const frames = v.length / 3;
        c.mean[b] = [mx / frames, my / frames, mz / frames];
      }
      c.cycles = c.cycles || 1;
    }
    this._a = {};
  }

  static async load(url = '/anim/clips.json') {
    if (url === '/anim/clips.json') {
      try {
        const rb = await fetch('/anim/clips.bin');
        if (rb.ok) {
          const buf = await rb.arrayBuffer();
          if (buf.byteLength >= 8) return new ClipLib(decodeClipsBin(buf));
        }
      } catch { /* fallback limpio a JSON */ }
    }
    const r = await fetch(url);
    if (!r.ok) throw new Error(`No se pudieron cargar las animaciones (${r.status})`);
    return new ClipLib(await r.json());
  }

  has(name) { return !!this.clips[name]; }
  dur(name) { return this.clips[name] ? this.clips[name].dur : 0; }

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

export class Layer {
  constructor(name, { rate = 1, mask = {}, loop = null, fade = 4, t = 0, amp = 1 } = {}) {
    Object.assign(this, { name, rate, mask, fade, t, w: 0, goal: 1, loop, amp });
  }
  zone(bone) {
    for (const [z, list] of Object.entries(ZONES)) if (list.includes(bone)) return this.mask[z] ?? 1;
    return this.mask.fingers ?? 1;
  }
}

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
