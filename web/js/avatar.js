// El cuerpo del personaje: carga el modelo VRM y lo anima sobre el esqueleto humanoide normalizado que trae todo
// modelo, así que sirve para cualquier VRM. La base son animaciones grabadas (clips.js, 17 nov 2026: reposo, hablar,
// andar, agacharse…) y encima va todo lo procedural de abajo.
//   · vida propia: respiración, cambio de peso de una pierna a otra, brazos que cuelgan y se mecen, dedos
//     relajados, parpadeo, mirada con pequeños desvíos y, de vez en cuando, un gesto ocioso
//   · conversación: escucha inclinándose, piensa con la mano en la barbilla, y al hablar mueve las manos
//     (explica, abre las palmas, se lleva una mano al pecho…) marcando el ritmo de la voz
//   · emociones → cara, postura del cuerpo y efectos (rubor, corazones, sudor…: ver effects.js)
//   · voz → boca · etiquetas [gesto:...] → gestos concretos
//
// Todas las poses están escritas en la convención de VRM 1.0 (el personaje mira a +Z y su izquierda es +X).
// Los modelos VRM 0.x miran al revés: al aplicar la pose se invierten los giros en X y Z.
// Los brazos se escriben para el IZQUIERDO y se reflejan para el derecho (cambian de signo Y y Z):
//   brazo  [x: − adelante, y: − gira hacia dentro, z: −π/2 colgando]   antebrazo [y: − dobla el codo]

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { VRMLoaderPlugin, VRMUtils, VRMSpringBoneCollider, VRMSpringBoneColliderShapeCapsule, VRMSpringBoneColliderShapePlane } from '@pixiv/three-vrm';
import { Effects } from './effects.js';
import { Orb, ORB_Y } from './orb.js';
import { ClipLib, Layer, applyLayer } from './clips.js';
import { addParts, EMO_PARTS, LIP_PARTS, Micro } from './face.js';
import { Lipsync } from './lipsync.js';
import { Device } from './props.js';

const FOV = 26;
const SIDES = ['left', 'right'];
const BONES = ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
  ...SIDES.flatMap((s) => ['Shoulder', 'UpperArm', 'LowerArm', 'Hand', 'UpperLeg', 'LowerLeg', 'Foot'].map((b) => s + b))];
const FINGERS = ['Thumb', 'Index', 'Middle', 'Ring', 'Little'];
// Cada hueso sigue a su objetivo como un muelle: [frecuencia (rad/s), amortiguación]. Con amortiguación < 1 se pasa
// un poco y vuelve, como un brazo de verdad; la mano, la que más (va «arrastrada» por el antebrazo).
const SPRING = (b) => (/Hand/.test(b) ? [15, 0.58] : /LowerArm/.test(b) ? [13, 0.66] : /UpperArm/.test(b) ? [11.5, 0.72]
  : /Shoulder/.test(b) ? [13, 0.85] : /head|neck/.test(b) ? [15, 0.78] : /Leg|Foot|hips/.test(b) ? [10, 0.95] : [13, 0.85]);
const SPRINGS = Object.fromEntries(BONES.map((b) => [b, SPRING(b)]));

const FACE_KEYS = ['happy', 'angry', 'sad', 'relaxed', 'surprised'];
const VISEMES = ['aa', 'ih', 'ou', 'ee', 'oh'];

const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;
const ease = (t) => t * t * (3 - 2 * t);
const damp = (rate, dt) => 1 - Math.exp(-rate * dt);
const wave = (t, hz) => Math.sin(t * Math.PI * 2 * hz);
const rand = (a, b) => a + Math.random() * (b - a);
const pick = (list, not) => { const l = list.filter((x) => x !== not); return l[Math.floor(Math.random() * l.length)]; };
// Ruido suave (-1..1): para los movimientos ociosos, que con senos puros se notan repetitivos.
const hash = (n) => { const x = Math.sin(n * 127.1 + 311.7) * 43758.5453; return (x - Math.floor(x)) * 2 - 1; };
const noise = (t, seed = 0) => { const i = Math.floor(t), f = t - i; return lerp(hash(i + seed * 57.3), hash(i + 1 + seed * 57.3), ease(f)); };

function envelope(t, dur, edge = 0.22) {
  return ease(clamp(Math.min(t / (dur * edge), (dur - t) / (dur * edge))));
}

class Pose {
  constructor() {
    this.r = {};
    for (const b of BONES) this.r[b] = [0, 0, 0];
    this.gaze = [0, 0];
    this.curl = { left: 0, right: 0 };     // dedos: 0 mano abierta · 1 puño
    this.index = { left: 0, right: 0 };    // índice estirado aunque los demás se cierren (señalar, contar)
    this.spread = { left: 0, right: 0 };   // dedos separados (palma abierta, susto)
    this.fingers = {};                      // dedos de las animaciones grabadas (clips.js), hueso → giro
    // Postura de mano con cada dedo por separado (HANDS): cuánto se cierra cada uno y cuánto manda la postura.
    this.shape = { left: { Thumb: 0, Index: 0, Middle: 0, Ring: 0, Little: 0, fan: null }, right: { Thumb: 0, Index: 0, Middle: 0, Ring: 0, Little: 0, fan: null } };
    this.shapeW = { left: 0, right: 0 };
    this.reset();
  }
  reset() {
    for (const b of BONES) { const v = this.r[b]; v[0] = v[1] = v[2] = 0; }
    this.gaze[0] = this.gaze[1] = 0;
    this.lift = 0;                          // sube o baja el cuerpo (m)
    this.shift = 0;                         // lo desplaza de lado (m)
    this.fwd = 0;                           // lo adelanta o atrasa (m)
    this.fingerW = 0;                       // cuánto mandan los dedos de las animaciones grabadas
    this.handSet = 0;                       // cuánto ha puesto el código los dedos a propósito (puño, señalar…)
    this.curl.left = this.curl.right = 0.3;
    this.index.left = this.index.right = 0;
    this.spread.left = this.spread.right = 0.15;
    this.shapeW.left = this.shapeW.right = 0;
    this.shape.left.fan = this.shape.right.fan = null;
    this.shake = 0;                         // temblor (susto)
  }
  // Postura de mano (HANDS) con su peso: cada dedo a su sitio (OK, pulgar arriba, paz, pinza, mano suave…).
  hand(side, name, w = 1) {
    const h = HANDS[name], sh = this.shape[side];
    if (!h || w <= 0) return;
    const k = this.shapeW[side] > 0 ? w : 1;               // la primera postura se toma entera; las siguientes, mezcladas
    for (const f of FIVE) sh[f] = lerp(sh[f], h[f], k);
    if (h.sp !== undefined) this.spread[side] = lerp(this.spread[side], h.sp, w);
    if (h.fan) sh.fan = h.fan; else if (w > 0.5) sh.fan = null;
    this.shapeW[side] = Math.max(this.shapeW[side], w);
    this.handSet = Math.max(this.handSet, w);
  }
  add(bone, v, w = 1) { const r = this.r[bone]; r[0] += v[0] * w; r[1] += v[1] * w; r[2] += v[2] * w; }
  set(bone, v, w = 1) { const r = this.r[bone]; r[0] = lerp(r[0], v[0], w); r[1] = lerp(r[1], v[1], w); r[2] = lerp(r[2], v[2], w); }
  // Brazo entero escrito para el izquierdo; `side` lo refleja. u = brazo, l = antebrazo, h = mano, c = dedos,
  // ix = índice estirado (0..1), sp = dedos separados (0..1).
  arm(side, { u, l, h, c, ix, sp, hs }, w = 1, mode = 'set') {
    const s = side === 'left' ? 1 : -1;
    const put = (bone, v) => v && this[mode](side + bone, [v[0], v[1] * s, v[2] * s], w);
    put('UpperArm', u); put('LowerArm', l); put('Hand', h);
    if (hs && mode === 'set') this.hand(side, hs, w);     // hs = postura de mano (HANDS)
    if (c !== undefined || ix !== undefined || sp !== undefined) this.handSet = Math.max(this.handSet, mode === 'set' ? w : 0);
    if (c !== undefined) this.curl[side] = lerp(this.curl[side], c, w);
    if (ix !== undefined) this.index[side] = lerp(this.index[side], ix, w);
    if (sp !== undefined) this.spread[side] = lerp(this.spread[side], sp, w);
  }
  both(pose, w = 1, mode = 'set') { this.arm('left', pose, w, mode); this.arm('right', pose, w, mode); }
  shoulders(up, w = 1) { this.add('leftShoulder', [0, 0, up], w); this.add('rightShoulder', [0, 0, -up], w); }
}

// La pose reflejada (izquierda ↔ derecha): se cambian los huesos de cada lado y se invierten los giros en Y y Z.
function mirrorPose(p) {
  for (const b of BONES) {
    if (b.startsWith('left')) {
      const o = 'right' + b.slice(4), l = p.r[b], r = p.r[o];
      if (!r) continue;
      const lx = l[0], ly = l[1], lz = l[2];
      l[0] = r[0]; l[1] = -r[1]; l[2] = -r[2];
      r[0] = lx; r[1] = -ly; r[2] = -lz;
    } else if (!b.startsWith('right')) { const v = p.r[b]; v[1] = -v[1]; v[2] = -v[2]; }
  }
  p.shift = -p.shift;
}

// ---------------------------------------------------------------- posturas de mano (17 nov 2026)
// Cada dedo por separado (0 estirado · 1 cerrado; en el pulgar, 0 al lado y 1 sobre la palma). Ideas de los gestos
// de TalkingHead (MIT, met4citizen: ok, pulgar arriba, señalar); los valores son propios, para el esqueleto de VRM.
// sp = separación en abanico; fan = abanico propio de algún dedo (la V de la paz).
const FIVE = ['Thumb', 'Index', 'Middle', 'Ring', 'Little'];
export const HANDS = {
  relax: { Thumb: 0.3, Index: 0.2, Middle: 0.3, Ring: 0.4, Little: 0.5 },
  grace: { Thumb: 0.12, Index: 0.02, Middle: 0.14, Ring: 0.26, Little: 0.4, sp: 0.4 },          // mano suave, de anime
  open: { Thumb: -0.1, Index: -0.08, Middle: -0.06, Ring: -0.04, Little: 0, sp: 1 },
  fist: { Thumb: 0.85, Index: 1, Middle: 1, Ring: 1, Little: 1, sp: 0 },
  point: { Thumb: 0.75, Index: -0.05, Middle: 0.95, Ring: 1, Little: 1, sp: 0 },
  ok: { Thumb: 0.85, Index: 0.72, Middle: -0.05, Ring: 0.06, Little: 0.14, sp: 0.7 },
  pinch: { Thumb: 0.85, Index: 0.55, Middle: 0.45, Ring: 0.55, Little: 0.62, sp: 0.1 },             // precisar algo al hablar
  thumb: { Thumb: -0.15, Index: 1, Middle: 1, Ring: 1, Little: 1, sp: 0 },
  peace: { Thumb: 0.9, Index: -0.05, Middle: -0.05, Ring: 1, Little: 1, sp: 0, fan: { Index: -1.8, Middle: 1.4 } },
};
// Cascada natural: aunque la mano entera se cierre igual, el índice va algo más abierto y el meñique más cerrado.
const CASCADE = { Index: -0.07, Middle: 0, Ring: 0.06, Little: 0.12 };
// Cada dedo llega a su ritmo (el índice primero, el meñique el último): la mano no se mueve como un bloque.
const FINGER_RATE = { Thumb: 12, Index: 14, Middle: 11.5, Ring: 10, Little: 8.5 };
const FINGER_SEED = { Thumb: 31, Index: 32, Middle: 33, Ring: 34, Little: 35 };
// Oposición del pulgar (pinza, OK, puño): cuánto gira, por eje, lo que pasa de 0,5 de cierre (medido con primeros
// planos: en Y negativo cruza hacia la punta del índice; en Z lo pasaría por encima de los dedos).
export const THUMB = { x: 0, y: -2.4, z: 0, zd: 1 };

// ---------------------------------------------------------------- posturas de brazos
export const ARMS = {
  rest:    { u: [0.05, -0.12, -1.27], l: [0, -0.36, 0], h: [0, 0, -0.06], c: 0.3 },     // colgando, codo algo doblado
  ready:   { u: [-0.06, -0.2, -1.22], l: [0, -0.75, 0], h: [0, 0, 0], c: 0.22 },       // antebrazos algo levantados
  explain: { u: [-0.24, -0.25, -1.18], l: [0, -1.4, 0], h: [-1.5, 0, 0.12], c: 0.1, sp: 0.5, hs: 'grace' }, // una mano delante, palma hacia arriba
  open:    { u: [-0.14, 0.02, -1.2], l: [0, -1.25, 0], h: [-0.7, 0, 0.16], c: 0.05, sp: 0.8, hs: 'open' },  // antebrazos delante, palmas abiertas
  chest:   { u: [-0.3, -0.5, -1.22], l: [0, -1.95, 0], h: [0.1, 0, 0.12], c: 0.18, sp: 0.3, hs: 'grace' },  // mano al propio pecho (no al hombro)
  point:   { u: [-0.42, -0.3, -1.16], l: [0, -1.55, 0], h: [0, 0, 0.12], c: 0.85, ix: 1, hs: 'point' },      // mano delante, índice arriba (contar)
  front:   { u: [-0.16, -0.55, -1.24], l: [0, -1.4, 0], h: [0, 0, 0.1], c: 0.35 },      // manos juntas delante
  guard:   { u: [-0.42, -0.6, -1.12], l: [0, -2.3, 0], h: [0, 0, 0.1], c: 0.75, hs: 'fist' },       // encogida, puños al pecho
  chin:    { u: [-0.55, 0, -1.05], l: [0, -2.0, 0], h: [0, 0, 0], c: 0.55 },            // mano a la barbilla
  fists:   { u: [0.12, -0.1, -1.31], l: [0, -0.45, 0], h: [0, 0, 0], c: 0.95, hs: 'fist' },         // brazos tensos, puños
  startle: { u: [-0.15, -0.2, -1.17], l: [0, -1.95, 0], h: [0, 0, 0], c: -0.1, sp: 1, hs: 'open' }, // manos arriba, dedos abiertos
  limp:    { u: [0.02, -0.2, -1.33], l: [0, -0.2, 0], h: [0, 0, -0.1], c: 0.4 },        // caídos, sin fuerza
};

// ---------------------------------------------------------------- gestos al hablar
// Mientras habla va encadenando estos gestos (uno cada pocos segundos) y los marca con el ritmo de la voz.
// run(p, side, w, beat, t): w = cuánto está «dentro» del gesto, beat = golpe de voz del momento.
const TALK = {
  explica(p, side, w, beat) {
    p.arm(side, ARMS.explain, w);
    p.add(side + 'LowerArm', [0, (side === 'left' ? -1 : 1) * 0.2 * beat, 0], w);
    p.add('spine', [0, (side === 'left' ? -1 : 1) * 0.04, 0], w);
  },
  abre(p, side, w, beat) {
    p.both(ARMS.open, w);
    p.shoulders(0.05 + 0.04 * beat, w);
    p.add('head', [0, 0, 0.04], w);
  },
  pecho(p, side, w, beat) {
    p.arm(side, ARMS.chest, w);
    p.add('head', [0.04, 0, (side === 'left' ? 1 : -1) * 0.05], w);
    p.add('chest', [0.02 + 0.02 * beat, 0, 0], w);
  },
  cuenta(p, side, w, beat) {
    p.arm(side, ARMS.point, w);
    p.add(side + 'LowerArm', [0, (side === 'left' ? -1 : 1) * 0.22 * beat, 0], w);      // marca cada punto con el índice
    p.add(side + 'Hand', [-0.15 * beat, 0, 0], w);
    p.add('head', [-0.03, (side === 'left' ? 1 : -1) * 0.06, 0], w);
  },
  ambas(p, side, w, beat, t) {
    p.both(ARMS.explain, w);
    const s = 0.14 * Math.sin(t * 3.1);
    p.add('leftLowerArm', [0, -0.16 * beat + s, 0], w);
    p.add('rightLowerArm', [0, 0.16 * beat + s, 0], w);
  },
  // Precisar algo: la mano delante en pinza (pulgar con índice) o haciendo «OK», marcando el ritmo con la muñeca.
  precisa(p, side, w, beat) {
    p.arm(side, { u: [-0.3, -0.3, -1.15], l: [0, -1.6, 0], h: [-0.55, 0, 0.1], hs: side === 'left' ? 'ok' : 'pinch' }, w);
    p.add(side + 'Hand', [-0.3 * beat, 0, 0], w);
    p.add('head', [-0.02, (side === 'left' ? 1 : -1) * 0.04, 0], w);
  },
  encoge(p, side, w) {
    p.both(ARMS.open, w * 0.8);
    p.shoulders(0.16, w);
    p.add('head', [0, 0, (side === 'left' ? 1 : -1) * 0.1], w);
  },
};
const TALK_NAMES = Object.keys(TALK);

// ---------------------------------------------------------------- emociones
// Cara (expresiones VRM), cabeza, mirada y cuerpo. Los efectos visibles (rubor, corazones…) están en effects.js.
//   hands: la postura ocupa las manos, así que no gesticula al hablar · blink: parpadea más o menos seguido
const EMOTIONS = {
  neutral:     { face: {} },
  // Pesos medidos con el modelo de VRoid: «happy» por encima de ~0,5 cierra los ojos y abre la boca del todo.
  feliz:       { face: { happy: 0.42 }, body(p, t, w) { p.add('chest', [-0.02, 0, 0], w); p.add('head', [0, 0, 0.03 * Math.sin(t * 1.6)], w); } },
  emocionada:  { face: { happy: 0.75 }, head: [-0.05, 0, 0], body(p, t, w, a) {
    p.both(ARMS.ready, w * 0.8);
    p.both({ l: [0, -0.5, 0], c: 0.8 }, w, 'add');
    p.lift += 0.012 * Math.abs(Math.sin(t * 5.2)) * w * (0.4 + 0.6 * a.stateW.speaking);
    p.shoulders(0.05, w);
  } },
  timida:      { face: { relaxed: 0.45 }, head: [0.14, 0.14, 0.05], gaze: [-0.25, -0.14], hands: true, body(p, t, w) {
    p.both(ARMS.front, w);
    p.shoulders(0.1, w);
    p.add('spine', [0.03, 0.06 * Math.sin(t * 0.9), 0], w);
    p.add('chest', [0.03, 0, 0], w);
  } },
  sonrojada:   { face: { relaxed: 0.5, happy: 0.2 }, head: [0.1, -0.12, -0.05], gaze: [0.22, -0.12], hands: true, body(p, t, w) {
    p.arm('left', ARMS.front, w);
    p.arm('right', ARMS.chest, w * 0.9);
    p.shoulders(0.08, w);
    p.add('hips', [0, 0.05 * Math.sin(t * 1.1), 0], w);
  } },
  triste:      { face: { sad: 0.8 }, head: [0.1, 0, 0.04], gaze: [0, -0.25], hands: true, blink: 0.7, body(p, t, w) {
    p.both(ARMS.limp, w);
    p.shoulders(-0.07, w);
    p.add('spine', [0.08, 0, 0], w);
    p.add('chest', [0.07, 0, 0], w);
    p.lift -= 0.012 * w;
  } },
  molesta:     { face: { angry: 0.7 }, head: [0.08, 0, -0.05], hands: true, body(p, t, w, a) {
    // Con las animaciones grabadas, se cruza de brazos; si no, puños apretados.
    if (a.lib && a.lib.has('fold_arms')) { a._L.fold.t = a.emoAge; applyLayer(p, a.lib, a._L.fold, w, a.hipsY); }
    else p.both(ARMS.fists, w);
    p.shoulders(0.06, w);
    p.add('spine', [0.04, 0, 0], w);
    p.add('chest', [-0.03, 0, 0], w);
  } },
  sorprendida: { face: { surprised: 0.65 }, head: [-0.09, 0, 0], blink: 0.4, body(p, t, w, a) {
    const jolt = Math.max(0, 1 - a.emoAge * 2.2);                 // respingo al sentirla
    p.both(ARMS.startle, w * (0.75 + 0.25 * jolt));
    p.shoulders(0.08 + 0.1 * jolt, w);
    p.add('spine', [-0.05 - 0.05 * jolt, 0, 0], w);
    p.lift += 0.02 * jolt * w;
  } },
  pensativa:   { face: { relaxed: 0.2 }, head: [-0.05, 0.12, 0.08], gaze: [0.3, 0.25], hands: true, body(p, t, w) {
    p.arm('right', ARMS.chin, w * 0.9);
    p.arm('left', ARMS.front, w * 0.5);
  } },
  carinosa:    { face: { relaxed: 0.5, happy: 0.25 }, head: [0.03, 0, 0.1], body(p, t, w) {
    p.add('hips', [0, 0.04 * Math.sin(t * 1.0), 0], w);
    p.add('spine', [0.02, 0, 0.02 * Math.sin(t * 1.0)], w);
  } },
  enamorada:   { face: { happy: 0.4, relaxed: 0.45 }, head: [0.02, 0, 0.13], gaze: [0, 0.03], hands: true, blink: 1.3, body(p, t, w) {
    p.both(ARMS.chest, w);
    p.shoulders(0.07, w);
    p.add('hips', [0, 0.07 * Math.sin(t * 1.3), 0.02 * Math.sin(t * 1.3)], w);
    p.add('spine', [0, -0.04 * Math.sin(t * 1.3), 0], w);
    p.lift += 0.006 * Math.sin(t * 2.6) * w;
  } },
  nerviosa:    { face: { sad: 0.25, surprised: 0.15 }, head: [0.05, 0, 0], hands: true, blink: 2.4, dart: 1, body(p, t, w) {
    p.both(ARMS.front, w);
    p.add('leftHand', [0.25 * Math.sin(t * 6.3), 0, 0.1 * Math.sin(t * 5.1)], w);      // se retuerce las manos
    p.add('rightHand', [0.25 * Math.sin(t * 6.3 + 2), 0, 0.1 * Math.sin(t * 4.7)], w);
    p.shoulders(0.12 + 0.02 * Math.sin(t * 4), w);
    p.add('hips', [0, 0.04 * Math.sin(t * 2.3), 0.015 * Math.sin(t * 3.1)], w);
    p.add('head', [0, 0.07 * Math.sin(t * 1.9), 0], w);
  } },
  asustada:    { face: { surprised: 0.6, sad: 0.35 }, head: [-0.02, 0, 0], hands: true, blink: 0.3, dart: 0.5, body(p, t, w, a) {
    const jolt = Math.max(0, 1 - a.emoAge * 2);
    p.both(ARMS.guard, w);
    p.shoulders(0.2, w);
    p.add('spine', [-0.07 - 0.05 * jolt, 0, 0], w);
    p.add('chest', [0.06, 0, 0], w);
    p.add('head', [0.06, 0, 0], w);
    p.lift += (0.02 * jolt - 0.015) * w;
    p.shake = Math.max(p.shake, w);
  } },
  confundida:  { face: { surprised: 0.22, sad: 0.15 }, head: [0, 0.08, 0.2], gaze: [0.15, 0.12], body(p, t, w) {
    p.arm('right', ARMS.explain, w * 0.75);
    p.add('rightShoulder', [0, 0, -0.14], w);
    p.add('spine', [0, 0, -0.03], w);
  } },
};

// ---------------------------------------------------------------- gestos con nombre
// Los que pide el LLM con [gesto:...] y, con «_», los que hace sola cuando no pasa nada.
// set = lleva el hueso a ese giro; add = lo suma.
const GESTURES = {
  saludar: { dur: 2.3, run(p, t, w) {
    p.set('rightUpperArm', [-0.2, 0, 0.45], w);
    p.set('rightLowerArm', [0, 0, -1.7 + 0.35 * wave(t, 2.4)], w);
    p.set('rightHand', [0, 0, 0.25 * wave(t, 2.4)], w);
    p.curl.right = lerp(p.curl.right, 0.05, w);
    p.add('head', [0, 0, -0.08], w);
    p.add('spine', [0, 0, -0.03], w);
  } },
  asentir: { dur: 1.0, run(p, t, w) {
    p.add('head', [0.2 * Math.max(0, wave(t, 2.0)) + 0.04, 0, 0], w);
    p.add('neck', [0.06 * Math.max(0, wave(t, 2.0)), 0, 0], w);
  } },
  negar: { dur: 1.2, run(p, t, w) {
    p.add('head', [0, 0.28 * wave(t, 2.1), 0], w);
    p.add('neck', [0, 0.08 * wave(t, 2.1), 0], w);
  } },
  pensar: { dur: 2.4, run(p, t, w) {
    p.arm('right', ARMS.chin, w);
    p.add('head', [-0.06, 0.16, 0.1], w);
    p.gaze[0] += 0.3 * w; p.gaze[1] += 0.25 * w;
  } },
  encogerse: { dur: 1.5, run(p, t, w) {
    p.shoulders(0.24, w);
    p.set('leftUpperArm', [-0.1, 0, -0.95], w);
    p.set('rightUpperArm', [-0.1, 0, 0.95], w);
    p.set('leftLowerArm', [0, -1.0, 0.25], w);
    p.set('rightLowerArm', [0, 1.0, -0.25], w);
    p.curl.left = p.curl.right = lerp(p.curl.left, 0.05, w);
    p.add('head', [0, 0, 0.1], w);
  } },
  reverencia: { dur: 1.7, run(p, t, w) {
    p.both(ARMS.front, w * 0.8);
    p.add('spine', [0.3, 0, 0], w);
    p.add('chest', [0.12, 0, 0], w);
    p.add('head', [0.18, 0, 0], w);
  } },
  celebrar: { dur: 1.9, run(p, t, w) {
    const b = 0.08 * wave(t, 2.6);
    p.set('leftUpperArm', [-0.1, 0, 0.85 + b], w);
    p.set('rightUpperArm', [-0.1, 0, -0.85 - b], w);
    p.set('leftLowerArm', [0, 0, 0.6], w);
    p.set('rightLowerArm', [0, 0, -0.6], w);
    p.curl.left = p.curl.right = lerp(p.curl.left, 0.9, w);
    p.add('head', [-0.08, 0, 0], w);
    p.lift += 0.02 * Math.abs(wave(t, 2.6)) * w;
  } },
  // Pulgar arriba y la V de la paz junto a la cara (17 nov 2026, con las posturas de mano por dedo).
  pulgar: { dur: 1.9, run(p, t, w) {
    p.arm('right', { u: [-0.7, -0.45, -1.2], l: [0, -1.35, 0], h: [0, 0, 0.25], hs: 'thumb' }, w);
    p.add('rightUpperArm', [-0.06 * Math.max(0, wave(t, 1.6)), 0, 0], w);
    p.add('head', [0.03, -0.06, -0.06], w);
  } },
  paz: { dur: 2.2, run(p, t, w) {
    p.arm('right', { u: [-0.35, -0.1, -0.5], l: [0, -2.35, 0], h: [0, 0, 0], hs: 'peace' }, w);
    p.add('head', [0.02, -0.08, -0.12], w);
    p.add('spine', [0, 0, -0.03], w);
  } },
  // ---- Pasatiempos (17 nov 2026): lo que hace sola cuando llevas un rato sin usar la app (HOBBIES, más abajo).
  // Usan las animaciones grabadas si están (baile, salto, hechizo, beber) y, si no, una versión escrita aquí.
  _bailar: { dur: 8, run(p, t, w, side, a) {
    const L = a._hob('dance', { fingers: 0.6 });
    if (L) { L.t = t * 0.95; applyLayer(p, a.lib, L, w, a.hipsY); }
    else {
      const b = Math.sin(t * Math.PI * 2 * 1.1);
      p.add('hips', [0, 0.12 * b, 0.05 * b], w); p.add('spine', [0, -0.1 * b, 0.04 * b], w);
      p.both({ u: [-0.3, 0, -0.9], l: [0, -1.6, 0], c: 0.6 }, w);
      p.lift += 0.015 * Math.abs(b) * w;
    }
    a.faceX = { parts: { eyeJoy: 0.45, mthFun: 0.5, brwJoy: 0.4 }, preset: { happy: 0.45 }, w };
    a._notes(t, 0.9);
  } },
  _saltar: { dur: 1.9, run(p, t, w, side, a) {
    const up = clamp((t - 0.35) / 0.8);                         // en el aire de 0,35 a 1,15 s
    const name = t < 0.35 ? 'jump_start' : t < 1.15 ? 'jump_loop' : 'jump_land';
    const L = a._hob(name, { arms: 0.7 });
    if (L) { L.t = name === 'jump_start' ? 0.6 + t : name === 'jump_loop' ? t : 0.1 + (t - 1.15) * 1.2; applyLayer(p, a.lib, L, w, a.hipsY); }
    p.lift += Math.sin(Math.PI * up) * 0.22 * a.hipsY * (up > 0 && up < 1 ? 1 : 0) * w;
    p.lift -= 0.05 * a.hipsY * Math.max(0, 1 - Math.abs(t - 0.25) / 0.2) * w;   // coge impulso
    p.both({ u: [-0.25, 0, 0.55], l: [0, -0.35, 0], hs: 'open' }, w * Math.sin(Math.PI * up));   // brazos arriba, en V
    a.faceX = { parts: { eyeJoy: 0.3, mthJoy: 0.45, brwJoy: 0.5 }, preset: { happy: 0.5 }, w };
  } },
  _girar: { dur: 1.8, run(p, t, w, side, a) {
    const u = clamp((t - 0.15) / 1.4);                          // la vuelta entera la da _petTick (spinYaw)
    p.both({ u: [-0.05, -0.1, -0.75], l: [0, -0.5, 0], hs: 'grace' }, w * Math.sin(Math.PI * u));
    p.lift += 0.02 * a.hipsY * Math.sin(Math.PI * u) * w;
    a.faceX = { parts: { eyeJoy: 0.35, mthFun: 0.55 }, preset: { happy: 0.4 }, w };
  } },
  _estirarse: { dur: 4.2, run(p, t, w, side, a) {
    const k = Math.sin(Math.PI * clamp(t / 4.2)) ** 0.6;
    p.both({ u: [-0.15, 0.1, 1.25], l: [0, -0.35, 0], h: [0, 0, 0.3], hs: 'open' }, w * k);   // brazos arriba
    p.add('spine', [-0.12, 0, 0.04 * Math.sin(t * 1.3)], w * k);
    p.add('chest', [-0.08, 0, 0], w * k);
    p.add('head', [-0.18, 0, 0.05], w * k);
    p.lift += 0.012 * a.hipsY * k * w;                          // de puntillas
    const yawn = Math.sin(Math.PI * clamp((t - 0.8) / 2.4));    // bostezo
    a.faceX = { parts: { eyeJoy: 0.75 * yawn, mthSurprised: 0.65 * yawn, brwSorrow: 0.3 * yawn }, preset: { surprised: 0.3 * yawn, relaxed: 0.4 * yawn }, w };
  } },
  _hechizo: { dur: 3.2, run(p, t, w, side, a) {
    const L = a._hob('spell', { legs: 0.5 });
    if (L && t > 0.9) { L.t = (t - 0.9) * 0.8; applyLayer(p, a.lib, L, w, a.hipsY); }
    else p.arm('right', { u: [-0.6, -0.3, -0.7], l: [0, -1.3, 0], hs: 'point' }, w);
    if (t > 1.0 && !a._spellDone) { a._spellDone = true; a.effects.burst('spark', 6, 1.2); }
    if (t < 0.5) a._spellDone = false;
    a.faceX = { parts: { eyeFun: 0.4, mthFun: 0.4, brwFun: 0.4 }, preset: { happy: 0.3 }, w };
  } },
  _tararear: { dur: 6, run(p, t, w, side, a) {
    const b = Math.sin(t * Math.PI * 2 * 0.55);
    p.add('hips', [0, 0.05 * b, 0.03 * b], w); p.add('head', [0, 0.06 * b, 0.1 * b], w); p.add('spine', [0, 0, -0.03 * b], w);
    p.both(ARMS.front, w * 0.6);
    a.faceX = { parts: { eyeJoy: 0.7, mthFun: 0.35, mthSmall: 0.25 }, preset: { relaxed: 0.5 }, w };
    a._notes(t, 1.4);
  } },
  _beber: { dur: 3, run(p, t, w, side, a) {
    const L = a._hob('consume', { legs: 0.4 });
    if (L) { L.t = t * 0.45; applyLayer(p, a.lib, L, w, a.hipsY); }
    else p.arm('right', ARMS.chin, w);
    a.faceX = { parts: { eyeJoy: 0.5 * Math.sin(Math.PI * clamp(t / 3)) }, preset: {}, w };
  } },
  _curiosear: { dur: 5, run(p, t, w, side, a) {
    const look = Math.sin(t * 1.3) * side;
    p.add('head', [0.05 * Math.sin(t * 2.1), 0.45 * look, 0.05 * look], w);
    p.add('neck', [0, 0.15 * look, 0], w);
    p.add('spine', [0, 0.08 * look, 0], w);
    p.both(ARMS.front, w * 0.5);
    a.faceX = { parts: { brwSurprised: 0.3, eyeSurprised: 0.2, mthSmall: 0.3 }, preset: { surprised: 0.15 }, w };
  } },
  aplaudir: { dur: 2.0, run(p, t, w) {
    const clap = 0.5 + 0.5 * wave(t, 4.2);
    p.both({ u: [-0.36, -0.42 - 0.13 * clap, -1.16], l: [0, -1.8, 0], h: [0, 0, 0.1], c: 0.05 }, w);
    p.add('head', [-0.04, 0, 0.05 * wave(t, 1)], w);
    p.lift += 0.006 * clap * w;
  } },
  risita: { dur: 1.9, run(p, t, w) {
    p.arm('right', { u: [-0.6, -0.25, -1.0], l: [0, -2.25, 0], h: [0, 0, 0.1], c: 0.4 }, w);     // mano a la boca
    p.shoulders(0.06 + 0.035 * wave(t, 5.5), w);
    p.add('head', [0.09, -0.06, 0.07], w);
    p.add('chest', [0.03 + 0.015 * wave(t, 5.5), 0, 0], w);
  } },
  _mirar: { dur: 2.8, run(p, t, w, side) {
    p.add('head', [0, 0.36 * side, 0.03 * side], w);
    p.add('neck', [0, 0.1 * side, 0], w);
    p.add('spine', [0, 0.05 * side, 0], w);
    p.gaze[0] += 0.5 * side * w;
  } },
  _ladear: { dur: 2.4, run(p, t, w, side) {
    p.add('head', [0.02, 0, 0.16 * side], w);
    p.add('neck', [0, 0, 0.05 * side], w);
  } },
  _hombros: { dur: 2.2, run(p, t, w) {
    p.shoulders(0.13, w);
    p.add('chest', [-0.04, 0, 0], w);
    p.add('head', [-0.05, 0, 0], w);
    p.both({ u: [0.06, 0, 0.05] }, w, 'add');
  } },
  // Mascota de escritorio (modo flotante): al tocarla y al aterrizar tras una caída.
  _toque: { dur: 0.9, run(p, t, w) {
    const jolt = Math.max(0, 1 - t * 3);
    p.shoulders(0.16 * w);
    p.add('spine', [-0.06 - 0.05 * jolt, 0, 0], w);
    p.add('head', [-0.1 * jolt, 0, 0.04], w);
    p.both({ u: [-0.1, -0.2, -1.12], l: [0, -1.2, 0], c: 0.1, sp: 0.8 }, w * 0.7);
    p.lift += 0.025 * jolt * w;
  } },
  _aterrizar: { dur: 0.75, run(p, t, w, side, a) {
    if (a && a.lib && a.lib.has('jump_land')) {        // grabado: el impacto, flexionando, y se incorpora
      a._L.land.t = 0.12 + t * 1.1;
      applyLayer(p, a.lib, a._L.land, w, a.hipsY);
      return;
    }
    const k = Math.max(0, 1 - t / 0.75);
    p.lift -= 0.07 * k * w;
    for (const side of SIDES) {
      p.add(side + 'UpperLeg', [-0.45 * k, 0, 0], w);
      p.add(side + 'LowerLeg', [0.85 * k, 0, 0], w);
      p.add(side + 'Foot', [-0.35 * k, 0, 0], w);
    }
    p.add('spine', [0.2 * k, 0, 0], w);
    p.both({ u: [-0.2, 0, -0.9], l: [0, -0.4, 0], c: 0.2, sp: 0.5 }, w * k);
  } },
  // Toques (16 nov 2026): cada parte del cuerpo tiene su reacción y sube de tono si se repite (ver react()).
  _mimos: { dur: 2.6, run(p, t, w) {                  // le acarician la cabeza: la apoya en la mano y se mece
    const s = Math.sin(t * 3.2);
    p.add('head', [0.12, 0.05 * s, 0.16 + 0.05 * s], w);
    p.add('neck', [0.05, 0, 0.06], w);
    p.shoulders(0.12, w);
    p.both(ARMS.front, w * 0.8);
    p.add('hips', [0, 0.05 * s, 0.02 * s], w);
    p.add('spine', [0.03, -0.03 * s, 0], w);
  } },
  _cubrir: { dur: 2.2, run(p, t, w) {                 // se cubre el pecho y se gira un poco
    p.both({ u: [-0.42, -0.75, -1.05], l: [0, -2.1, 0], h: [0, 0, 0.1], c: 0.5 }, w);
    p.shoulders(0.16, w);
    p.add('spine', [0.06, 0.22, 0], w);
    p.add('chest', [0.05, 0.1, 0], w);
    p.add('head', [0.06, -0.3, 0], w);
    p.gaze[0] -= 0.3 * w;
  } },
  _falda: { dur: 2.2, run(p, t, w) {                  // se sujeta la falda y junta las rodillas
    p.both({ u: [-0.12, -0.95, -1.28], l: [0, -0.7, 0], h: [0.45, 0, 0.1], c: 0.2, sp: 0.6 }, w);   // manos delante de la cadera
    p.add('leftUpperLeg', [-0.08, 0, -0.07], w);
    p.add('rightUpperLeg', [-0.08, 0, 0.07], w);
    p.add('leftLowerLeg', [0.18, 0, 0], w);
    p.add('rightLowerLeg', [0.18, 0, 0], w);
    p.add('spine', [0.14, 0, 0], w);
    p.add('head', [0.1, 0, 0], w);
    p.lift -= 0.02 * w;
  } },
  _rechazo: { dur: 1.8, run(p, t, w) {                // «no, no»: la palma delante, moviéndola de lado, y niega
    p.arm('right', { u: [-0.6, -0.35, -0.95], l: [0, -1.5, 0], h: [-0.2, 0, 0], c: -0.05, sp: 1 }, w);
    p.add('rightLowerArm', [0, 0.3 * Math.sin(t * 11), 0], w);
    p.add('head', [0.04, 0.22 * Math.sin(t * 9), 0], w);
    p.add('spine', [-0.05, 0, 0], w);
    p.arm('left', ARMS.guard, w * 0.6);
  } },
  _pisoton: { dur: 1.1, run(p, t, w) {                // pisotón de enfado
    const up = Math.max(0, Math.sin(Math.min(1, t / 0.55) * Math.PI));
    p.add('rightUpperLeg', [-0.55 * up, 0, 0], w);
    p.add('rightLowerLeg', [0.8 * up, 0, 0], w);
    p.both(ARMS.fists, w);
    p.shoulders(0.1, w);
    p.add('head', [0.1, 0, 0], w);
    p.lift -= 0.015 * (1 - up) * w;
  } },
  _cosquillas: { dur: 2.2, run(p, t, w) {             // se retuerce de risa
    const s = Math.sin(t * 14);
    p.both({ u: [-0.15, -0.55, -1.18], l: [0, -1.6, 0], h: [0.2, 0, 0], c: 0.6 }, w);
    p.add('spine', [0.2 + 0.05 * s, 0.12 * s, 0.05 * s], w);
    p.add('chest', [0.08, 0.06 * s, 0], w);
    p.add('head', [0.1, -0.1 * s, 0.1], w);
    p.shoulders(0.12 + 0.05 * s, w);
    p.lift -= 0.03 * w;
  } },
  _saltito: { dur: 0.8, run(p, t, w) {                // respingo con saltito
    const k = Math.max(0, Math.sin(Math.min(1, t / 0.5) * Math.PI));
    p.lift += 0.06 * k * w;
    p.both(ARMS.startle, w);
    p.add('spine', [-0.08, 0, 0], w);
    for (const side of SIDES) { p.add(side + 'UpperLeg', [-0.25 * k, 0, 0], w); p.add(side + 'LowerLeg', [0.5 * k, 0, 0], w); }
  } },
  _mirar_mano: { dur: 2.0, run(p, t, w, side) {       // mira el brazo que le tocaron y lo levanta un poco
    const arm = side > 0 ? 'left' : 'right';
    p.arm(arm, { u: [-0.55, -0.1, -1.0], l: [0, -1.1, 0], h: [-0.8, 0, 0.1], c: 0.15, sp: 0.6 }, w);
    p.add('head', [0.2, 0.35 * side, 0.08 * side], w);
    p.gaze[0] += 0.45 * side * w; p.gaze[1] -= 0.25 * w;
  } },
};
// Lo mismo, a petición (17 nov 2026): «¿puedes bailar?» → [gesto:bailar] (prompt.py y companion/play.py).
for (const [pub, own] of [['bailar', '_bailar'], ['saltar', '_saltar'], ['girar', '_girar'], ['estirarse', '_estirarse'],
  ['hechizo', '_hechizo'], ['tararear', '_tararear'], ['beber', '_beber']]) GESTURES[pub] = GESTURES[own];
// «Duérmete» / «échate una siesta»: se duerme cuando termina de hablar (Avatar.sleepNow).
GESTURES.dormir = { dur: 0.1, run(p, t, w, side, a) { a.sleepAsked = true; } };
const IDLE_GESTURES = ['_mirar', '_ladear', '_hombros'];
// Pasatiempos: tras BORED_AFTER s sin que uses la app, de vez en cuando hace uno (los define GESTURES).
const HOBBIES = ['_bailar', '_saltar', '_girar', '_estirarse', '_hechizo', '_tararear', '_beber', '_curiosear'];
const BORED_AFTER = 50;
// Sueño: tras SLEEP_AFTER s sin usar la app se sienta sobre los talones y cabecea, o se tumba a echar la siesta (con
// «zzz»). Flotando, solo cabecea (tumbada no cabe en la ventana). Al volver a usar la app se despierta.
const SLEEP_AFTER = 180;
// Recostada (lean, 17 nov 2026): se sienta y se recuesta (la animación de levantarse del suelo, al revés, parada en
// LEAN.base), con una pierna estirada y la otra doblada, y mira una tablet o un móvil; con el rato le entra sueño,
// baja la pantalla al pecho y se duerme. Flotando lo hace en una esquina de la pantalla, con la espalda contra el
// borde (desktop/pet.js la lleva). Los valores se pueden tocar en vivo: (await import('/js/avatar.js')).LEAN.
export const LEAN = {
  base: 0.28,                      // instante de lay_up: recostada sobre la espalda con las rodillas dobladas
  watch: [70, 110],                // segundos mirando la pantalla antes de que le entre sueño
  drowsy: 25,                      // segundos cabeceando con la pantalla en la mano
  legOut: [0.75, 0, 0], kneeOut: [-1.6, 0, 0],    // la pierna estirada (izquierda), sumado a la animación
  legSide: -0.05,                  // la tendida apunta recta hacia delante (hacia su lado se acercaba a la cámara y parecía levantada)
  legReach: 0.88,                  // y no del todo estirada: la rodilla algo levantada (del todo, a 0,97, se veía rígida)
  // Apoyada sobre un codo (17 nov 2026, imagen de referencia del usuario): se gira sobre el costado que queda lejos de
  // la cámara y se apoya en ese codo; la pierna de ese lado, casi estirada en el suelo; la otra, con la rodilla alta y
  // el pie apoyado. Escrito para apoyarse en el costado IZQUIERDO; para el derecho se refleja.
  roll: { hips: [0, 0.1, -0.35], spine: [0, 0.08, -0.08], chest: [0, 0.04, -0.04] },
  prop: { u: [0.1, 0.3, -1.25], l: [0, -1.6, 0], h: [-0.3, 0, 0.2], hs: 'relax' },    // punto de partida del brazo de apoyo
  topLeg: { up: [0, 0, 0], lo: [0, 0, 0] },
  // Puntos del IK (en largos de pierna): la pantalla delante del pecho, las manos a sus lados, el codo de apoyo hacia el
  // suelo detrás, y el pie de la pierna alta junto a la rodilla de la otra.
  ik: { screenFwd: 0.3, screenUp: 0.22, handGap: 0.07, elbowOut: 0.32, elbowDown: 0.55, elbowBack: 0.12,
    footBeside: 0.12, footBack: -0.22, kneeUp: 1.0 },      // footBack < 0: el pie, por delante de la rodilla
  hold: { u: [-0.55, -0.45, -1.05], l: [0, -2.05, 0], h: [-0.45, 0, 0.1], hs: 'relax' },        // tablet con las dos manos
  phone: { u: [-0.6, -0.25, -1.0], l: [0, -2.25, 0], h: [-0.3, 0, 0.15], hs: 'relax' },         // móvil con la derecha
  rest: { u: [-0.45, -0.6, -1.15], l: [0, -1.25, 0], h: [0.2, 0, 0], hs: 'relax' },          // manos al pecho, dormida
  head: 0.32,                      // mirar hacia abajo, a la pantalla
  yaw: 1.15,                       // casi de perfil, como la referencia (se le ve la cara), con la espalda hacia la pared
  shift: 0.05,                     // flotando: centra el cuerpo recostado en la ventana (la espalda, cerca del borde)
  rise: 0.07,                      // flotando: todo el cuerpo algo más arriba, para que la pierna tendida no se corte (m)
  lift: 0.12,                      // sube la cadera (en alturas de cadera): la animación la deja a ~3 cm del suelo y
                                   // el trasero y el arranque de faldas y abrigos atravesaban el suelo (el hueso va a ~10 cm)
  // Posturas (17 nov 2026, «más posiciones… y animaciones en las que se queda dormida»). Cada una: instante de lay_up
  // despierta (base) y dormida (sleepBase), giro, si estira una pierna (extend) o planta los dos pies, dónde sostiene la
  // pantalla (screen: desde chest o head, en largos de pierna), dónde quedan pantalla y manos dormida (rest), y la
  // cabeza (head despierta, sleepHead dormida). float: false = no cabe en la ventana flotante.
  variants: {
    // Apoyada en un codo (la de la referencia). Al dormirse se desliza hasta quedar tumbada, con la pantalla al pecho.
    codo: { base: 0.28, sleepBase: 0.1, yaw: 1.15, roll: 1, extend: true, raise: 'low', screen: { from: 'chest', fwd: 0.3, up: 0.22 },
      rest: { from: 'chest', fwd: 0.1, up: 0.0 }, head: 0.32, sleepHead: [0.12, 0.22], float: true },
    // Sentada con la espalda contra el borde y las rodillas dobladas, la tablet sobre las rodillas. Al dormirse abraza
    // las rodillas y apoya la cabeza en ellas.
    rodillas: { base: 0.62, sleepBase: 0.62, yaw: 0.95, roll: 0, extend: false, raise: 'both', knees: 0.3,
      screen: { from: 'chest', fwd: 0.38, up: 0.06 }, rest: { from: 'knees', fwd: -0.1, up: 0.04 }, head: 0.35,
      sleepHead: [0.55, 0.1], float: true },
    // Tumbada boca arriba con las rodillas dobladas y el móvil sobre la cara. Al dormirse lo deja en el pecho y ladea
    // la cabeza. Tumbada a lo largo no cabe en la ventana flotante.
    tumbada: { base: 0.02, sleepBase: 0.0, yaw: 1.3, roll: 0, extend: false, raise: 'both', knees: 0.42,
      screen: { from: 'head', fwd: 0.04, up: 0.34 }, rest: { from: 'chest', fwd: 0.06, up: 0.05 }, head: -0.1,
      sleepHead: [0.0, 0.35], float: false, phoneBoth: true },
  },
};

// ---------------------------------------------------------------- mascota de escritorio (solo flotando)
// Actividades largas que pone desktop/pet.js: andar, que la lleven en brazos, caer, sentarse sobre una ventana y
// trabajar de espaldas en una ventana (las acciones «controlar»). run(p, t, w, a): w = cuánto está dentro.
const WORK_POSE = { u: [-0.5, -0.35, -1.12], l: [0, -1.35, 0], h: [0.25, 0, 0], c: 0.35 };     // manos al teclado
export const WALK_HZ = 0.95;             // ciclos de marcha por segundo (dos pasos por ciclo)
// Estilos grabados de 100STYLE (17 nov 2026): clips walk_<estilo> e idle_<estilo> (scripts/convertir_animaciones.py).
// Cada emoción anda y está de pie a su manera; sin emoción marcada, manda la personalidad (setTemper). Si un clip no
// está, se usa el de siempre (walk / idle, de Quaternius).
const EMO_STYLE = { feliz: 'alegre', emocionada: 'alegre', timida: 'timido', sonrojada: 'timido', triste: 'triste',
  molesta: 'enfado', pensativa: 'pensar', carinosa: 'ligero', enamorada: 'ligero', nerviosa: 'nervioso', asustada: 'nervioso' };
// Cuánto se marca el movimiento (clips.js, amp): algo más que la captura, como en el anime; más con alegría.
const EMO_AMP = { emocionada: 1.3, feliz: 1.2, carinosa: 1.15, enamorada: 1.15, triste: 0.9, pensativa: 1, timida: 1.05 };
const ACTIVITIES = {
  // Andar (16 nov 2026, revisado): ciclo de marcha de verdad. La pierna que avanza dobla la rodilla en el aire y
  // apoya primero el talón; la cadera gira con ella y cae un poco del lado que va en el aire; el tronco gira al
  // revés, la cabeza se queda estable y los brazos oscilan al contrario que las piernas, doblando el codo al ir
  // hacia delante. El cuerpo baja cuando las dos piernas están abiertas y sube al pasar sobre la de apoyo.
  walk(p, t, w, a) {
    // Con las animaciones grabadas (17 nov 2026), el ciclo de marcha de verdad, al ritmo de WALK_HZ.
    // Con 100STYLE, el estilo de andar va con la emoción y la personalidad (alegre, triste, tímido…).
    if (a.lib && a.lib.has('walk')) {
      a._styled(p, 'walk', w, a.walkPhase / (Math.PI * 2));
      // Estilo anime: pisa más hacia la línea del centro (rodillas juntas) y la cadera se mece algo más. La marcha
      // de Quaternius es de personaje de acción y lo necesita entero; las de 100STYLE (gente real), solo un toque.
      const s = Math.sin(a.walkPhase), k = a.lib.has('walk_neutro') ? 0.35 : 1;
      for (const [side, z] of [['left', 1], ['right', -1]]) {
        const r = p.r[side + 'UpperLeg'];
        r[2] = lerp(r[2], r[2] * 0.35 - 0.045 * z, w * k);
      }
      p.add('hips', [0, 0.05 * s, 0.03 * Math.cos(a.walkPhase)], w * k);
      p.add('spine', [0, -0.04 * s, 0], w * k);
      p.add('head', [-0.03, 0, 0], w);
      return;
    }
    const ph = a.walkPhase, s = Math.sin(ph), c = Math.cos(ph);
    const swingL = Math.max(0, c), swingR = Math.max(0, -c);              // qué pierna va por el aire
    p.both(ARMS.rest, w);
    p.add('leftUpperLeg', [-0.36 * s - 0.06 - 0.12 * swingL, 0, 0.02], w);
    p.add('rightUpperLeg', [0.36 * s - 0.06 - 0.12 * swingR, 0, -0.02], w);
    p.add('leftLowerLeg', [0.08 + 0.85 * Math.pow(swingL, 1.6) + 0.1 * Math.max(0, s) * (1 - swingL), 0, 0], w);
    p.add('rightLowerLeg', [0.08 + 0.85 * Math.pow(swingR, 1.6) + 0.1 * Math.max(0, -s) * (1 - swingR), 0, 0], w);
    // Tobillo: talón delante (punta arriba) al apoyar, punta abajo al despegar.
    p.add('leftFoot', [-0.18 * Math.max(0, s) + 0.32 * Math.max(0, -s) * (1 - swingL) + 0.15 * swingL, 0, 0], w);
    p.add('rightFoot', [-0.18 * Math.max(0, -s) + 0.32 * Math.max(0, s) * (1 - swingR) + 0.15 * swingR, 0, 0], w);
    p.add('hips', [0.02, 0.1 * s, 0.045 * c], w);
    p.shift += 0.012 * c * w;
    p.add('spine', [0.05, -0.08 * s, -0.03 * c], w);
    p.add('chest', [0, -0.06 * s, 0], w);
    p.add('neck', [0, 0.06 * s, 0.01 * c], w);
    p.add('head', [-0.02, 0.05 * s, 0.015 * c], w);
    p.add('leftUpperArm', [0.34 * s, 0, 0.04], w);                       // los brazos, al revés que las piernas
    p.add('rightUpperArm', [-0.34 * s, 0, -0.04], w);
    p.add('leftLowerArm', [0, -0.18 - 0.4 * Math.max(0, -s), 0], w);       // el codo se dobla al ir hacia delante
    p.add('rightLowerArm', [0, 0.18 + 0.4 * Math.max(0, s), 0], w);
    p.add('leftHand', [0.1 * s, 0, 0], w);
    p.add('rightHand', [-0.1 * s, 0, 0], w);
    p.curl.left = p.curl.left + (0.4 - p.curl.left) * w;
    p.curl.right = p.curl.right + (0.4 - p.curl.right) * w;
    p.lift += (0.006 - 0.016 * Math.abs(s)) * w;
  },
  carried(p, t, w) {                                  // en brazos: las piernas cuelgan y se balancean
    const sw = Math.sin(t * 2.3);
    p.both({ u: [-0.2, -0.05, -0.7], l: [0, -0.6, 0], h: [0, 0, 0.1], c: 0.25, sp: 0.4 }, w);
    p.shoulders(0.24, w);
    p.add('leftUpperLeg', [-0.2 + 0.2 * sw, 0, 0.14 + 0.05 * sw], w);
    p.add('rightUpperLeg', [-0.2 - 0.2 * sw, 0, -0.14 + 0.05 * sw], w);
    p.add('leftLowerLeg', [0.4 + 0.18 * sw, 0, 0], w);
    p.add('rightLowerLeg', [0.4 - 0.18 * sw, 0, 0], w);
    p.add('leftFoot', [0.35, 0, 0], w);
    p.add('rightFoot', [0.35, 0, 0], w);
    p.add('head', [0.05, 0, 0.06 * Math.sin(t * 1.1)], w);
    p.add('spine', [-0.03, 0, 0.03 * sw], w);
  },
  fall(p, t, w, a) {                                  // cayendo o de viaje por el aire
    const fl = Math.sin(t * 9);
    const clip = a.lib && a.lib.has('jump_loop');
    if (clip) { a._L.fall.t = t; applyLayer(p, a.lib, a._L.fall, w, a.hipsY); }
    p.both(ARMS.startle, w * (clip ? 0.6 : 1));
    p.both({ u: [0.1 * fl, 0, 0.35] }, w, 'add');
    if (!clip) for (const side of SIDES) {
      p.add(side + 'UpperLeg', [-0.5, 0, 0], w);
      p.add(side + 'LowerLeg', [0.9, 0, 0], w);
    }
    p.add('head', [-0.12, 0, 0], w);
  },
  // Sentada en el borde de una ventana, de costado (16 nov 2026: de frente, con los muslos hacia la cámara, la falda
  // y la chaqueta atravesaban las piernas). El cuerpo gira (yaw, ver _petTick), la cabeza se vuelve hacia ti, las
  // manos se apoyan en el borde, un poco por detrás, y las piernas cuelgan juntas columpiándose.
  sit(p, t, w, a) {
    const k = Math.sin(t * 1.3), side = (a.act.opts && a.act.opts.side) || 1;
    // Muslos algo caídos (no horizontales): con faldas y vestidos largos, la tela atravesaba las piernas.
    p.add('leftUpperLeg', [-1.02, 0, 0.02], w);
    p.add('rightUpperLeg', [-1.02, 0, -0.02], w);
    p.add('leftLowerLeg', [1.05 + 0.15 * k, 0, 0], w);
    p.add('rightLowerLeg', [1.05 - 0.15 * k, 0, 0], w);
    p.add('leftFoot', [0.35, 0, 0], w);
    p.add('rightFoot', [0.35, 0, 0], w);
    p.both({ u: [0.26, -0.06, -1.36], l: [0, -0.2, 0], h: [0.8, 0, 0.05], c: 0.3, sp: 0.4 }, w);  // manos en el borde, detrás
    p.add('spine', [-0.08, 0, 0], w);
    p.add('chest', [-0.03, 0, 0], w);
    p.add('neck', [0, -0.22 * side, 0], w);
    p.add('head', [0.02, -0.42 * side, 0.04 * side], w);
  },
  work(p, t, w, a) {                                  // de espaldas, trabajando en la ventana
    if (a.act.opts && a.act.opts.point) return pointerWork(p, t, w, a);
    const m = a.workW;
    p.add('spine', [0.1, 0, 0], w);
    p.add('head', [0.1, 0.12 * Math.sin(t * 0.8) * m.read, 0], w);
    p.both(WORK_POSE, w);
    const tap = (ph) => 0.28 * Math.max(0, Math.sin(t * 15 + ph));
    p.add('leftHand', [tap(0), 0, 0], w * m.type);
    p.add('rightHand', [tap(Math.PI * 0.8), 0, 0], w * m.type);
    p.add('leftLowerArm', [0, -0.08 * Math.sin(t * 7.5), 0], w * m.type);
    p.arm('right', { u: [-1.2, -0.05, -1.02], l: [0, -0.22, 0], h: [0, 0, 0], c: 0.85, ix: 1 }, w * Math.max(m.click, m.scroll));
    p.add('rightLowerArm', [0, -0.25 * Math.max(0, Math.sin(t * 6)), 0], w * m.click);       // toca la pantalla
    p.add('rightUpperArm', [0.2 * Math.sin(t * 3.2), 0, 0], w * m.scroll);                  // arrastra arriba y abajo
  },
};
const ACT_NAMES = Object.keys(ACTIVITIES);
const STANCES = ['stand', 'crouch', 'kneel', 'reach'];

// Trabajar «con la mano de puntero» (16 nov 2026, flotando): desktop/pet.js lleva la ventana para que su mano
// derecha quede sobre el punto que maneja cada paso; aquí la postura según dónde está ese punto en la pantalla:
// de pie, en cuclillas o de rodillas si está abajo, estirándose de puntillas si está arriba. De espaldas a ti.
// Con la mano: tocar (click), teclear (type), deslizar (scroll) o mirar (read).
function pointerWork(p, t, w, a) {
  const m = a.workW, s = a.stanceW, legLen = a.hipsY || 0.9;
  // Piernas y altura de la cadera de cada postura: con las animaciones grabadas, las de agacharse y arrodillarse
  // (17 nov 2026); si no, las escritas aquí.
  const C = a.lib && a.lib.has('crouch') ? 1 : 0, K = a.lib && a.lib.has('kneel_work') ? 1 : 0;
  if (C && s.crouch > 0.01) { a._L.crouch.t = a.act.t; applyLayer(p, a.lib, a._L.crouch, w * s.crouch, a.hipsY); }
  if (K && s.kneel > 0.01) { a._L.kneel.t = a.act.t; applyLayer(p, a.lib, a._L.kneel, w * s.kneel, a.hipsY); }
  const cr = s.crouch * (1 - C), kn = s.kneel * (1 - K);
  for (const [side, z] of [['left', 1], ['right', -1]]) {
    p.add(side + 'UpperLeg', [-1.85 * cr - 0.08 * kn, 0, 0.28 * z * cr + 0.06 * z * kn], w);
    p.add(side + 'LowerLeg', [2.35 * cr + 1.75 * kn, 0, 0], w);
    p.add(side + 'Foot', [-0.5 * cr + 0.75 * kn + 0.55 * s.reach, 0, 0], w);
  }
  p.lift += (-0.6 * cr - 0.5 * kn + 0.05 * s.reach) * legLen * w;
  p.add('spine', [0.28 * s.crouch + 0.1 * s.kneel - 0.1 * s.reach + 0.08 * s.stand, 0, 0], w);
  p.add('chest', [0.08 * s.crouch - 0.06 * s.reach, 0, 0], w);
  p.add('head', [0.12 - 0.35 * s.reach + 0.05 * s.crouch, 0.1 * Math.sin(t * 0.7) * m.read, 0], w);
  // Brazo izquierdo: apoyado en la rodilla agachada, o relajado / al teclado.
  p.arm('left', { u: [-0.7, -0.35, -1.05], l: [0, -1.0, 0], h: [0.3, 0, 0], c: 0.4 }, w * (s.crouch + s.kneel) * (1 - m.type));
  p.arm('left', ARMS.rest, w * (s.stand + s.reach) * (1 - m.type));
  p.arm('left', WORK_POSE, w * m.type);
  // Brazo derecho: estirado hacia el punto (más alto de puntillas, más bajo agachada), con el índice como puntero.
  const up = -1.25 - 0.95 * s.reach + 0.25 * (s.crouch + s.kneel);
  const point = { u: [up, -0.1, -0.95 + 0.2 * s.reach], l: [0, -0.12, 0], h: [0.1, 0, 0], c: 0.85, ix: 1 };
  p.arm('right', point, w * (1 - m.type));
  p.arm('right', WORK_POSE, w * m.type);
  const tap = Math.max(0, Math.sin(t * 7));
  p.add('rightLowerArm', [0, -0.35 * tap, 0], w * m.click);                      // toca
  p.add('rightHand', [0.35 * tap, 0, 0], w * m.click);
  p.add('rightUpperArm', [0.22 * Math.sin(t * 3.4), 0, 0], w * m.scroll);       // desliza arriba y abajo
  const key = (ph) => 0.3 * Math.max(0, Math.sin(t * 15 + ph));
  p.add('leftHand', [key(0), 0, 0], w * m.type);
  p.add('rightHand', [key(2.4), 0, 0], w * m.type);
}

export class Avatar {
  constructor(canvas) {
    this.canvas = canvas;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(FOV, 1, 0.1, 30);
    this.camera.position.set(0, 1.35, 1.4);

    const key = new THREE.DirectionalLight(0xffffff, Math.PI * 0.85);
    key.position.set(0.6, 1.2, 1.5);
    this.scene.add(key, new THREE.AmbientLight(0xffffff, 0.55));

    // Cámara libre (16 nov 2026, petición del usuario): gira del todo en horizontal y en vertical, se desplaza
    // con el botón derecho y la rueda acerca o aleja hacia el punto que señala el ratón.
    this.controls = new OrbitControls(this.camera, canvas);
    Object.assign(this.controls, { enablePan: true, screenSpacePanning: true, enableDamping: true, dampingFactor: 0.08,
      minDistance: 0.25, maxDistance: 12, zoomToCursor: true, rotateSpeed: 0.9 });
    this.fullBody = false;
    this.controls.addEventListener('start', () => (this.userMoved = true));
    this.userMoved = false;

    this.lookTarget = new THREE.Object3D();
    this.scene.add(this.lookTarget);
    this.effects = new Effects(this.scene, this.camera);

    this.clock = new THREE.Clock();
    this.pose = new Pose();
    this.vrm = null;
    this.orb = null;                // el personaje neutro (esfera), cuando no hay VRM
    this.isV0 = false;
    this.bones = {};
    this.fingers = { left: [], right: [] };
    this.headY = 1.4;
    this.head = null;               // medidas de la cabeza del modelo, para colocar los efectos

    this.state = 'idle';
    this.stateW = { idle: 1, listening: 0, thinking: 0, speaking: 0 };
    this.emotion = 'neutral';
    this.emoW = Object.fromEntries(Object.keys(EMOTIONS).map((k) => [k, k === 'neutral' ? 1 : 0]));
    this.emoAge = 0;                // segundos desde que cambió de emoción
    this.face = Object.fromEntries(FACE_KEYS.map((k) => [k, 0]));
    this.emoHead = [0, 0, 0];
    this.emoGaze = [0, 0];
    this.mouth = Object.fromEntries(VISEMES.map((k) => [k, 0]));
    this.voice = 0;                 // envolvente de la voz, 0..1
    this.voiceSlow = 0;
    this.beat = 0;                  // golpe de voz: sube en cada énfasis
    this.lip = new Lipsync();       // qué sonido se dice (lipsync.js)
    this.gestures = [];
    this.talk = { name: null, side: 'right', w: 0, until: 0, next: 0, last: null };
    this.weight = { cur: 0.5, goal: 0.5, next: 4 };          // sobre qué pierna descansa (-1..1)
    this.fidget = { next: 7 };
    this.thinkArm = 0;
    this.tilt = 1;
    this.blink = { next: 2, t: -1, twice: false, last: -9, slow: 1 };
    this.saccade = { next: 1.5, x: 0, y: 0, away: false };
    this.nod = { next: 3 };
    this.spring = {};               // estado de los muelles de cada hueso: { x: [3], v: [3] }
    this.headFollow = [0, 0];       // la cabeza acompaña, con retraso, a los ojos cuando miran lejos
    this.breath = { phase: 0, inhaleT: 9, silent: 0 };          // respiración; inhaleT: segundos desde que tomó aire
    this.prevState = 'idle';
    this._q = new THREE.Quaternion();
    this._q2 = new THREE.Quaternion();
    this._e = new THREE.Euler();
    this._v = new THREE.Vector3();
    this._headInfo = { eyes: new THREE.Vector3(), cheeks: [new THREE.Vector3(), new THREE.Vector3()], unit: 0.11, facing: 1 };
    this.floating = false;
    // Mascota de escritorio: actividad en curso, giro del cuerpo y el ratón (en px de la ventana, puede estar fuera).
    this.act = { name: 'none', opts: {}, t: 0 };
    this.actW = Object.fromEntries(ACT_NAMES.map((k) => [k, 0]));
    this.workW = { read: 1, type: 0, click: 0, scroll: 0 };
    this.stance = 'stand';
    this.stanceW = { stand: 1, crouch: 0, kneel: 0, reach: 0 };
    this._handS = null;
    this.workMode = 'read';
    this.workUntil = 0;
    this.walkPhase = 0;
    this.yaw = 0;
    this.baseYaw = 0;
    this.cursor = null;
    this.follow = false;
    this.followW = 0;
    this.flashEmo = null;
    this.hipsY = 0.9;
    this.probe = null;              // punto (px de la ventana) donde se mira si hay avatar o fondo transparente
    this.probeHit = false;
    this._px = new Uint8Array(4);
    // Animaciones grabadas (clips.js): se cargan una vez y valen para cualquier VRM. Sin ellas (archivo que falta o
    // roto), todo sigue como antes, con la animación escrita en código.
    this._lib = null;
    this.clipT = 0;                // reloj de las animaciones de base (va un poco más rápido o lento, con ruido)
    this.clipOn = true;             // se pueden apagar desde la consola para comparar (window.companion.avatar)
    this.hobbyOn = true;            // se entretiene sola si no usas la app (Ajustes › Tú y tu personaje)
    this.lastActive = 0;
    this.hobby = { next: 0, last: null };
    this.spinYaw = 0;               // la vuelta del pasatiempo _girar
    this.sleep = { mode: null, t: 0, w: 0, waking: 0, side: 1 };   // nod (cabecear) | nap (siesta)
    this.sleepYaw = 0;
    this.sleepShift = 0;            // recostada en una esquina: se acerca al borde de la pantalla
    this.device = null;             // la tablet o el móvil (props.js)
    this.sleepEyes = 0;             // ojos cerrados por el sueño (0..1)
    this.sleepAsked = false;        // se lo pediste: se duerme al terminar de hablar
    this.onSleep = null;            // main.js: avisa a la mascota (no pasea mientras duerme)
    this.faceX = null;              // cara de un pasatiempo en este cuadro (bostezo, sonrisa al bailar…)
    this.styleW = { neutro: 1 };     // estilos de andar / estar de pie (100STYLE) y su peso
    this.ikOn = true;               // pies en el suelo (_legIK); también se puede apagar desde la consola
    this.ik = null;
    this._L = {
      // El reposo grabado es de personaje de acción (piernas muy abiertas): de las piernas se toma solo una parte,
      // y el resto lo pone el reposo de siempre, con los pies juntos.
      idle: new Layer('idle', { mask: { legs: 0.35, hips: 0.6, arms: 0.8 } }),
      talk: new Layer('talk', { mask: { legs: 0.35, hips: 0.6, arms: 0.55, fingers: 0.6 } }),
      walk: new Layer('walk', { mask: { arms: 0.75 } }),
      fall: new Layer('jump_loop', { mask: { arms: 0.4, fingers: 0 } }),
      crouch: new Layer('crouch', { mask: { arms: 0, head: 0, fingers: 0 } }),
      kneel: new Layer('kneel_work', { mask: { arms: 0, head: 0, fingers: 0 } }),
      fold: new Layer('fold_arms', { mask: { legs: 0, hips: 0, spine: 0.4, head: 0 } }),
      land: new Layer('jump_land', { mask: { arms: 0.5, head: 0.5 } }),
    };
    this.clipsReady = ClipLib.load().then((lib) => (this._lib = lib)).catch((e) => console.warn(e.message));

    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
  }

  // ---------------------------------------------------------------- carga
  async load(url) {
    const loader = new GLTFLoader();
    loader.register((parser) => new VRMLoaderPlugin(parser));
    const gltf = await loader.loadAsync(url);
    const vrm = gltf.userData.vrm;
    if (!vrm) throw new Error('El archivo no es un VRM');
    VRMUtils.removeUnnecessaryVertices(gltf.scene);
    if (VRMUtils.combineSkeletons) VRMUtils.combineSkeletons(gltf.scene);
    VRMUtils.rotateVRM0(vrm);
    vrm.scene.traverse((o) => (o.frustumCulled = false));

    this.unload();
    this.vrm = vrm;
    this.isV0 = vrm.meta?.metaVersion === '0';
    const node = (name) => vrm.humanoid.getNormalizedBoneNode(name);
    for (const b of BONES) if (node(b)) this.bones[b] = node(b);
    for (const side of SIDES) {
      for (const f of FINGERS) {
        const segs = f === 'Thumb' ? ['Metacarpal', 'Proximal', 'Distal'] : ['Proximal', 'Intermediate', 'Distal'];
        segs.forEach((seg, i) => { const n = node(side + f + seg); if (n) this.fingers[side].push({ node: n, name: f, thumb: f === 'Thumb', i, little: f === 'Little', bone: side + f + seg }); });
      }
    }
    this.hipsRest = this.bones.hips ? this.bones.hips.position.clone() : null;
    this.baseYaw = vrm.scene.rotation.y;          // π en los VRM 0.x (rotateVRM0), 0 en los 1.0
    this.spring = {};
    if (vrm.lookAt) vrm.lookAt.target = this.lookTarget;
    this.scene.add(vrm.scene);
    this._measureHead(vrm);
    this._measureLegs(vrm);
    this._legColliders(vrm);          // faldas y vestidos que no atraviesan las piernas
    this.parts = addParts(vrm);      // cara por partes (face.js): solo en los modelos de VRoid
    this.partW = {};
    this.micro = new Micro();

    // Alturas de la cabeza y la cadera en la pose en T, antes de poner ninguna postura: medidas después, con el
    // modelo anterior recostado o dormido, salían mal (cadera a 0,18 m) y descuadraban todas las animaciones.
    vrm.scene.updateMatrixWorld(true);
    const head = node('head');
    this.headY = head ? head.getWorldPosition(this._v).y : 1.4;
    this.hipsY = this.bones.hips ? this.bones.hips.getWorldPosition(this._v).y : this.headY * 0.62;
    // Un modelo nuevo empieza despierto y de pie.
    if (this.sleep.mode && this.onSleep) this.onSleep(false);
    Object.assign(this.sleep, { mode: null, w: 0, waking: 0, rest: 0, t: 0 });
    this.sleepYaw = this.sleepShift = this.sleepRise = 0;
    vrm.scene.position.set(0, 0, 0);
    if (this.device) this.device.show = 0;

    this._buildPose(this.clock.elapsedTime, 0);
    this._applyPose(0);             // pose de reposo antes del primer cuadro (evita ver la «T»)
    vrm.update(0);
    vrm.scene.updateMatrixWorld(true);
    this.userMoved = false;
    this.frame();
    return vrm.meta;
  }

  // Dónde están los ojos y las mejillas respecto al hueso de la cabeza (en la pose en T, recién cargado).
  // Con eso los efectos se colocan bien en cualquier modelo, tenga la cabeza del tamaño que tenga.
  _measureHead(vrm) {
    vrm.scene.updateMatrixWorld(true);
    const head = vrm.humanoid.getNormalizedBoneNode('head');
    if (!head) { this.head = null; return; }
    const pos = head.getWorldPosition(new THREE.Vector3());
    const inv = head.getWorldQuaternion(new THREE.Quaternion()).invert();
    const eye = (name) => { const n = vrm.humanoid.getRawBoneNode(name); return n ? n.getWorldPosition(new THREE.Vector3()) : null; };
    let l = eye('leftEye'), r = eye('rightEye');
    const scale = clamp(pos.y / 1.4, 0.4, 2.5);
    if (!l || !r || l.y - pos.y < 0.01) {               // sin huesos de ojos: proporciones típicas
      l = pos.clone().add(new THREE.Vector3(0.032, 0.07, 0.07).multiplyScalar(scale));
      r = pos.clone().add(new THREE.Vector3(-0.032, 0.07, 0.07).multiplyScalar(scale));
    }
    const mid = l.clone().add(r).multiplyScalar(0.5);
    const unit = clamp((mid.y - pos.y) * 1.6, 0.07 * scale, 0.17 * scale);
    const half = Math.max(Math.abs(l.x - r.x) / 2, 0.2 * unit);
    const local = (v) => v.sub(pos).applyQuaternion(inv);
    this.head = {
      node: head, unit,
      eyes: local(mid.clone()),
      forward: new THREE.Vector3(0, 0, 1).applyQuaternion(inv),
      cheeks: [1, -1].map((s) => local(this._onSkin(vrm, new THREE.Vector3(mid.x + s * (half + 0.2 * unit), mid.y - 0.42 * unit, mid.z + 0.08 * unit), s))),
    };
    this.effects.attachBlush(head, this.head);       // el rubor, pegado a la cara (effects.js)
  }

  // El estilo que toca ahora: el de la emoción o, si no la hay, el de la personalidad.
  _styleNow() {
    const e = EMO_STYLE[this.emotion];
    if (e) return e;
    const { shy, sharp } = this.temper || { shy: 0.3, sharp: 0.3 };
    if (shy > 0.6 && shy >= sharp) return 'timido';
    if (sharp > 0.6) return 'orgullo';
    return 'neutro';
  }

  // Pesos de cada estilo, que se funden despacio al cambiar (sin saltos aunque cambie la emoción a media marcha).
  _styleStep(dt) {
    const want = this._styleNow(), sw = this.styleW;
    if (!(want in sw)) sw[want] = 0;
    for (const k in sw) {
      sw[k] = dt ? lerp(sw[k], k === want ? 1 : 0, damp(2.2, dt)) : (k === want ? 1 : 0);
      if (sw[k] < 0.004 && k !== want) delete sw[k];
    }
  }

  // Pone el andar o el estar de pie con los estilos mezclados. walk: `at` = ciclos de marcha (todos los clips
  // empiezan cuando el pie izquierdo va más adelantado, así que van a la par); idle: `at` = segundos.
  _styled(p, kind, w, at) {
    const lib = this.lib;
    if (!lib || w < 0.005) return;
    const amp = EMO_AMP[this.emotion] ?? 1.1;
    let total = 0;
    for (const [style, sw] of Object.entries(this.styleW)) {
      if (sw < 0.004) continue;
      const name = lib.has(kind + '_' + style) ? kind + '_' + style : kind;
      const L = this._styleLayer(name, kind);
      const c = lib.clips[name];
      L.t = kind === 'walk' ? (((at % c.cycles) + c.cycles) % c.cycles) * (c.dur / c.cycles) : at;
      L.amp = amp;
      total += sw;
      applyLayer(p, lib, L, w * (sw / total), this.hipsY);
    }
  }

  _styleLayer(name, kind) {
    const c = this._SL || (this._SL = {});
    if (c[name]) return c[name];
    if (name === kind) return (c[name] = this._L[kind]);              // los de Quaternius, con sus máscaras
    // Los de 100STYLE: el cuerpo entero (los pies los clava _legIK); de pie, los brazos los comparte con lo demás.
    const mask = kind === 'idle' ? { legs: 0.85, hips: 0.85, arms: 0.8 } : { arms: 0.9 };
    // Triste: la persona grabada se encorva y hunde la cabeza del todo (~57°), y la emoción ya la baja; con las dos,
    // de frente solo se veía la coronilla. Se toma una parte, para que se le vea la cara.
    if (name.endsWith('_triste')) { mask.head = 0.25; mask.spine = 0.4; }
    return (c[name] = new Layer(name, { mask }));
  }

  // Ritmo, paso y velocidad de la marcha con los estilos de ahora (de los clips; 0 = los de siempre).
  gait() {
    const lib = this.lib, g = this._gait || (this._gait = { hz: 0, stride: 0, speed: 0 });
    g.hz = g.stride = g.speed = 0;
    if (!lib || !lib.has('walk')) return g;
    let tot = 0;
    for (const [style, sw] of Object.entries(this.styleW)) {
      const c = lib.clips['walk_' + style] || lib.clips.walk;
      g.hz += sw * (c.cycles ? c.cycles / c.dur : 0);
      g.stride += sw * c.stride;
      g.speed += sw * (c.speed || 0);
      tot += sw;
    }
    if (tot > 0) { g.hz /= tot; g.stride /= tot; g.speed /= tot; }
    if (!lib.clips.walk_neutro) g.hz = 0;                              // sin 100STYLE, el ritmo de siempre
    return g;
  }

  // Faldas y vestidos (17 nov 2026): muchos VRM no traen colisionadores en las piernas, así que al sentarse,
  // recostarse, andar o levantar la rodilla la falda (una cadena de físicas colgada de la cadera) atraviesa los
  // muslos o se queda tiesa enseñando lo de debajo. Se añaden cápsulas en muslos y espinillas (en los huesos de
  // verdad, que son los que usan las físicas) a toda cadena de físicas que quede por debajo del pecho: la falda se
  // apoya en la pierna y cae por encima de la rodilla. Se mide en la pose en T, recién cargado.
  _legColliders(vrm) {
    const sb = vrm.springBoneManager, hum = vrm.humanoid;
    if (!sb || !hum || !sb.joints || !sb.joints.size) return;
    vrm.scene.updateMatrixWorld(true);
    const raw = (n) => hum.getRawBoneNode(n);
    const chestNode = raw('upperChest') || raw('chest') || raw('spine');
    if (!chestNode) return;
    const chestY = chestNode.getWorldPosition(new THREE.Vector3()).y;
    const colliders = [];
    for (const side of SIDES) {
      const up = raw(side + 'UpperLeg'), lo = raw(side + 'LowerLeg'), ft = raw(side + 'Foot');
      if (!up || !lo || !ft) continue;
      const pU = up.getWorldPosition(new THREE.Vector3()), pL = lo.getWorldPosition(new THREE.Vector3()), pF = ft.getWorldPosition(new THREE.Vector3());
      const thigh = pU.distanceTo(pL), shin = pL.distanceTo(pF);
      // Cápsula del muslo (un poco más gruesa arriba, como la pierna) y de la espinilla, en el espacio del hueso.
      for (const [bone, from, to, r] of [[up, pU, pL, 0.2 * thigh], [lo, pL, pF, 0.15 * shin]]) {
        const shape = new VRMSpringBoneColliderShapeCapsule({
          offset: new THREE.Vector3(), tail: bone.worldToLocal(to.clone()), radius: r,
        });
        const c = new VRMSpringBoneCollider(shape);
        c.name = 'companion_leg';
        bone.add(c);
        colliders.push(c);
      }
    }
    if (!colliders.length) return;
    // El suelo: tumbada o recostada, la falda y el pelo largo caen sobre él en vez de atravesarlo.
    const floor = new VRMSpringBoneCollider(new VRMSpringBoneColliderShapePlane({ offset: new THREE.Vector3(0, 0.005, 0), normal: new THREE.Vector3(0, 1, 0) }));
    floor.name = 'companion_floor';
    vrm.scene.add(floor);
    colliders.push(floor);
    const group = { colliders, name: 'companion_legs' };
    let n = 0;
    for (const j of sb.joints) {
      if (j.bone.getWorldPosition(new THREE.Vector3()).y > chestY) {
        j.colliderGroups.push({ colliders: [floor], name: 'companion_floor' });   // lo de arriba (pelo), solo el suelo
        continue;
      }
      if (j.colliderGroups.includes(group)) continue;
      j.colliderGroups.push(group);
      n++;
    }
    sb._isSortedJointsDirty = true;                              // las dependencias cambiaron: que las reordene
    this.legColliders = n;
  }

  // Piernas en la pose en T (recién cargado): dónde está el suelo (la altura del tobillo de pie) y cuánto miden, en
  // el espacio del modelo (vrm.scene). Con eso _legIK deja los pies en el suelo, sea cual sea el modelo.
  _measureLegs(vrm) {
    vrm.scene.updateMatrixWorld(true);
    const b = this.bones, inv = vrm.scene.matrixWorld.clone().invert();
    const loc = (n) => n.getWorldPosition(new THREE.Vector3()).applyMatrix4(inv);
    this.ik = null;
    if (!SIDES.every((s) => b[s + 'UpperLeg'] && b[s + 'LowerLeg'] && b[s + 'Foot'])) return;
    const leg = {};
    for (const s of SIDES) {
      const h = loc(b[s + 'UpperLeg']), k = loc(b[s + 'LowerLeg']), a = loc(b[s + 'Foot']);
      leg[s] = { ground: a.y, len: h.distanceTo(k) + k.distanceTo(a), x: a.x };
    }
    this.ik = { leg, len: (leg.left.len + leg.right.len) / 2, feet: {}, plant: 0, walk: 0, lean: 0, inv: new THREE.Matrix4(),
      v: [0, 1, 2, 3, 4, 5, 6].map(() => new THREE.Vector3()), q: [0, 1, 2, 3, 4].map(() => new THREE.Quaternion()) };
  }

  // Pies en el suelo (IK de dos huesos, 17 nov 2026). Al mezclar animaciones y mover la cadera (el peso, respirar,
  // hablar) los pies resbalan o se hunden. De pie, cada pie se queda CLAVADO donde está; si la animación lo lleva
  // lejos de ahí, da un pasito corto hasta el sitio nuevo (de uno en uno, como una persona al cambiar el peso).
  // Andando solo se corrige la altura: no se hunde en el suelo ni flota en el apoyo. Se hace sobre los huesos ya
  // girados (después de los muelles), sin estado salvo dónde está clavado cada pie; el pie conserva su giro.
  _legIK(dt) {
    const ik = this.ik, vrm = this.vrm;
    if (!ik || !vrm || !this.ikOn) return;
    const plant = ik.plant, walk = ik.walk, lean = ik.lean || 0;
    if (plant < 0.02 && walk < 0.02 && lean < 0.02) { ik.feet = {}; return; }
    const [H, K, A, T, u, v2, n] = ik.v, [q0, q1, q2, q3, q4] = ik.q;
    this.bones.hips.updateWorldMatrix(true, true);
    ik.inv.copy(vrm.scene.matrixWorld).invert();
    const fwd = new THREE.Vector3(0, 0, this.isV0 ? -1 : 1).applyQuaternion(vrm.scene.getWorldQuaternion(q4));
    const len = ik.len;
    for (const side of SIDES) {
      const up = this.bones[side + 'UpperLeg'], lo = this.bones[side + 'LowerLeg'], ft = this.bones[side + 'Foot'];
      const L = ik.leg[side];
      up.getWorldPosition(H); lo.getWorldPosition(K); ft.getWorldPosition(A);
      // Dónde quiere la animación el tobillo, en el espacio del modelo.
      const al = T.copy(A).applyMatrix4(ik.inv);
      const want = new THREE.Vector3(al.x, L.ground + Math.max(0, al.y - L.ground - 0.025 * len), al.z);
      let st = ik.feet[side];
      if (!st || !dt || plant < 0.05) st = ik.feet[side] = { lock: want.clone(), from: null, to: null, u: 1 };
      const goal = new THREE.Vector3();
      if (st.u < 1) {                                   // dando un paso
        st.u = Math.min(1, st.u + dt / 0.3);
        const e = st.u * st.u * (3 - 2 * st.u);
        st.to.lerp(want, 0.25);                          // el destino sigue a la animación mientras pisa
        goal.lerpVectors(st.from, st.to, e);
        goal.y += Math.sin(Math.PI * st.u) * 0.045 * len;
        if (st.u >= 1) st.lock.copy(st.to);
      } else {
        const other = ik.feet[side === 'left' ? 'right' : 'left'];
        const dx = want.x - st.lock.x, dz = want.z - st.lock.z;
        if (Math.hypot(dx, dz) > 0.085 * len && !(other && other.u < 1)) {
          st.from = st.lock.clone(); st.to = want.clone(); st.u = 0;
        }
        goal.copy(st.lock);
        goal.y = want.y;
      }
      // Objetivo del tobillo: clavado (de pie) o solo a ras de suelo (andando), según el peso de cada cosa.
      const walkGoal = new THREE.Vector3(al.x, al.y < L.ground + 0.02 * len ? L.ground : al.y, al.z);
      const target = al.clone().lerp(walkGoal, walk).lerp(goal, plant);
      // Recostada (LEAN, 17 nov 2026): la pierna estirada (izquierda) se apoya en el suelo a todo su largo, en la
      // dirección en que ya apunta; la doblada pisa con el pie donde está, a ras de suelo. Sin esto la estirada
      // quedaba colgando por debajo del suelo.
      if (lean > 0.02) {
        const hl = H.clone().applyMatrix4(ik.inv);
        const lg = new THREE.Vector3();
        if (side === ik.leanDown) {
          // Hacia delante del cuerpo y algo hacia su lado (no hacia donde la dejaba la animación: en algunos modelos
          // quedaba cruzada bajo la otra pierna). En el espacio del modelo mira a +Z (a -Z los VRM 0.x).
          const h = Math.max(0, hl.y - L.ground), reach = LEAN.legReach * (H.distanceTo(K) + K.distanceTo(A));
          const f = this.isV0 ? -1 : 1;
          const flat = new THREE.Vector3(LEAN.legSide * f * (side === 'left' ? 1 : -1), 0, f).normalize();
          flat.multiplyScalar(Math.sqrt(Math.max(0, reach * reach - h * h)));
          lg.set(hl.x + flat.x, L.ground, hl.z + flat.z);
        } else lg.set(al.x, L.ground + 0.01 * len, al.z);
        target.lerp(lg, lean);
      }
      T.copy(target).applyMatrix4(vrm.scene.matrixWorld);
      if (T.distanceToSquared(A) < 1e-8) continue;
      // Dos huesos: primero la rodilla (para que cadera-tobillo midan lo que hace falta), luego el muslo apunta.
      const a = H.distanceTo(K), b = K.distanceTo(A);
      const d = clamp(H.distanceTo(T), Math.abs(a - b) + 1e-4, a + b - 1e-4);
      u.subVectors(H, K); v2.subVectors(A, K);
      const cur = u.angleTo(v2), wantK = Math.acos(clamp((a * a + b * b - d * d) / (2 * a * b), -1, 1));
      n.crossVectors(u, v2);
      let ang = wantK - cur;
      if (n.lengthSq() < 1e-10 * a * b) {               // pierna recta: la rodilla se dobla hacia delante
        n.crossVectors(v2, fwd).negate();
        ang = cur - wantK;
      }
      n.normalize();
      const footW = ft.getWorldQuaternion(q0);           // el pie conserva su giro
      const footLocal = q4.copy(ft.quaternion);          // (recostada, la pierna tendida: el pie sigue a la pierna)
      const loW = lo.getWorldQuaternion(q1);
      const upW = up.getWorldQuaternion(q2);
      const Rk = q3.setFromAxisAngle(n, ang);
      loW.premultiply(Rk);
      A.sub(K).applyQuaternion(Rk).add(K);               // dónde queda el tobillo tras doblar la rodilla
      const Rh = new THREE.Quaternion().setFromUnitVectors(u.subVectors(A, H).normalize(), v2.subVectors(T, H).normalize());
      upW.premultiply(Rh);
      loW.premultiply(Rh);
      const parW = up.parent.getWorldQuaternion(new THREE.Quaternion());
      up.quaternion.copy(parW.invert().multiply(upW));
      lo.quaternion.copy(upW.clone().invert().multiply(loW));
      if (lean > 0.5 && side === ik.leanDown) ft.quaternion.copy(footLocal);
      else ft.quaternion.copy(loW.clone().invert().multiply(footW));
      up.updateWorldMatrix(false, true);
    }
  }

  // IK de dos huesos general (brazo o pierna): lleva el extremo de `end` a T (mundo); `pole` (mundo, opcional) dice
  // hacia dónde se dobla el codo o la rodilla; `w` mezcla con lo que había. No toca el giro local de `end`.
  _ikChain(up, lo, end, T, pole, w = 1) {
    if (w < 0.01) return;
    const H = up.getWorldPosition(new THREE.Vector3()), K = lo.getWorldPosition(new THREE.Vector3());
    const A = end.getWorldPosition(new THREE.Vector3());
    const q0u = up.quaternion.clone(), q0l = lo.quaternion.clone();
    const a = H.distanceTo(K), b = K.distanceTo(A);
    const d = clamp(H.distanceTo(T), Math.abs(a - b) + 1e-4, a + b - 1e-4);
    const u = new THREE.Vector3().subVectors(H, K), v = new THREE.Vector3().subVectors(A, K);
    const cur = u.angleTo(v), want = Math.acos(clamp((a * a + b * b - d * d) / (2 * a * b), -1, 1));
    const n = new THREE.Vector3().crossVectors(u, v);
    if (n.lengthSq() < 1e-12) n.set(1, 0, 0);
    n.normalize();
    const upW = up.getWorldQuaternion(new THREE.Quaternion()), loW = lo.getWorldQuaternion(new THREE.Quaternion());
    const Rk = new THREE.Quaternion().setFromAxisAngle(n, want - cur);
    loW.premultiply(Rk);
    A.sub(K).applyQuaternion(Rk).add(K);
    const Rh = new THREE.Quaternion().setFromUnitVectors(A.clone().sub(H).normalize(), T.clone().sub(H).normalize());
    upW.premultiply(Rh); loW.premultiply(Rh);
    if (pole) {                                                   // gira la cadena sobre el eje H→T hacia el polo
      const axis = T.clone().sub(H).normalize();
      const k2 = K.clone().sub(H).applyQuaternion(Rh);
      const kp = k2.clone().sub(axis.clone().multiplyScalar(k2.dot(axis)));
      const pp = pole.clone().sub(H); pp.sub(axis.clone().multiplyScalar(pp.dot(axis)));
      if (kp.lengthSq() > 1e-10 && pp.lengthSq() > 1e-10) {
        let ang = kp.angleTo(pp);
        if (new THREE.Vector3().crossVectors(kp, pp).dot(axis) < 0) ang = -ang;
        const Rp = new THREE.Quaternion().setFromAxisAngle(axis, ang);
        upW.premultiply(Rp); loW.premultiply(Rp);
      }
    }
    const parW = up.parent.getWorldQuaternion(new THREE.Quaternion());
    up.quaternion.copy(parW.invert().multiply(upW));
    lo.quaternion.copy(upW.clone().invert().multiply(loW));
    if (w < 0.999) { up.quaternion.slerpQuaternions(q0u, up.quaternion.clone(), w); lo.quaternion.slerpQuaternions(q0l, lo.quaternion.clone(), w); }
    up.updateWorldMatrix(false, true);
  }

  // Recostada sobre un codo (LEAN.ik): las manos a la pantalla, el codo de apoyo hacia el suelo detrás, y el pie de
  // la pierna alta junto a la rodilla de la otra (la de abajo ya la apoyó _legIK).
  _leanIK() {
    const ik = this.ik, sl = this.sleep, vrm = this.vrm;
    if (!ik || !vrm || !this.ikOn || sl.mode !== 'lean' || !(ik.lean > 0.02)) return;
    const b = this.bones, L = LEAN.ik, Lg = ik.len, w = ik.lean, V = ik.leanV || LEAN.variants.codo;
    const low = sl.side > 0 ? 'right' : 'left', top = low === 'left' ? 'right' : 'left';
    const f = this.isV0 ? -1 : 1;
    const sq = vrm.scene.getWorldQuaternion(new THREE.Quaternion());
    const fwd = new THREE.Vector3(0, 0, f).applyQuaternion(sq), up = new THREE.Vector3(0, 1, 0);
    const leftDir = new THREE.Vector3(f, 0, 0).applyQuaternion(sq);
    const lat = (s) => leftDir.clone().multiplyScalar(s === 'left' ? 1 : -1);
    const pos = (n) => n.getWorldPosition(new THREE.Vector3());
    b.hips.updateWorldMatrix(true, true);
    const ground = (s) => vrm.scene.localToWorld(new THREE.Vector3(0, ik.leg[s].ground, 0)).y;
    // Piernas con la rodilla alta y el pie en el suelo: en «codo», la de apoyo, delante de la rodilla de la tendida;
    // en las demás, las dos, a `knees` largos de pierna por delante de la cadera.
    const raise = V.raise === 'both' ? [low, top] : V.raise === 'low' ? [low] : [];
    for (const s of raise) {
      let foot;
      if (V.extend) {
        foot = pos(b[top + 'LowerLeg']).addScaledVector(lat(low), L.footBeside * Lg).addScaledVector(fwd, -L.footBack * Lg);
      } else {
        foot = pos(b[s + 'UpperLeg']).addScaledVector(fwd, V.knees * Lg * 1.4).addScaledVector(lat(s), 0.06 * Lg);
      }
      foot.y = ground(s);
      const hip = pos(b[s + 'UpperLeg']);
      const kneePole = hip.clone().lerp(foot, 0.5).addScaledVector(up, L.kneeUp * Lg).addScaledVector(fwd, 0.3 * Lg);
      this._ikChain(b[s + 'UpperLeg'], b[s + 'LowerLeg'], b[s + 'Foot'], foot, kneePole, w);
    }
    // Manos a la pantalla; dormida, pantalla y manos a su sitio de descanso (pecho, o rodillas abrazadas).
    if (!b.leftHand || !b.rightHand) return;
    const rest = clamp(sl.rest || 0);
    const from = (o) => (o.from === 'head' ? pos(b.head) : o.from === 'knees'
      ? pos(b.leftLowerLeg).add(pos(b.rightLowerLeg)).multiplyScalar(0.5) : pos(b.upperChest || b.chest));
    const awakeP = from(V.screen).addScaledVector(fwd, V.screen.fwd * Lg).addScaledVector(up, V.screen.up * Lg);
    const restP = from(V.rest).addScaledVector(fwd, V.rest.fwd * Lg).addScaledVector(up, V.rest.up * Lg);
    const screen = awakeP.lerp(restP, rest);
    this._restPoint = restP;
    const phone = this.device && this.device.kind === 'phone' && !V.phoneBoth;
    for (const s of [top, low]) {
      if (phone && s === low) continue;                          // con el móvil, la de abajo solo apoya
      const hand = screen.clone().addScaledVector(lat(s), (V.rest.from === 'knees' ? 0.12 * rest + L.handGap * (1 - rest) : L.handGap) * Lg);
      const sh = pos(b[s + 'UpperArm']);
      const pole = s === low && V.extend
        ? sh.clone().addScaledVector(lat(s), L.elbowOut * Lg).addScaledVector(up, -L.elbowDown * Lg).addScaledVector(fwd, -L.elbowBack * Lg)
        : sh.clone().addScaledVector(lat(s), L.elbowOut * Lg).addScaledVector(up, -0.3 * Lg);
      this._ikChain(b[s + 'UpperArm'], b[s + 'LowerArm'], b[s + 'Hand'], hand, pole, w);
    }
  }

  // El punto de la mejilla sobre la piel (17 nov 2026): el cálculo desde los ojos cae por dentro de la cara (los huesos
  // de los ojos están en el centro del globo), y el rubor pegado a la cara quedaba escondido. Se lanza un rayo desde
  // delante (algo hacia fuera, como mira la mejilla) contra las mallas con expresiones (la cara; el pelo no tiene), en la
  // pose en T. Si no da con nada, se queda el punto calculado.
  _onSkin(vrm, p, side) {
    const faces = [];
    vrm.scene.traverse((o) => { if (o.isMesh && o.morphTargetInfluences && o.morphTargetInfluences.length) faces.push(o); });
    if (!faces.length) return p;
    const dir = new THREE.Vector3(-side * 0.35, 0, -1).normalize();
    const ray = new THREE.Raycaster(p.clone().addScaledVector(dir, -0.3), dir, 0, 0.6);
    const hit = ray.intersectObjects(faces, false)[0];
    return hit ? hit.point.clone() : p;
  }

  _headNow() {
    const h = this.head;
    if (!h) return null;
    const out = this._headInfo;
    const pos = h.node.getWorldPosition(this._v);
    const q = h.node.getWorldQuaternion(this._q2);
    out.unit = h.unit;
    out.eyes.copy(h.eyes).applyQuaternion(q).add(pos);
    out.cheeks.forEach((c, i) => c.copy(h.cheeks[i]).applyQuaternion(q).add(pos));
    const toCam = this._e2 || (this._e2 = new THREE.Vector3());
    toCam.copy(this.camera.position).sub(out.eyes).normalize();
    const fwd = this._e3 || (this._e3 = new THREE.Vector3());
    out.facing = clamp(fwd.copy(h.forward).applyQuaternion(q).dot(toCam) * 2.2 - 0.5);
    return out;
  }

  // El personaje neutro: una esfera con cara (orb.js). No es un VRM, pero recibe las mismas órdenes.
  loadOrb() {
    this.unload();
    this.orb = new Orb();
    this.scene.add(this.orb.group);
    this.headY = ORB_Y - 0.06;
    this.hipsY = ORB_Y - 0.28;
    this.userMoved = false;
    this.frame();
  }

  get loaded() { return !!this.vrm || !!this.orb; }
  get lib() { return this.clipOn ? this._lib : null; }

  unload() {
    this.effects.clear();
    this.effects.detachBlush();
    if (this.orb) {
      this.scene.remove(this.orb.group);
      this.orb.dispose();
      this.orb = null;
    }
    this.bones = {};
    this.fingers = { left: [], right: [] };
    this.head = null;
    if (!this.vrm) return;
    this.scene.remove(this.vrm.scene);
    VRMUtils.deepDispose(this.vrm.scene);
    this.vrm = null;
  }

  // Modo flotante: el botón izquierdo mueve la ventana (main.js), así que la cámara se gira con el derecho y se
  // desplaza con el central; la rueda cambia el tamaño de la ventana (Ctrl + rueda: zoom, ver zoom()).
  setFloating(on) {
    this.floating = on;
    this.controls.mouseButtons = on ? { LEFT: null, MIDDLE: THREE.MOUSE.PAN, RIGHT: THREE.MOUSE.ROTATE }
      : { LEFT: THREE.MOUSE.ROTATE, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
    this.controls.enableZoom = !on;
    this.probeHit = false;
    this.userMoved = false;
    this.frame();
  }

  // Flotando: encuadre de cuerpo entero (sin el degradado de abajo) o de medio cuerpo.
  setFullBody(on) {
    this.fullBody = !!on;
    if (!this.userMoved) this.frame();
  }

  // Acercar (factor < 1) o alejar la cámara hacia lo que mira, sin pasar de los límites.
  zoom(factor) {
    const c = this.controls;
    const offset = this.camera.position.clone().sub(c.target);
    const d = clamp(offset.length() * factor, c.minDistance, c.maxDistance);
    this.camera.position.copy(c.target).add(offset.setLength(d));
    this.userMoved = true;
    c.update();
  }

  // Doble clic: vuelve al encuadre de siempre.
  resetView() {
    this.userMoved = false;
    this.frame();
  }

  // ¿Hay avatar bajo ese punto de la ventana, o es fondo transparente? Se lee del último cuadro dibujado.
  _readProbe() {
    this.probeHit = false;
    if (!this.probe) return;
    const dpr = this.renderer.getPixelRatio();
    const x = Math.round(this.probe.x * dpr), y = Math.round(this.canvas.height - this.probe.y * dpr);
    if (x < 0 || y < 0 || x >= this.canvas.width || y >= this.canvas.height) return;
    const gl = this.renderer.getContext();
    gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, this._px);
    this.probeHit = this._px[3] > 24;
  }

  // Encuadre: de la cintura hacia arriba, con sitio a los lados para los gestos y arriba para los efectos.
  frame() {
    const aspect = this.camera.aspect;
    const tan = Math.tan(THREE.MathUtils.degToRad(FOV / 2));
    const dist = clamp(Math.max(0.95, 0.95 / aspect) / (2 * tan), 1.6, 4.2);
    const visible = 2 * dist * tan;
    // La esfera va centrada; un personaje con cuerpo, encuadrado de la cintura a la cabeza. Flotando sin el
    // degradado, entero: de los pies a un poco por encima de la cabeza.
    if (((this.floating && this.fullBody) || this._sheetFull) && !this.orb) {
      const top = this.headY + 0.2;
      const full = clamp(Math.max(top * 1.08, 0.8 / aspect) / (2 * tan), 1.2, 9);
      this.controls.target.set(0, top / 2, 0);
      this.camera.position.set(0, top / 2 + 0.02, full);
      this.controls.update();
      return;
    }
    const y = this.orb ? ORB_Y - 0.03 : this.headY + 0.24 - 0.4 * visible;
    this.controls.target.set(0, y, 0);
    this.camera.position.set(0, y + 0.03, dist);
    this.controls.update();
  }

  resize() {
    const el = this.canvas.parentElement;
    const w = el.clientWidth || 1, h = el.clientHeight || 1;
    this.renderer.setSize(w, h, false);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    if (!this.userMoved) this.frame();
  }

  // ---------------------------------------------------------------- órdenes
  setState(state) {
    if (!(state in this.stateW) || state === this.state) return;
    this.state = state;
    if (state !== 'idle') this.wake();
    if (state === 'listening') this.tilt = Math.random() < 0.5 ? -1 : 1;
    if (state === 'speaking') this.breath.inhaleT = 0;          // toma aire antes de hablar
    if (Math.random() < 0.45) this._blinkSoon();                // al cambiar de actitud se suele parpadear
  }
  setEmotion(name) {
    if (!(name in EMOTIONS) || name === this.emotion) return;
    this.emotion = name;
    this.emoAge = 0;
    this.effects.setFeeling(name);
    if (Math.random() < 0.5) this._blinkSoon();
  }
  // Parpadeo en cuanto se pueda (no dos casi seguidos).
  _blinkSoon() {
    const b = this.blink, t = this.clock.elapsedTime;
    if (b.t < 0 && t - b.last > 0.6) b.next = t;
  }
  // Usas la app (hablas, escribes, mueves el ratón por la ventana): deja el pasatiempo y vuelve a esperar.
  wake() {
    this.lastActive = this.clock.elapsedTime;
    this.endHobby();
    const sl = this.sleep;
    if (sl.mode && !sl.waking) { sl.waking = 0.001; sl.t = 0; }
  }
  // Dormirse ya: mode = 'nod' (sentada, cabeceando) o 'nap' (tumbada); sin mode, el que toque.
  // lean (recostada con la tablet o el móvil, lo normal), nod (sentada cabeceando), nap (tumbada). Flotando, recostada
  // en una esquina: la mascota la lleva primero (restAt la deja empezar). drowsy: empieza ya con sueño («duérmete»).
  sleepNow(mode, drowsy = false) {
    const sl = this.sleep;
    if (sl.mode && !sl.waking) return;
    if (!this.vrm) return;                                       // la esfera no se tumba
    const r = Math.random();
    mode = mode || (this.floating || r < 0.7 ? 'lean' : r < 0.85 ? 'nod' : 'nap');
    if (this.floating && mode === 'nap') mode = 'lean';
    Object.assign(sl, { mode, t: 0, waking: 0, side: Math.random() < 0.5 ? -1 : 1,
      ready: !(mode === 'lean' && this.floating && this.restWait), watch: drowsy ? 0 : rand(LEAN.watch[0], LEAN.watch[1]) });
    if (mode === 'lean') {
      const names = Object.keys(LEAN.variants).filter((v) => !this.floating || LEAN.variants[v].float);
      sl.variant = pick(names, this._lastVariant);
      this._lastVariant = sl.variant;
      this._takeDevice(sl.variant === 'tumbada' || Math.random() < 0.5 ? (sl.variant === 'rodillas' ? 'tablet' : 'phone') : 'tablet');
    }
    this.endHobby();
    this.gestures = this.gestures.filter((g) => !g.name.startsWith('_'));
    if (this.onSleep) this.onSleep(true, mode);
  }
  get sleeping() { return !!this.sleep.mode; }
  // Flotando: ya está en la esquina; side = +1 si la pared queda a su derecha (mira a la izquierda), -1 al revés.
  restAt(side) {
    const sl = this.sleep;
    if (sl.mode !== 'lean' || sl.ready) return;
    Object.assign(sl, { ready: true, t: 0, side: side || sl.side });
  }
  _takeDevice(kind) {
    if (this.device && this.device.kind !== kind) { this.device.dispose(); this.device = null; }
    if (!this.device) { this.device = new Device(kind); this.scene.add(this.device.group); }
    this.device.on = 1;
    this.device.show = 0;
  }
  // Coloca la tablet o el móvil (después de vrm.update, con los huesos ya en su sitio): entre las manos o en la
  // derecha, con la pantalla hacia su cara; dormida, sobre el pecho, mirando hacia arriba.
  _placeDevice(t) {
    const d = this.device;
    if (!d) return;
    const sl = this.sleep;
    d.group.visible = d.show > 0.02 && !!this.vrm;
    if (!d.group.visible) return;
    const b = this.bones, V = this._dv || (this._dv = [0, 1, 2, 3, 4].map(() => new THREE.Vector3()));
    const scale = clamp(this.headY / 1.4, 0.5, 2) * d.show;
    d.group.scale.setScalar(Math.max(0.001, scale));
    const head = b.head.getWorldPosition(V[0]);
    const hold = V[1];
    const hand = this.sleep.side > 0 ? 'left' : 'right';          // la mano que da a la cámara (la de arriba)
    if (d.kind === 'tablet') hold.addVectors(b.leftHand.getWorldPosition(V[2]), b.rightHand.getWorldPosition(V[3])).multiplyScalar(0.5);
    else {
      // El móvil, en la palma: algo más allá de la muñeca, hacia los nudillos del dedo medio.
      b[hand + 'Hand'].getWorldPosition(hold);
      const mid = this.fingers[hand].find((f) => f.name === 'Middle' && f.i === 0);
      if (mid) hold.lerp(mid.node.getWorldPosition(V[2]), 0.75);
    }
    const chest = this._restPoint && sl.mode === 'lean' ? V[2].copy(this._restPoint) : (b.upperChest || b.chest).getWorldPosition(V[2]);
    const restK = clamp(sl.rest || 0);
    const pos = V[3].lerpVectors(hold, chest, restK);
    pos.y += 0.02 * scale * (1 - restK);
    d.group.position.copy(pos);
    // Mirando a la cara; dormida, tumbada sobre el pecho (la pantalla hacia arriba).
    const look = V[4].copy(head).lerp(V[0].copy(pos).add(new THREE.Vector3(0, 1, 0)), restK);
    d.group.lookAt(look);
    d.on = lerp(d.on, sl.mode && (sl.rest || 0) < 0.5 ? 1 : 0, 0.05);
    d.update(t);
  }
  endHobby() {
    for (const g of this.gestures) {
      if (!HOBBIES.includes(g.name)) continue;
      const d = GESTURES[g.name].dur;
      g.t = Math.max(g.t, d * 0.8);                            // sale con suavidad (el final del gesto)
    }
    this.hobby.next = Math.max(this.hobby.next, this.clock.elapsedTime + 12);
  }
  // ---------------------------------------------------------------- sueño (17 nov 2026)
  // nod: sentada sobre los talones (seiza), manos en el regazo; la cabeza cae despacio y se levanta de golpe, como
  // quien se duerme sentada; con el tiempo se queda dormida del todo. nap: se tumba boca arriba de lado a la cámara
  // (la animación grabada de levantarse, al revés) y respira despacio. En los dos, «zzz» y ojos cerrados.
  _sleepPose(p, t, dt) {
    const sl = this.sleep;
    if (!sl.mode) {
      this.sleepEyes = lerp(this.sleepEyes, 0, damp(6, dt)); this.sleepYaw = lerp(this.sleepYaw, 0, damp(4, dt));
      if (this.ik) this.ik.lean = 0;
      return;
    }
    sl.t += dt;
    const lay = this._hob('lay_up', {});
    const nap = sl.mode === 'nap' && lay;
    if (sl.mode === 'lean') return this._leanPose(p, t, dt, lay);
    // Peso: entra en ~1 s; al despertar, la siesta se levanta con la animación (1,5 s) y luego suelta.
    if (sl.waking) {
      sl.waking += dt;
      const outT = nap ? 1.6 : 0.9;
      sl.w = clamp(1 - Math.max(0, sl.waking - (nap ? 1.3 : 0)) / (outT - (nap ? 1.3 : 0)));
      if (sl.waking >= outT) {
        Object.assign(sl, { mode: null, w: 0, waking: 0 });
        if (this.onSleep) this.onSleep(false);
        if (Math.random() < 0.6) this.playGesture('_estirarse');          // se despereza al despertar
        return;
      }
    } else sl.w = clamp(sl.t / (nap ? 0.25 : 1.1));
    const w = ease(sl.w);
    if (nap) {
      const dur = this.lib.dur('lay_up');
      // Tumbarse: la animación de levantarse al revés (1,9 s); dormida, el primer cuadro; al despertar, hacia delante.
      lay.t = sl.waking ? Math.min(dur, sl.waking * 1.15) : Math.max(0, dur - sl.t * 0.8);
      applyLayer(p, this.lib, lay, w, this.hipsY);
      this.sleepYaw = lerp(this.sleepYaw, sl.side * Math.PI / 2 * (sl.waking ? 1 - clamp(sl.waking / 1.4) : 1), damp(3, dt));
      const br = Math.sin(t * 1.6);                                // respira despacio
      p.add('chest', [0.03 * br, 0, 0], w);
      p.add('head', [0.05, -0.35 * sl.side, 0], w * clamp(sl.t - 1.5));   // gira la cara hacia la cámara
      p.both({ c: 0.4 }, w, 'add');
    } else {
      // Seiza: muslos hacia delante, rodillas dobladas del todo, empeines en el suelo; la cadera sobre los talones.
      const L = 1;
      p.set('leftUpperLeg', [-1.32, 0, 0.1], w); p.set('rightUpperLeg', [-1.32, 0, -0.1], w);
      p.set('leftLowerLeg', [2.55, 0, 0], w); p.set('rightLowerLeg', [2.55, 0, 0], w);
      p.set('leftFoot', [0.95, 0, 0], w); p.set('rightFoot', [0.95, 0, 0], w);
      p.set('hips', [0.06, 0, 0], w); p.set('spine', [0.06, 0, 0], w);
      p.lift = lerp(p.lift, -(this.hipsY * 0.76) * L, w);
      p.fwd = lerp(p.fwd, -0.06 * this.hipsY, w);
      p.both({ u: [-0.2, -0.38, -1.22], l: [0, -1.0, 0], h: [0.25, 0, 0], hs: 'relax' }, w);    // manos en el regazo
      // Cabecear: la cabeza cae despacio (3–5 s) y se levanta de golpe; tras ~40 s se queda dormida del todo.
      const deep = clamp((sl.t - 40) / 15);
      const cyc = 4.2 + 1.3 * noise(Math.floor(sl.t / 4.2), 77);
      const u = (sl.t % cyc) / cyc;
      const droop = deep > 0.99 ? 1 : u < 0.88 ? ease(u / 0.88) : 1 - ease((u - 0.88) / 0.12);
      const nodW = Math.max(droop, deep);
      p.add('head', [0.42 * nodW, 0, 0.08 * nodW * sl.side], w);
      p.add('neck', [0.18 * nodW, 0, 0], w);
      p.add('spine', [0.05 * nodW, 0, 0.03 * Math.sin(t * 0.7)], w);
      this.sleepYaw = lerp(this.sleepYaw, 0, damp(4, dt));
    }
    // Ojos: cerrados (cabeceando, se entreabren cuando la cabeza se levanta).
    const open = sl.mode === 'nod' && !nap ? clamp(1 - (p.r.head[0] - 0.05) * 4) * clamp(1 - (sl.t - 40) / 15) : 0;
    this.sleepEyes = lerp(this.sleepEyes, (sl.waking ? 1 - clamp(sl.waking * 2) : 1) * (1 - 0.6 * open), damp(5, dt));
    this.faceX = { parts: { mthSmall: 0.25, brwSorrow: 0.15 }, preset: { relaxed: 0.4 }, w };
    // «zzz» que suben de la cabeza cuando ya duerme.
    if (!sl.waking && sl.t > (nap ? 2.5 : 6) && (!this._zzzAt || this.clock.elapsedTime > this._zzzAt)) {
      this.effects.burst('zzz', 1, rand(0.8, 1.15));
      this._zzzAt = this.clock.elapsedTime + rand(1.3, 2.1);
    }
  }

  // Recostada con la tablet o el móvil (LEAN): se sienta (lay_up al revés hasta LEAN.base), mira la pantalla, cabecea
  // y se duerme con la pantalla en el pecho. Al despertar guarda la pantalla y se levanta (lay_up hacia delante).
  _leanPose(p, t, dt, lay) {
    const sl = this.sleep, d = this.device, L = LEAN;
    if (!lay) { sl.mode = 'nod'; return; }
    if (!sl.ready) {                                            // flotando: aún va de camino a la esquina
      if (d) d.show = 0;
      if (sl.waking) {                                          // la despertaste antes de llegar
        Object.assign(sl, { mode: null, w: 0, waking: 0, rest: 0 });
        if (this.onSleep) this.onSleep(false);
      }
      return;
    }
    const V = L.variants[sl.variant] || L.variants.codo;
    const dur = this.lib.dur('lay_up'), down = (dur - V.base) / 0.8;   // segundos en sentarse (~1,5 s)
    let w = 1, k = 0;                                           // k: cuánto manda la postura propia (piernas, brazos)
    if (sl.waking) {
      sl.waking += dt;
      // Guarda la pantalla (0,4 s) y se levanta con la animación hacia delante; al final suelta.
      lay.t = Math.min(dur, (sl.layT ?? V.base) + Math.max(0, sl.waking - 0.4) * 1.1);
      k = 1 - clamp(sl.waking / 0.5);
      w = 1 - clamp((sl.waking - 1.2) / 0.5);
      if (d) d.show = Math.max(0, 1 - sl.waking * 3);
      if (sl.waking >= 1.7) {
        Object.assign(sl, { mode: null, w: 0, waking: 0, rest: 0 });
        if (d) d.show = 0;
        if (this.onSleep) this.onSleep(false);
        if (Math.random() < 0.6) this.playGesture('_estirarse');
        return;
      }
    } else {
      // Se sienta (lay_up al revés hasta su base) y, dormida, se va a la base de dormir (se desliza, se acurruca…).
      const baseNow = lerp(V.base, V.sleepBase, ease(clamp(sl.rest || 0)));
      lay.t = Math.max(baseNow, dur - sl.t * 0.8);
      sl.layT = lay.t;
      w = clamp(sl.t / 0.3);
      k = clamp((sl.t - down) / 0.8);
      if (d) d.show = clamp((sl.t - down - 0.3) / 0.5);
    }
    sl.w = w;
    if (this.ik) this.ik.lean = w * k;                           // pies en el suelo (_legIK)
    applyLayer(p, this.lib, lay, w, this.hipsY);
    // La animación de base no es simétrica (la cadera viene algo girada): para el otro lado, reflejada.
    if (sl.side < 0) mirrorPose(p);
    p.lift += L.lift * this.hipsY * w * k;
    sl.vName = sl.variant;
    // Fases: mirando (watch) → con sueño (drowsy: cabecea, la pantalla baja) → dormida (rest: la pantalla al pecho).
    const since = sl.t - down;
    const sleepy = clamp((since - sl.watch) / L.drowsy);
    sl.rest = sl.waking ? sl.rest : clamp((since - sl.watch - L.drowsy) / 4);
    const asleep = sl.rest;
    // Apoyada sobre el costado que queda lejos de la cámara (sl.side > 0: mira a la izquierda y se apoya en el
    // derecho). `low` = ese lado; `top` = el que da a la cámara. Lo escrito para el izquierdo se refleja con `m`.
    const low = sl.side > 0 ? 'right' : 'left', top = low === 'left' ? 'right' : 'left', ms = low === 'left' ? 1 : -1;
    const m = (v) => [v[0], v[1] * ms, v[2] * ms];
    // Piernas (como en la referencia): la que da a la cámara, tendida en el suelo (la apoya _legIK); la del costado de
    // apoyo, con la rodilla alta y el pie detrás de la otra (la coloca _leanIK).
    if (this.ik) { this.ik.leanDown = V.extend ? top : null; this.ik.leanV = V; }
    for (const b of ['hips', 'spine', 'chest']) p.add(b, m(L.roll[b]).map((v) => v * V.roll), w * k);
    if (V.extend) {
      p.add(top + 'UpperLeg', m(L.legOut).map((v, i) => (i ? -v : v)), w * k);
      // La rodilla, algo doblada hacia delante (fija, no sumada a la animación: según la base salía doblada hacia atrás).
      p.set(top + 'LowerLeg', [0.4, 0, 0], w * k);
    } else {
      // Las dos rodillas dobladas hacia arriba (el IK planta los pies).
      p.set('leftLowerLeg', [1.6, 0, 0], w * k); p.set('rightLowerLeg', [1.6, 0, 0], w * k);
    }
    // Brazos: el de abajo, con el codo en el suelo y la mano en la pantalla; el otro, sosteniéndola. Dormida, las
    // manos al pecho. Con el móvil, solo la mano de arriba lo sostiene.
    const phone = d && d.kind === 'phone';
    p.arm(low, L.prop, w * k * (phone ? 1 : 1 - asleep));
    p.arm(top, phone ? L.phone : L.hold, w * k * (1 - asleep));
    p.arm(top, L.rest, w * k * asleep);
    if (!phone) p.arm(low, { ...L.prop, l: [0, -1.4, 0], h: [0.2, 0, 0] }, w * k * asleep);
    // Pulgar que pasa cosas en el móvil o toca la tablet de vez en cuando.
    if (!asleep && Math.sin(t * 2.2) > 0.7) p.add(top + 'Hand', [0.08 * Math.sin(t * 14), 0, 0], w * k * (1 - sleepy));
    // Cabeza: mira la pantalla; con sueño, cae y se levanta (cabecea); dormida, ladeada.
    const cyc = 4.5 + 1.2 * noise(Math.floor(since / 4.5), 91), u = (Math.max(0, since) % cyc) / cyc;
    const droop = (u < 0.85 ? ease(u / 0.85) : 1 - ease((u - 0.85) / 0.15)) * sleepy * (1 - asleep);
    p.add('head', [V.head * (1 - asleep) + 0.35 * droop + V.sleepHead[0] * asleep, 0, V.sleepHead[1] * asleep * -sl.side], w * k);
    p.add('neck', [0.12 * droop + 0.3 * V.sleepHead[0] * asleep, 0, 0.08 * asleep * -sl.side], w * k);
    p.add('chest', [0.025 * Math.sin(t * (asleep ? 1.5 : 2.2)), 0, 0], w);   // respira (más lento dormida)
    // De perfil, con la espalda hacia la pared (flotando, más cerca del borde).
    this.sleepYaw = lerp(this.sleepYaw, -sl.side * V.yaw * (sl.waking ? 1 - clamp(sl.waking / 1.6) : 1), damp(3, dt));
    this.sleepShift = lerp(this.sleepShift, this.floating ? sl.side * L.shift * w : 0, damp(3, dt));
    // Flotando, el suelo es el borde de abajo de la ventana: la pierna tendida quedaba cortada por la mitad.
    this.sleepRise = lerp(this.sleepRise || 0, this.floating ? L.rise * w : 0, damp(3, dt));
    // Cara y ojos: mirando, atenta (alguna sonrisa con lo que ve); con sueño, parpadeos lentos; dormida, cerrados.
    const smile = !sleepy && Math.sin(t * 0.37) > 0.85 ? 0.5 : 0;
    this.faceX = asleep > 0.3 ? { parts: { mthSmall: 0.25, brwSorrow: 0.15 }, preset: { relaxed: 0.4 }, w }
      : { parts: { mthFun: 0.25 + smile, eyeFun: 0.15 + 0.3 * smile }, preset: { happy: 0.15 + 0.3 * smile }, w };
    const lids = Math.max(asleep, sleepy * (0.45 + 0.45 * droop));
    this.sleepEyes = lerp(this.sleepEyes, (sl.waking ? 1 - clamp(sl.waking * 2) : 1) * lids, damp(5, dt));
    if (!sl.waking && asleep > 0.6 && (!this._zzzAt || this.clock.elapsedTime > this._zzzAt)) {
      this.effects.burst('zzz', 1, rand(0.8, 1.15));
      this._zzzAt = this.clock.elapsedTime + rand(1.3, 2.1);
    }
  }

  // Capa de una animación grabada para un pasatiempo (null si no está).
  _hob(name, mask = {}) {
    if (!this.lib || !this.lib.has(name)) return null;
    const c = this._HL || (this._HL = {});
    return c[name] || (c[name] = new Layer(name, { mask }));
  }
  // Notas musicales de vez en cuando (tararear, bailar).
  _notes(t, every) {
    const now = this.clock.elapsedTime;
    if (!this._noteAt || now > this._noteAt) { this.effects.burst('note', 1, rand(0.8, 1.1)); this._noteAt = now + every * rand(0.7, 1.3); }
  }
  playGesture(name, side = Math.random() < 0.5 ? -1 : 1) {
    if (!(name in GESTURES)) return;
    this.gestures = this.gestures.filter((g) => g.name !== name);
    this.gestures.push({ name, t: 0, side });
  }
  // ---------------------------------------------------------------- mascota de escritorio
  // name: none | walk | carried | fall | sit | work · opts: { dir: -1|1 (walk), side: -1|1 (work: lado de la ventana) }
  setActivity(name, opts = {}) {
    if (name !== 'none' && !(name in ACTIVITIES)) return;
    if (name === this.act.name && JSON.stringify(opts) === JSON.stringify(this.act.opts)) return;
    if (this.act.name === 'fall' && name !== 'fall') this.playGesture('_aterrizar');
    if (name !== 'none') this.endHobby();                       // pasea, la llevas, trabaja…: deja lo que hacía
    this.act = { name, opts, t: 0 };
    if (name === 'work') this.setWorkMode('read', 0);
    if (name !== 'work' || !opts.point) this.stance = 'stand';
  }
  // Qué hace con las manos mientras trabaja: read | type | click | scroll (durante `secs`, luego vuelve a leer).
  setWorkMode(mode, secs = 2.6) {
    if (!(mode in this.workW)) mode = 'read';
    this.workMode = mode;
    this.workUntil = secs ? this.clock.elapsedTime + secs : 0;
  }
  // Postura mientras trabaja con la mano de puntero: stand | crouch | kneel | reach.
  setStance(name) { this.stance = STANCES.includes(name) ? name : 'stand'; }
  setCursor(x, y) { this.cursor = { x, y, at: this.clock.elapsedTime }; }
  setFollow(on) { this.follow = !!on; }
  // Una emoción un momento y vuelta a la de antes (si nadie la cambió mientras).
  flash(emotion, secs = 2.2) {
    const back = this.flashEmo ? this.flashEmo.back : this.emotion;
    this.setEmotion(emotion);
    this.flashEmo = { back, emotion, until: this.clock.elapsedTime + secs };
  }
  // Su carácter, para reaccionar a los toques y a cómo la miras (de la personalidad elegida: timidez, calidez y
  // «genio» = lo que tenga de ironía u opiniones firmes). main.js lo pone al cargar y al cambiar de personalidad.
  setTemper({ shy = 0.3, warm = 0.7, sharp = 0.3 } = {}) { this.temper = { shy, warm, sharp }; }

  // Al tocarla o al pasar el ratón. zone = hover | head | chest | belly | hips | legs | feet | arms | hands | body.
  // Tocar la misma parte varias veces seguidas (menos de 2,2 s entre toques) sube de tono: nivel 1, 2 y 3.
  // Devuelve { zone, level, n } (main.js lo usa para que, a veces, lo comente en voz alta).
  react(zone, side = 1) {
    const r = Math.random(), t = this.clock.elapsedTime;
    if (zone === 'hover') {
      if (r < 0.35) this.playGesture('saludar');
      this.flash('feliz', 1.8);
      return { zone, level: 0, n: 0 };
    }
    const tc = this.touch || (this.touch = { zone: null, n: 0, last: -9 });
    tc.n = tc.zone === zone && t - tc.last < 2.2 ? tc.n + 1 : 1;
    tc.zone = zone; tc.last = t;
    const level = tc.n <= 2 ? 1 : tc.n <= 5 ? 2 : 3;
    const { shy, warm, sharp } = this.temper || { shy: 0.3, warm: 0.7, sharp: 0.3 };
    const tsun = sharp > 0.6 && shy > 0.4;                // orgullosa y tímida: lo niega aunque le guste
    const fx = this.effects;
    const go = (emo, secs, ...gestures) => { this.flash(emo, secs); for (const g of gestures) this.playGesture(g, side); };
    if (zone === 'head') {
      if (level === 1) { go(tsun ? 'sonrojada' : 'feliz', 2, r < 0.5 ? 'risita' : '_mimos'); fx.burst('heart', 1 + Math.round(warm), 0.9); }
      else if (level === 2) { go(tsun ? 'sonrojada' : 'carinosa', 3, '_mimos'); fx.burst('heart', 3, 1.1); fx.burst('spark', 2); }
      else {
        go(tsun ? 'sonrojada' : 'enamorada', 4, tsun ? 'negar' : '_mimos');
        fx.burst('heart', 4 + Math.round(4 * warm), 1.9);                 // corazones grandes
        if (tsun) fx.burst('puff', 2, 1.1);
      }
    } else if (zone === 'chest' || zone === 'hips') {
      const cover = zone === 'chest' ? '_cubrir' : '_falda';
      if (level === 1) { go('sorprendida', 1.8, '_saltito', cover); fx.burst('exclaim', 1, 1.2); }
      else if (level === 2) { go('sonrojada', 3, cover, 'negar'); fx.burst('puff', 2, 1); fx.burst('drop', 1); }
      else if (sharp > 0.45 || shy < 0.35) { go('molesta', 3.5, '_rechazo', '_pisoton'); fx.burst('anger', 1, 1.3); fx.burst('puff', 3, 1.3); }
      else { go('nerviosa', 3.5, cover, '_rechazo'); fx.burst('drop', 3); fx.burst('puff', 2, 1.2); }
    } else if (zone === 'legs' || zone === 'feet') {
      if (level === 1) { go('sorprendida', 1.6, '_saltito'); fx.burst('exclaim', 1); }
      else if (level === 2) {
        if (zone === 'feet') { go('feliz', 2.4, '_cosquillas'); fx.burst('spark', 3); }
        else { go('sonrojada', 3, '_falda', 'negar'); fx.burst('puff', 1); }
      } else { go(sharp > 0.45 ? 'molesta' : 'timida', 3.2, '_rechazo', sharp > 0.45 ? '_pisoton' : 'negar'); fx.burst(sharp > 0.45 ? 'anger' : 'drop', 2); }
    } else if (zone === 'belly') {
      if (level === 1) { go('feliz', 1.8, 'risita'); fx.burst('spark', 2); }
      else if (level === 2) { go('emocionada', 2.6, '_cosquillas'); fx.burst('spark', 4); }
      else { go('nerviosa', 3, '_cosquillas', '_rechazo'); fx.burst('drop', 3); fx.burst('exclaim', 1); }
    } else if (zone === 'arms' || zone === 'hands') {
      if (level === 1) { go('confundida', 1.5, '_mirar_mano'); fx.burst('question', 1); }
      else if (level === 2) { go('feliz', 2.2, zone === 'hands' ? 'saludar' : '_mirar_mano'); fx.burst('spark', 2); }
      else { go(tsun ? 'sonrojada' : 'carinosa', 3, '_mimos'); fx.burst('heart', 3, 1.2); }
    } else {                                              // la esfera, o un punto que no se distingue
      this.playGesture('_toque');
      if (level === 3) { this.flash(sharp > 0.45 ? 'molesta' : 'enamorada', 3); fx.burst(sharp > 0.45 ? 'anger' : 'heart', 4, 1.6); }
      else this.flash(r < 0.5 ? 'sorprendida' : 'feliz', 1.6);
    }
    return { zone, level, n: tc.n };
  }
  _project(x, y, z) {
    const r = this.canvas.getBoundingClientRect();
    this._v.set(x, y, z).project(this.camera);
    return { x: (this._v.x + 1) / 2 * r.width, y: (1 - this._v.y) / 2 * r.height };
  }
  // Puntos del personaje en px de la ventana: los pies (suelo), dónde se sienta y la cabeza. Para colocar la ventana
  // flotante sobre la barra de tareas o encima de otra ventana (desktop/pet.js).
  anchors() {
    if (!this.vrm && !this.orb) return null;
    const top = this.orb ? ORB_Y + 0.25 : this.headY + 0.16;
    const feet = this.orb ? ORB_Y - 0.33 : 0;
    const r = this.canvas.getBoundingClientRect();
    // La punta del índice derecho (la «mano de puntero» al trabajar), suavizada para que el golpecito de tocar no
    // haga temblar la ventana que la sigue.
    let hand;
    if (this.vrm) {
      const tip = this.fingers.right.find((f) => f.name === 'Index' && f.i === 2) || { node: this.bones.rightHand };
      const v = tip.node ? tip.node.getWorldPosition(new THREE.Vector3()) : new THREE.Vector3(0.3, this.hipsY, 0);
      const now = this._project(v.x, v.y, v.z);
      this._handS = this._handS ? { x: lerp(this._handS.x, now.x, 0.35), y: lerp(this._handS.y, now.y, 0.35) } : now;
      hand = this._handS;
    } else hand = this._project(0.3, this.orb ? ORB_Y - 0.1 : this.hipsY, 0);
    const out = { feet: this._project(0, feet, 0), seat: this._project(0, this.orb ? feet : this.hipsY - 0.07, 0),
      head: this._project(0, top, 0), hand, w: Math.round(r.width), h: Math.round(r.height) };
    // Largo de un paso al andar con la animación grabada (px; pet.js lo corrige por verla casi de perfil).
    // Con 100STYLE, también su ritmo (hz) y la velocidad a la que avanza (speed, px/s), según el estilo de ahora.
    const lib = this.vrm && this.lib;
    if (lib && lib.has('walk')) {
      const g = this.gait(), px = Math.abs(out.feet.y - this._project(0, this.hipsY, 0).y);
      out.step = g.stride * px;
      if (g.hz) out.hz = g.hz;
      if (g.speed) out.speed = g.speed * px;
    }
    return out;
  }
  // ¿Qué parte del personaje hay en ese punto de la ventana? Con un VRM: head | chest | belly | hips | legs | feet |
  // arms | hands (la más cercana entre puntos de su esqueleto, en pantalla); con la esfera, head | body. Deja en
  // `zoneSide` el lado (1 = su izquierda, -1 = su derecha) para los gestos. null si no hay personaje ahí.
  zoneAt(x, y) {
    if (!this.probeHit) return null;
    this.zoneSide = 1;
    if (this.orb || !this.vrm) {
      const head = this._project(0, this.orb ? ORB_Y : this.headY + 0.06, 0);
      const edge = this._project(0, this.orb ? ORB_Y + 0.23 : this.headY + 0.17, 0);
      return Math.hypot(x - head.x, y - head.y) < Math.max(18, Math.abs(head.y - edge.y) * 1.25) ? 'head' : 'body';
    }
    const b = this.bones, wp = (bone) => (b[bone] ? b[bone].getWorldPosition(new THREE.Vector3()) : null);
    const pts = [];
    const add = (zone, v, side = 1) => { if (v) { const s = this._project(v.x, v.y, v.z); pts.push({ zone, side, x: s.x, y: s.y }); } };
    const mid = (a, c, k = 0.5) => (a && c ? a.clone().lerp(c, k) : null);
    const head = wp('head'), neck = wp('neck'), chest = wp('upperChest') || wp('chest'), spine = wp('spine'), hips = wp('hips');
    if (head && this.head) add('head', this._headNow().eyes.clone());
    add('head', head && neck ? head.clone().lerp(neck, -0.6) : head);
    add('chest', chest ? chest.clone().add(new THREE.Vector3(0, -0.04, 0)) : null);
    add('belly', mid(spine, hips, 0.3));
    add('hips', hips);
    for (const [side, s] of [['left', 1], ['right', -1]]) {
      const ul = wp(side + 'UpperLeg'), ll = wp(side + 'LowerLeg'), ft = wp(side + 'Foot');
      add('hips', mid(hips, ul, 0.8), s);
      for (const k of [0.35, 0.7]) add('legs', mid(ul, ll, k), s);
      for (const k of [0, 0.5]) add('legs', mid(ll, ft, k), s);
      add('feet', ft, s);
      const ua = wp(side + 'UpperArm'), la = wp(side + 'LowerArm'), hd = wp(side + 'Hand');
      for (const k of [0.4, 0.8]) add('arms', mid(ua, la, k), s);
      add('arms', mid(la, hd, 0.5), s);
      add('hands', hd, s);
    }
    let best = null, bestD = Infinity;
    for (const p of pts) { const d = Math.hypot(p.x - x, p.y - y); if (d < bestD) { bestD = d; best = p; } }
    if (!best) return 'body';
    this.zoneSide = best.side;
    return best.zone;
  }

  // Cómo la miras con la cámara libre (16 nov 2026): de muy cerca a la cara, al pecho, a las piernas, desde abajo,
  // por la espalda o haciéndola girar. Si se mantiene ~1 s, reacciona según su carácter y avisa a `onView(kind)`
  // (main.js, para que lo comente en voz alta). Una vez por tipo cada 45 s, y nunca dos seguidas en menos de 8 s.
  _watchView(dt) {
    const wv = this.view || (this.view = { kind: null, since: 0, last: {}, any: -99, acc: 0, spinT: 0, az: null, t: 0 });
    wv.t += dt;
    if (!this.vrm || !this.userMoved || this.posing || this.act.name !== 'none') { wv.kind = null; return; }
    if (wv.t - (wv.tick || 0) < 0.25) return;
    const step = wv.t - (wv.tick || wv.t);
    wv.tick = wv.t;
    const cam = this.camera.position, tgt = this.controls.target, scale = clamp(this.headY / 1.4, 0.4, 2.5);
    // Giros: cuánto da la vuelta la cámara alrededor de ella en los últimos segundos.
    const az = Math.atan2(cam.x - tgt.x, cam.z - tgt.z);
    if (wv.az !== null) { let d = az - wv.az; d = Math.atan2(Math.sin(d), Math.cos(d)); wv.acc = Math.max(0, wv.acc * Math.pow(0.6, step) + Math.abs(d)); }
    wv.az = az;
    let kind = null;
    if (wv.acc > Math.PI * 2.2) kind = 'spin';
    else {
      const b = this.bones, wp = (n) => (b[n] ? b[n].getWorldPosition(new THREE.Vector3()) : null);
      const parts = { head: this.head ? this._headNow().eyes.clone() : wp('head'), chest: wp('upperChest') || wp('chest'), hips: wp('hips'),
        legs: wp('leftLowerLeg') && wp('rightLowerLeg') ? wp('leftLowerLeg').lerp(wp('rightLowerLeg'), 0.5).lerp(wp('hips'), 0.35) : null };
      let focus = null, fd = 0.42;
      for (const [name, v] of Object.entries(parts)) {
        if (!v) continue;
        const n = v.clone().project(this.camera);
        if (n.z > 1) continue;                            // detrás de la cámara
        const d = Math.hypot(n.x, n.y);
        if (d < fd) { fd = d; focus = { name, dist: cam.distanceTo(v) }; }
      }
      const fwd = new THREE.Vector3(Math.sin(this.yaw), 0, Math.cos(this.yaw));
      const toCam = new THREE.Vector3(cam.x, 0, cam.z).normalize();
      const behind = fwd.dot(toCam) < -0.55;
      const flat = Math.hypot(cam.x, cam.z);
      if (cam.y < this.hipsY * 0.55 && tgt.y - cam.y > 0.15 && flat < 1.6 * scale) kind = 'below';
      else if (behind && cam.distanceTo(tgt) < 2.6 * scale) kind = 'behind';
      else if (focus && focus.name === 'head' && focus.dist < 0.55 * scale) kind = 'face';
      else if (focus && focus.name === 'chest' && focus.dist < 0.75 * scale) kind = 'chest';
      else if (focus && (focus.name === 'legs' || focus.name === 'hips') && focus.dist < 1.15 * scale) kind = 'legs';
    }
    if (kind !== wv.kind) { wv.kind = kind; wv.since = wv.t; return; }
    if (!kind || wv.t - wv.since < (kind === 'spin' ? 0 : 1.0) || wv.t - wv.any < 8 || wv.t - (wv.last[kind] ?? -99) < 45) return;
    wv.last[kind] = wv.any = wv.t;
    if (kind === 'spin') wv.acc = 0;
    this.lookReact(kind);
    if (this.onView) this.onView(kind);
  }

  // La reacción del cuerpo a cómo la miras (la frase, si la hay, la pone el servidor con su personalidad).
  lookReact(kind) {
    const { shy, warm, sharp } = this.temper || { shy: 0.3, warm: 0.7, sharp: 0.3 };
    const fx = this.effects, bold = sharp > 0.5;
    const go = (emo, secs, ...g) => { this.flash(emo, secs); for (const n of g) this.playGesture(n); };
    if (kind === 'face') {
      if (shy > 0.5) { go('sonrojada', 3, 'risita'); fx.burst('puff', 1); }
      else if (bold) { go('confundida', 2.6, '_ladear'); fx.burst('question', 1); }
      else { go(warm > 0.7 ? 'carinosa' : 'sorprendida', 2.6, '_ladear'); fx.burst(warm > 0.7 ? 'heart' : 'exclaim', 1); }
    } else if (kind === 'chest') { go(bold ? 'molesta' : 'sonrojada', 3, '_cubrir'); fx.burst(bold ? 'anger' : 'puff', 1); }
    else if (kind === 'legs') { go(bold ? 'molesta' : 'sonrojada', 3, '_falda'); fx.burst(bold ? 'anger' : 'exclaim', 1); }
    else if (kind === 'below') { go(bold ? 'molesta' : 'asustada', 3.2, '_falda', bold ? '_pisoton' : 'negar'); fx.burst('exclaim', 2, 1.3); }
    else if (kind === 'behind') { go('confundida', 2.4, '_mirar'); fx.burst('question', 1); }
    else if (kind === 'spin') { go('confundida', 3, 'encogerse'); fx.burst('drop', 2); fx.burst('question', 2); }
  }

  // Tocar en la ventana normal: la cámara libre usa el arrastre, así que un clic corto pregunta qué hay bajo el
  // punto en el siguiente cuadro (se lee el píxel del dibujo, como al flotar). Promesa con la zona o null.
  pickAt(x, y) {
    return new Promise((resolve) => { this._pick = { x, y, resolve }; });
  }

  setVoice({ vol, low, mid, high, bands, centroid }) {
    const open = clamp((vol - 0.012) * 7);
    const total = low + mid + high + 1e-5;
    // Topes medidos con el modelo de VRoid: sus visemas al 100 % abren la boca de forma exagerada.
    const target = {
      aa: open * clamp(0.35 + 1.5 * mid / total) * 0.6,
      oh: open * clamp(1.3 * low / total) * 0.3,
      ee: open * clamp(2.2 * high / total) * 0.25,
      ih: open * clamp(1.6 * high / total) * 0.12,
      ou: open * clamp(1.0 * low / total) * 0.18,
    };
    // Qué sonido es (lipsync.js, de wawa-lipsync): la forma de la vocal sale de ahí en un 60 %, y en las consonantes
    // p/t/k la boca casi se cierra; en s/f/ch se queda con los dientes juntos. Con el reparto por bandas de antes
    // (el 40 % restante) no da saltos si el detector duda.
    if (bands && open > 0.02) {
      const lip = this.lip.update(bands, centroid, performance.now());
      const cap = { aa: 0.6, oh: 0.32, ee: 0.3, ih: 0.18, ou: 0.22 };
      for (const k of VISEMES) target[k] = 0.4 * target[k] + 0.6 * open * lip[k] * cap[k] * 1.4;
      if (lip.close) for (const k of VISEMES) target[k] *= 1 - 0.75 * lip.close;
      this.lipClose = lerp(this.lipClose || 0, lip.close || 0, 0.5);
    } else this.lipClose = lerp(this.lipClose || 0, 0, 0.3);
    const sum = VISEMES.reduce((s, k) => s + target[k], 0);
    if (sum > 0.7) for (const k of VISEMES) target[k] *= 0.7 / sum;
    // Abre rápido y cierra casi igual de rápido: entre sílabas la boca tiene que llegar a cerrarse.
    for (const k of VISEMES) this.mouth[k] = lerp(this.mouth[k], target[k], target[k] > this.mouth[k] ? 0.6 : 0.4);
    this.voice = lerp(this.voice, open, open > this.voice ? 0.4 : 0.08);
  }

  // ---------------------------------------------------------------- cuadro a cuadro
  update() {
    const dt = Math.min(this.clock.getDelta(), 0.05);
    const t = this.clock.elapsedTime;
    this.controls.update();
    if (this.vrm) {
      this._buildPose(t, dt);
      this._applyPose(dt);
      this._face(t, dt);
      this._gaze(t, dt);
      this._inertia();
      this.vrm.update(dt);
      this.vrm.scene.updateMatrixWorld(true);
      this._placeDevice(t);
      this.effects.update(dt, this._headNow());
    } else if (this.orb) {
      this._updateOrb(t, dt);
    }
    this.renderer.render(this.scene, this.camera);
    if (this._pick) {                                   // un clic en la ventana normal: ¿qué parte tocó?
      const { x, y, resolve } = this._pick, keep = this.probe;
      this._pick = null;
      this.probe = { x, y };
      this._readProbe();
      const zone = this.zoneAt(x, y);
      this.probe = keep;
      if (!this.floating) this.probeHit = false;
      resolve(zone);
    }
    if (this.floating) this._readProbe();
    this._watchView(dt);
  }

  // Inercia del pelo y la ropa (17 nov 2026): al flotar, la ventana se mueve (la arrastras, anda, salta, la llevas)
  // pero el personaje no se mueve dentro de su escena, así que sus físicas (los muelles del propio VRM) no lo notaban.
  // Se desplazan las puntas de esos muelles lo contrario a lo que se movió la ventana, en metros a la distancia del
  // personaje: el pelo y la falda se quedan atrás y vuelven, como si el cuerpo se hubiera movido de verdad.
  _inertia() {
    const sb = this.vrm && this.vrm.springBoneManager;
    if (!this.floating || !sb || this.posing) { this._win = null; return; }
    const x = window.screenX, y = window.screenY, last = this._win;
    this._win = { x, y };
    if (!last || (x === last.x && y === last.y)) return;
    const h = this.canvas.getBoundingClientRect().height || 1;
    const mpp = (2 * this.camera.position.distanceTo(this.controls.target) * Math.tan(THREE.MathUtils.degToRad(FOV / 2))) / h;
    const right = this._v.set(1, 0, 0).applyQuaternion(this.camera.quaternion);
    const up = (this._e6 || (this._e6 = new THREE.Vector3())).set(0, 1, 0).applyQuaternion(this.camera.quaternion);
    const d = (this._e7 || (this._e7 = new THREE.Vector3())).copy(right).multiplyScalar((x - last.x) * mpp)
      .addScaledVector(up, -(y - last.y) * mpp);
    const len = d.length();
    if (len > 0.6) return;                                  // un salto de la ventana (cambio de pantalla): sin sacudida
    if (len > 0.12) d.setLength(0.12);
    for (const j of sb.joints) {
      if (j._currentTail) j._currentTail.sub(d);
      if (j._prevTail) j._prevTail.sub(d);
    }
  }

  // La esfera: mismos estados, emociones, voz y gestos, sin esqueleto.
  _updateOrb(t, dt) {
    for (const s in this.stateW) this.stateW[s] = lerp(this.stateW[s], s === this.state ? 1 : 0, damp(5, dt));
    this.emoAge += dt;
    this.voiceSlow = lerp(this.voiceSlow, this.voice, damp(2.5, dt));
    this.beat = lerp(this.beat, clamp((this.voice - this.voiceSlow) * 5), damp(this.voice > this.voiceSlow ? 18 : 7, dt));
    const { idle, listening } = this.stateW;
    if (idle > 0.9 && !this.gestures.length) {
      const bored = this.hobbyOn && this.act.name === 'none' && t - this.lastActive > BORED_AFTER;
      if (bored && t > this.hobby.next) {                     // la esfera también se entretiene (orb.js los pinta)
        const h = pick(['_bailar', '_saltar', '_girar', '_tararear'], this.hobby.last);
        this.hobby.last = h;
        this.playGesture(h);
        this.hobby.next = t + GESTURES[h].dur + rand(15, 40);
      } else if (t > this.fidget.next) { this.playGesture(pick(IDLE_GESTURES)); this.fidget.next = t + rand(7, 16); }
    } else {
      this.fidget.next = Math.max(this.fidget.next, t + 4);
    }
    if (listening > 0.6) {
      if (t > this.nod.next) { this.playGesture('asentir'); this.nod.next = t + 3.5 + Math.random() * 3; }
    } else {
      this.nod.next = t + 1.6;
    }
    for (const g of this.gestures) { g.t += dt; g.dur = GESTURES[g.name].dur; }
    this.gestures = this.gestures.filter((g) => g.t < g.dur);
    this._petTick(t, dt);
    this.orb.update({ t, dt, emotion: this.emotion, emoAge: this.emoAge, state: this.stateW, voice: this.voice,
      beat: this.beat * this.stateW.speaking, mouth: VISEMES.reduce((s, k) => s + this.mouth[k], 0), gestures: this.gestures,
      act: { w: this.actW, work: this.workW, walkPhase: this.walkPhase, t: this.act.t } });
    this.effects.update(dt, this.orb.head(this.camera, this._headInfo));
  }

  _buildPose(t, dt) {
    const p = this.pose;
    p.reset();
    for (const s in this.stateW) this.stateW[s] = lerp(this.stateW[s], s === this.state ? 1 : 0, damp(5, dt));
    for (const e in this.emoW) this.emoW[e] = lerp(this.emoW[e], e === this.emotion ? 1 : 0, damp(3.5, dt));
    this.emoAge += dt;
    const { idle, listening, thinking, speaking } = this.stateW;

    // Reposo: brazos colgando cerca del cuerpo, codos algo doblados, dedos relajados.
    p.both(ARMS.rest);
    // Base grabada (17 nov 2026, clips.js): el reposo y el hablar de verdad (peso, cadera, rodillas, brazos que
    // acompañan), fundidos según el estado. Durante una actividad de la mascota (andar, sentarse…) manda la
    // actividad. El reloj va algo más rápido o más lento con ruido, para que no se note que el bucle se repite.
    const lib = this.lib;
    let baseW = 0, actMax = 0;
    for (const k of ACT_NAMES) actMax = Math.max(actMax, this.actW[k]);
    if (this.ik) { this.ik.plant = (1 - actMax) * (1 - this.sleep.w); this.ik.walk = this.actW.walk; }   // pies en el suelo (_legIK)
    this._styleStep(this.posing ? 0 : dt);
    if (lib) {
      baseW = 1 - actMax;
      if (!this.posing) this.clipT += dt * (0.92 + 0.1 * noise(t * 0.15, 21));
      this._L.idle.t = this._L.talk.t = this.clipT;
      if (this.forceClip) {                               // pruebas: un clip cualquiera, entero (hoja de contactos)
        const L = this._L.force || (this._L.force = new Layer(this.forceClip));
        L.name = this.forceClip; L.t = this.clipT;
        applyLayer(p, lib, L, 1, this.hipsY);
      } else {
        this._styled(p, 'idle', baseW, this.clipT);
        applyLayer(p, lib, this._L.talk, baseW * speaking, this.hipsY);
      }
    }
    p.handSet = 0;

    // Respiración: más rápida si está agitada, más lenta si está triste o tranquila; al hablar, más corta, y
    // toma aire de golpe al empezar y en cada pausa (como una persona entre frases).
    const br = this.breath;
    const rate = { emocionada: 2.2, asustada: 2.6, nerviosa: 2.3, sorprendida: 1.9, triste: 1.1, enamorada: 1.15, carinosa: 1.2 }[this.emotion] || 1.45;
    br.phase += dt * lerp(rate, 1.25, speaking) * (1 + 0.12 * noise(t * 0.2, 9));
    if (speaking > 0.5) {
      if (this.voice < 0.05) br.silent += dt;
      else { if (br.silent > 0.35) br.inhaleT = 0; br.silent = 0; }
    } else br.silent = 0;
    br.inhaleT += dt;
    const inhale = Math.sin(clamp(br.inhaleT / 0.45) * Math.PI) * (br.inhaleT < 0.45 ? 1 : 0);
    const deep = 1 - 0.55 * speaking;
    const breath = Math.sin(br.phase) * deep, breath2 = Math.sin(br.phase - 0.6) * deep;
    p.add('chest', [0.02 * breath - 0.035 * inhale, 0, 0]);
    p.add('upperChest', [0.014 * breath - 0.02 * inhale, 0, 0]);
    p.add('neck', [-0.01 * breath, 0, 0]);
    p.add('head', [-0.02 * inhale, 0, 0]);
    p.shoulders(0.014 * breath2 + 0.03 * inhale);
    p.both({ u: [0, 0, 0.012 * breath2], l: [0, -0.015 * breath2, 0] }, 1, 'add');

    // Peso: descansa sobre una pierna y cada cierto tiempo cambia a la otra. La cadera se ladea, el tronco
    // compensa para que la cabeza siga recta, las piernas quedan verticales y la rodilla libre se dobla un poco.
    const wt = this.weight;
    if (t > wt.next) {
      wt.goal = (wt.goal > 0 ? -1 : 1) * rand(0.45, 1);
      wt.next = t + rand(5, 12);
    }
    wt.cur = lerp(wt.cur, wt.goal, damp(1.3, dt));
    const s = wt.cur * (1 - 0.6 * baseW);           // con la base grabada, el peso ya se mueve: solo un poco más
    p.shift += 0.016 * s;
    p.add('hips', [0, 0.04 * s, 0.05 * s]);
    p.add('spine', [0, -0.02 * s, -0.028 * s]);
    p.add('chest', [0, -0.012 * s, -0.018 * s]);
    p.add('neck', [0, 0, -0.006 * s]);
    p.shoulders(-0.012 * s);
    for (const side of SIDES) {
      const free = Math.max(0, side === 'left' ? -s : s);         // pierna sin peso
      p.add(side + 'UpperLeg', [-0.07 * free, 0, -0.05 * s]);
      p.add(side + 'LowerLeg', [0.13 * free, 0, 0]);
      p.add(side + 'Foot', [-0.05 * free, 0, 0.02 * s]);
    }

    // Balanceo lento de todo el cuerpo, irregular (ruido, no senos: así no se nota que se repite); los brazos lo
    // siguen con retraso, como péndulos, y los muelles de los huesos ponen la inercia.
    const sway = noise(t * 0.35, 1), sway2 = noise(t * 0.22, 2);
    p.add('hips', [0, 0.03 * sway2, 0.008 * sway]);
    p.add('spine', [0.01 * sway2, -0.018 * sway2, -0.01 * sway]);
    p.add('head', [0.016 * noise(t * 0.6, 3), 0.035 * noise(t * 0.3, 4), 0.014 * noise(t * 0.45, 5)]);
    p.arm('left', { u: [0.022 * noise(t * 0.5, 6), 0, 0.014 * noise(t * 0.4, 7)], l: [0, -0.04 * (0.5 + 0.5 * noise(t * 0.45, 8)), 0] }, 1, 'add');
    p.arm('right', { u: [0.022 * noise(t * 0.5, 10), 0, 0.014 * noise(t * 0.4, 11)], l: [0, -0.04 * (0.5 + 0.5 * noise(t * 0.45, 12)), 0] }, 1, 'add');
    // Los dedos tampoco están quietos del todo.
    p.curl.left += 0.06 * noise(t * 0.4, 13);
    p.curl.right += 0.06 * noise(t * 0.4, 14);

    // La cabeza acompaña a los ojos cuando miran lejos: primero van los ojos y la cabeza llega después.
    const sc = this.saccade;
    const hf = this.headFollow;
    hf[0] = lerp(hf[0], sc.away ? sc.x : 0, damp(3, dt));
    hf[1] = lerp(hf[1], sc.away ? sc.y : 0, damp(3, dt));
    p.add('head', [-0.32 * hf[1], 0.38 * hf[0], 0.05 * hf[0]]);
    p.add('neck', [-0.08 * hf[1], 0.12 * hf[0], 0]);

    // Sin nada que hacer: de vez en cuando mira a un lado, ladea la cabeza o mueve los hombros. Y si llevas un rato
    // sin usar la app (BORED_AFTER), se entretiene sola: baila, salta, da una vuelta, se estira… (HOBBIES).
    let still = 0;
    for (const k of ACT_NAMES) still = Math.max(still, this.actW[k]);
    if (idle > 0.9 && !this.gestures.length) {
      const bored = this.hobbyOn && !this.posing && still < 0.05 && t - this.lastActive > BORED_AFTER;
      if (this.sleep.mode) {
        // dormida: ni pasatiempos ni gestos ociosos
      } else if (this.state === 'idle' && (this.sleepAsked || (bored && t - this.lastActive > SLEEP_AFTER)) && still < 0.05) {
        const asked = this.sleepAsked;                         // «duérmete»: empieza ya con sueño
        this.sleepAsked = false;
        this.sleepNow(null, asked);
      } else if (bored && t > this.hobby.next) {
        const h = pick(HOBBIES, this.hobby.last);
        this.hobby.last = h;
        this.playGesture(h);
        this.hobby.next = t + GESTURES[h].dur + rand(15, 40);
      } else if (t > this.fidget.next) { this.playGesture(pick(IDLE_GESTURES)); this.fidget.next = t + rand(7, 16); }
    } else {
      this.fidget.next = Math.max(this.fidget.next, t + 4);
    }

    // Escuchar: se inclina hacia ti, ladea la cabeza y asiente de vez en cuando.
    p.add('spine', [0.05, 0, 0], listening);
    p.add('head', [0.03, 0, 0.07 * this.tilt], listening);
    p.both(ARMS.ready, listening * 0.35);
    if (listening > 0.6) {
      if (t > this.nod.next) { this.playGesture('asentir'); this.nod.next = t + 3.5 + Math.random() * 3; }
    } else {
      this.nod.next = t + 1.6;
    }

    // Pensar: mira arriba y a un lado; si tarda, se lleva la mano a la barbilla.
    p.add('head', [-0.08, 0.17, -0.05], thinking);
    p.add('spine', [-0.015, 0.04, 0], thinking);
    p.gaze[0] += 0.3 * thinking; p.gaze[1] += 0.28 * thinking;
    this.thinkArm = lerp(this.thinkArm, thinking > 0.85 ? 1 : 0, damp(thinking > 0.85 ? 1.6 : 5, dt));
    p.arm('right', ARMS.chin, this.thinkArm * 0.9);

    // Hablar: el cuerpo acompaña la voz. `beat` salta con cada énfasis (cuando la voz sube de golpe).
    this.voiceSlow = lerp(this.voiceSlow, this.voice, damp(2.5, dt));
    this.beat = lerp(this.beat, clamp((this.voice - this.voiceSlow) * 5), damp(this.voice > this.voiceSlow ? 18 : 7, dt));
    const v = this.voice * speaking, beat = this.beat * speaking;
    p.add('head', [-0.04 * v + 0.07 * beat + 0.025 * v * Math.sin(t * 5.1), 0.06 * v * Math.sin(t * 1.7), 0.035 * v * Math.sin(t * 2.3)]);
    p.add('neck', [0.02 * beat, 0, 0]);
    p.add('spine', [0.02 * speaking + 0.012 * v * Math.sin(t * 2.1), 0.035 * v * Math.sin(t * 1.1), 0]);
    p.add('chest', [0.01 * beat, 0.02 * v * Math.sin(t * 1.3 + 1), 0]);
    p.shoulders(0.02 * beat);

    // Manos al hablar: encadena gestos, salvo que la emoción ya tenga las manos ocupadas.
    let busy = 0;
    for (const e in this.emoW) if (EMOTIONS[e].hands) busy = Math.max(busy, this.emoW[e]);
    const free = 1 - busy;
    const tk = this.talk;
    const talking = speaking > 0.55 && free > 0.4;
    // Cada gesto nuevo arranca con un golpe de voz (énfasis), como cuando una persona remarca una palabra.
    if (!tk.name && talking && this.voice > 0.12 && t > tk.next && (this.beat > 0.22 || t > tk.next + 1.2)) {
      tk.name = pick(TALK_NAMES, tk.last);
      tk.last = tk.name;
      tk.side = Math.random() < 0.6 ? 'right' : 'left';
      tk.until = t + rand(1.5, 3.2);
    }
    if (tk.name) {
      const on = talking && t < tk.until;
      tk.w = lerp(tk.w, on ? 1 : 0, damp(on ? 5.5 : 3.4, dt));
      p.both(ARMS.ready, speaking * free * 0.5 * (1 - tk.w));
      TALK[tk.name](p, tk.side, ease(clamp(tk.w)) * free, beat, t);
      if (!on && tk.w < 0.03) { tk.name = null; tk.w = 0; tk.next = t + rand(0.2, 1.1); }
    } else {
      p.both(ARMS.ready, speaking * free * 0.5);
      p.both({ l: [0, -0.12 * beat, 0] }, speaking * free, 'add');
    }

    // Emoción: cabeza, mirada y postura del cuerpo. Las emociones se funden entre sí al cambiar.
    const emo = EMOTIONS[this.emotion];
    const eh = emo.head || [0, 0, 0], eg = emo.gaze || [0, 0];
    for (let i = 0; i < 3; i++) this.emoHead[i] = lerp(this.emoHead[i], eh[i], damp(4, dt));
    for (let i = 0; i < 2; i++) this.emoGaze[i] = lerp(this.emoGaze[i], eg[i], damp(4, dt));
    p.add('head', this.emoHead);
    p.gaze[0] += this.emoGaze[0]; p.gaze[1] += this.emoGaze[1];
    for (const e in this.emoW) {
      const w = this.emoW[e];
      if (w > 0.01 && EMOTIONS[e].body) EMOTIONS[e].body(p, t, ease(w), this);
    }
    if (p.shake > 0.01) {                                        // temblor de susto
      const k = 0.012 * p.shake;
      p.add('spine', [k * Math.sin(t * 43), 0, k * Math.sin(t * 37)]);
      p.shoulders(k * Math.sin(t * 47));
      p.add('head', [0, k * Math.sin(t * 41), 0]);
    }

    // Mascota de escritorio: la actividad (andar, en brazos, cayendo, sentada, trabajando) manda sobre brazos y
    // piernas; el ratón, sobre hacia dónde mira.
    this._petPose(p, t, dt);

    this._sleepPose(p, t, dt);

    // Gestos en curso (los que pide el LLM y los ociosos).
    for (const g of this.gestures) {
      const def = GESTURES[g.name];
      g.t += dt;
      def.run(p, g.t, envelope(g.t, def.dur), g.side, this);
    }
    this.gestures = this.gestures.filter((g) => g.t < GESTURES[g.name].dur);
  }

  _petTick(t, dt) {
    const a = this.act;
    a.t += dt;
    for (const k of ACT_NAMES) this.actW[k] = lerp(this.actW[k], k === a.name ? 1 : 0, damp(k === 'fall' || k === 'carried' ? 9 : 4.5, dt));
    if (this.workUntil && t > this.workUntil) { this.workMode = 'read'; this.workUntil = 0; }
    for (const k in this.workW) this.workW[k] = lerp(this.workW[k], k === this.workMode ? 1 : 0, damp(6, dt));
    for (const k of STANCES) this.stanceW[k] = lerp(this.stanceW[k], k === this.stance ? 1 : 0, damp(4, dt));
    // Ritmo de la marcha: el natural del estilo que anda (100STYLE), o WALK_HZ con la marcha de siempre.
    if (!this.posing) this.walkPhase += dt * Math.PI * 2 * (this.gait().hz || WALK_HZ) * this.actW.walk;
    const goal = a.name === 'walk' ? (a.opts.dir || 1) * 1.2 : a.name === 'work' ? (a.opts.side || 1) * Math.PI * (a.opts.point ? 0.9 : 0.78)
      : a.name === 'sit' ? (a.opts.side || 1) * 1.1 : 0;
    this.yaw = lerp(this.yaw, goal, damp(a.name === 'work' ? 3.2 : 5, dt));
    // _girar: una vuelta entera, con arranque y frenada suaves (también la esfera).
    const spin = this.gestures.find((g) => g.name === '_girar' || g.name === 'girar');
    const su = spin ? clamp((spin.t - 0.15) / 1.4) : 0;
    this.spinYaw = spin ? spin.side * Math.PI * 2 * su * su * (3 - 2 * su) : 0;
    if (this.vrm) {
      this.vrm.scene.rotation.y = this.baseYaw + this.yaw + this.spinYaw + this.sleepYaw;
      this.vrm.scene.position.x = this.sleepShift;
      this.vrm.scene.position.y = this.sleep.mode === 'lean' ? this.sleepRise || 0 : lerp(this.vrm.scene.position.y, 0, damp(4, dt));
    }
    if (this.orb) this.orb.group.rotation.y = this.yaw + this.spinYaw;
    if (this.flashEmo && t > this.flashEmo.until) {
      if (this.emotion === this.flashEmo.emotion) this.setEmotion(this.flashEmo.back);
      this.flashEmo = null;
    }
    // Seguir el ratón: solo de frente, si se movió hace poco (mientras habla, menos: también te mira a ti).
    const fresh = this.follow && this.cursor && t - this.cursor.at < 5 && Math.abs(this.yaw) < 0.35 && this.floating;
    this.followW = lerp(this.followW, fresh ? 1 - 0.4 * this.stateW.speaking : 0, damp(fresh ? 4 : 1.5, dt));
  }

  _cursorWorld(out) {
    const r = this.canvas.getBoundingClientRect();
    out.set((this.cursor.x / r.width) * 2 - 1, -(this.cursor.y / r.height) * 2 + 1, 0.5).unproject(this.camera)
      .sub(this.camera.position).normalize();
    const d = this.camera.position.distanceTo((this._e4 || (this._e4 = new THREE.Vector3())).set(0, this.headY, 0)) * 0.8;
    return out.multiplyScalar(d).add(this.camera.position);
  }

  _petPose(p, t, dt) {
    this._petTick(t, dt);
    for (const k of ACT_NAMES) {
      const w = this.actW[k];
      if (w > 0.01) ACTIVITIES[k](p, this.act.name === k ? this.act.t : t, ease(clamp(w)), this);
    }
    if (this.followW > 0.01 && this.cursor) {
      const c = this._cursorWorld(this._e5 || (this._e5 = new THREE.Vector3()));
      const dx = c.x, dy = c.y - this.headY, dz = Math.max(0.05, c.z);
      const yaw = clamp(Math.atan2(dx, dz), -0.75, 0.75), pitch = clamp(-Math.atan2(dy, Math.hypot(dx, dz)), -0.45, 0.5);
      const w = this.followW;
      p.add('head', [0.55 * pitch, 0.55 * yaw, 0.05 * yaw], w);
      p.add('neck', [0.25 * pitch, 0.3 * yaw, 0], w);
      p.add('spine', [0, 0.12 * yaw, 0], w);
    }
  }

  // dt = 0 coloca la pose de golpe (al cargar y en las capturas de prueba).
  _applyPose(dt) {
    const flip = this.isV0 ? -1 : 1;
    // Cada hueso va hacia su objetivo como un muelle (con algo de inercia y un pequeño rebote), no a velocidad
    // constante: así un brazo que sube se pasa un poco y se asienta, y la mano llega después que el antebrazo.
    const steps = dt > 0.02 ? 2 : 1, h = dt / steps;
    for (const b in this.bones) {
      const r = this.pose.r[b];
      let st = this.spring[b];
      if (!st || !dt) {
        st = this.spring[b] = { x: [r[0], r[1], r[2]], v: [0, 0, 0] };
      } else {
        const [w, z] = SPRINGS[b];
        for (let k = 0; k < steps; k++) {
          for (let i = 0; i < 3; i++) {
            st.v[i] += (w * w * (r[i] - st.x[i]) - 2 * z * w * st.v[i]) * h;
            st.x[i] += st.v[i] * h;
          }
        }
      }
      this._e.set(st.x[0] * flip, st.x[1], st.x[2] * flip, 'XYZ');
      this.bones[b].quaternion.setFromEuler(this._e);
    }
    // Dedos: se cierran hacia la palma según `curl`; el meñique un poco más y el pulgar hacia dentro. `index`
    // deja el índice estirado (y cierra los demás) y `spread` los separa en abanico, como una palma abierta.
    // Encima, la postura de mano de cada dedo (HANDS), la cascada natural y un temblor mínimo de cada dedo en reposo.
    const FAN = { Index: -1, Middle: -0.15, Ring: 0.6, Little: 1.2 };
    const tt = this.clock.elapsedTime;
    for (const side of SIDES) {
      const s = side === 'left' ? 1 : -1;
      const c = clamp(this.pose.curl[side], -0.15, 1);
      const ix = clamp(this.pose.index[side]), sp = clamp(this.pose.spread[side]);
      const sh = this.pose.shape[side], shw = clamp(this.pose.shapeW[side]);
      const calm = (1 - shw) * (1 - clamp(this.pose.handSet));
      for (const f of this.fingers[side]) {
        const wob = calm * 0.05 * noise(tt * 0.22, FINGER_SEED[f.name] + (side === 'left' ? 0 : 7));
        if (f.thumb) {
          let ct = clamp(c + 0.4 * ix, -0.15, 1);
          ct = lerp(ct, sh.Thumb, shw) + wob;
          // Oposición: muy cerrado, el pulgar cruza hacia el índice (pinza, OK) en vez de quedarse tieso hacia arriba.
          const opp = Math.max(0, ct - 0.5), T = THUMB;
          this._e.set(T.x * opp * (f.i === 0 ? 1 : 0), -s * (0.1 + 0.42 * ct + T.y * opp - 0.12 * sp) * (f.i === 0 ? 1 : 0.6),
            -s * (0.12 * ct + T.z * opp * (f.i === 0 ? 1 : T.zd)) * flip, 'XYZ');
        } else {
          let cf = f.name === 'Index' ? lerp(c, -0.05, ix) : lerp(c, Math.max(c, 0.9), ix);
          cf += CASCADE[f.name] * (1 - shw) * (c > 0.05 ? 1 : 0.5);
          cf = lerp(cf, sh[f.name], shw) + wob * (f.i === 0 ? 1 : 0.6);
          const fanK = sh.fan && sh.fan[f.name] !== undefined ? lerp(FAN[f.name] * sp, sh.fan[f.name], shw) : FAN[f.name] * sp;
          const fan = f.i === 0 ? s * 0.13 * fanK : 0;
          this._e.set(0, fan, -s * cf * [1.05, 1.25, 0.85][f.i] * (f.little ? 1.12 : 1) * flip, 'XYZ');
        }
        this._q.setFromEuler(this._e);
        // Dedos de la animación grabada, salvo donde el código los pone a propósito (puño, señalar, palma abierta).
        const fk = this.pose.fingerW * (1 - clamp(this.pose.handSet)), fv = this.pose.fingers[f.bone];
        if (fk > 0.01 && fv) {
          this._e.set(fv[0] * flip, fv[1], fv[2] * flip, 'XYZ');
          this._q.slerp(this._q2.setFromEuler(this._e), fk);
        }
        f.node.quaternion.slerp(this._q, dt ? damp(FINGER_RATE[f.name], dt) : 1);
      }
    }
    if (this.bones.hips && this.hipsRest) {
      const a = dt ? damp(8, dt) : 1, pos = this.bones.hips.position;
      pos.y = lerp(pos.y, this.hipsRest.y + this.pose.lift, a);
      pos.x = lerp(pos.x, this.hipsRest.x + this.pose.shift * flip, a);
      pos.z = lerp(pos.z, this.hipsRest.z + this.pose.fwd * flip, a);
    }
    this._legIK(dt);
    this._leanIK();
  }

  _face(t, dt) {
    const em = this.vrm.expressionManager;
    if (!em) return;
    const target = EMOTIONS[this.emotion].face;
    const talking = this.stateW.speaking;
    const parts = this.parts || [];
    // Microgestos (face.js): cejas que suben al recalcar algo, ojos que se entrecierran, una sonrisita…
    const micro = { ...(this.micro ? this.micro.step(t, dt, this.emotion, talking, this.beat * talking, parts) : {}) };
    // La cara de un pasatiempo (bostezo, sonrisa al bailar): partes o expresiones completas, según el modelo.
    const fx = this.faceX;
    this.faceX = null;
    if (fx) for (const [k, v] of Object.entries(parts.length ? fx.parts : fx.preset)) micro[k] = (micro[k] || 0) + v * fx.w;
    if (parts.length) {
      // Cara por partes (modelos de VRoid): cejas, ojos y boca por separado. Al hablar, la boca cede a las vocales.
      const want = EMO_PARTS[this.emotion] || {};
      // ARKit: los labios siguen a la voz (redondos en o/u, apretados en p/b/m), además de las vocales.
      if (parts.kind === 'arkit') {
        const m = this.mouth;
        micro.akFunnel = (micro.akFunnel || 0) + 1.6 * m.oh;
        micro.akPucker = (micro.akPucker || 0) + 2.2 * m.ou;
        micro.akLips = (micro.akLips || 0) + 0.55 * (this.lipClose || 0) * talking;
      }
      for (const k of parts) {
        const lips = LIP_PARTS.includes(k);
        const mouth = !lips && (k.startsWith('mth') || /^ak(Smirk|Press|Puff|Dimple|Sneer)/.test(k));
        const goal = ((want[k] || 0) + (micro[k] || 0)) * (mouth ? 1 - 0.6 * talking : 1);
        this.partW[k] = lerp(this.partW[k] || 0, goal, damp(lips ? 18 : mouth ? 9 : 7, dt));
        em.setValue('p_' + k, clamp(this.partW[k]));
      }
    }
    for (const k of FACE_KEYS) {
      // Con partes, las expresiones completas solo se usan para lo que no tenga parte (nada, en VRoid).
      const goal = parts.length ? 0 : ((target[k] || 0) + (micro[k] || 0)) * (1 - 0.45 * talking);    // al hablar deja sitio a la boca
      this.face[k] = lerp(this.face[k], goal, damp(6, dt));
      em.setValue(k, this.face[k]);
    }
    for (const k of VISEMES) em.setValue(k, this.mouth[k]);

    // Parpadeo: más seguido si está nerviosa o enamorada, casi nada si está asustada o sorprendida. Como uno de
    // verdad: se cierra rápido (~65 ms), se queda un instante y se abre más despacio; si está tierna o
    // relajada, a veces es un parpadeo lento.
    const b = this.blink;
    const rate = EMOTIONS[this.emotion].blink || 1;
    if (b.t < 0 && t > b.next) {
      b.t = 0;
      b.slow = ['carinosa', 'enamorada', 'timida', 'triste'].includes(this.emotion) && Math.random() < 0.35 ? 1.9 : 1;
    }
    let blink = 0;
    if (b.t >= 0) {
      b.t += dt;
      const close = 0.065 * b.slow, hold = 0.03 * b.slow, open = 0.13 * b.slow;
      blink = b.t < close ? ease(b.t / close) : b.t < close + hold ? 1 : 1 - ease(clamp((b.t - close - hold) / open));
      if (b.t >= close + hold + open) {
        b.t = -1;
        b.last = t;
        b.twice = !b.twice && Math.random() < 0.18;            // a veces parpadea dos veces seguidas
        b.next = t + (b.twice ? 0.09 : (2.2 + Math.random() * 4) / rate);
      }
    }
    // Con los ojos ya cerrados de alegría, el parpadeo no los cierra «de más».
    blink = Math.max(blink, this.sleepEyes || 0);                // dormida o cabeceando: ojos cerrados
    em.setValue('blink', blink * (1 - 0.8 * clamp((this.partW && this.partW.eyeJoy) || 0)));
  }

  _gaze(t, dt) {
    // Mira a la cámara, con pequeños desvíos como los de un ojo de verdad (más, si está nerviosa).
    const s = this.saccade;
    const dart = EMOTIONS[this.emotion].dart || 0;
    if (t > s.next) {
      // Al hablar desvía la mirada más a menudo (como quien piensa lo que dice); al escuchar, casi nada.
      const st = this.stateW;
      const away = Math.random() < (0.25 + 0.5 * dart) * (1 + 0.6 * st.speaking - 0.6 * st.listening);
      s.x = (Math.random() - 0.5) * (away ? 0.5 + 0.4 * dart : 0.08);
      s.y = (Math.random() - 0.5) * (away ? 0.25 : 0.05);
      if (away && !s.away && Math.random() < 0.45) this._blinkSoon();      // un desvío grande suele llevar parpadeo
      s.away = away;
      s.next = t + (away ? 0.5 + Math.random() * 0.7 : 1.2 + Math.random() * 2.5) / (1 + 2 * dart);
    }
    this._v.copy(this.camera.position);
    this._v.x += (this.pose.gaze[0] + s.x) * 1.2;
    this._v.y += (this.pose.gaze[1] + s.y) * 1.2;
    if (this.followW > 0.05 && this.cursor) {             // el ratón (modo flotante)
      this._v.lerp(this._cursorWorld(this._e6 || (this._e6 = new THREE.Vector3())), this.followW);
    }
    if (Math.abs(this.yaw) > 0.35 && this.act.name !== 'sit') {   // de lado o de espaldas: mira hacia donde va o trabaja
      this._v.set(Math.sin(this.yaw) * 2, this.headY - 0.25 + s.y, Math.cos(this.yaw) * 2);
    }
    this.lookTarget.position.lerp(this._v, damp(10, dt));
  }

  // Hoja de contactos de la esfera (misma idea que sheet, sin esqueleto).
  orbSheet(specs, cols, cw, ch) {
    const out = document.createElement('canvas');
    out.width = cols * cw;
    out.height = Math.ceil(specs.length / cols) * ch;
    const g = out.getContext('2d');
    g.fillStyle = '#1a1830';
    g.fillRect(0, 0, out.width, out.height);
    const keep = { w: this.canvas.width, h: this.canvas.height, aspect: this.camera.aspect, state: this.state, emotion: this.emotion };
    this.renderer.setSize(cw, ch, false);
    this.camera.aspect = cw / ch;
    this.camera.updateProjectionMatrix();
    this.frame();
    specs.forEach((spec, i) => {
      this.state = spec.state || 'idle';
      this.emotion = spec.emotion || 'neutral';
      this.voice = spec.voice ?? (this.state === 'speaking' ? 0.6 : 0);
      this.mouth.aa = this.state === 'speaking' ? 0.3 : 0;
      this.fidget.next = 1e9;
      this.act = { name: spec.activity || 'none', opts: spec.opts || {}, t: 1 };
      for (const k of ACT_NAMES) this.actW[k] = k === this.act.name ? 1 : 0;
      this.workMode = spec.work || 'read';
      for (const k in this.workW) this.workW[k] = k === this.workMode ? 1 : 0;
      this.effects.clear(); this.effects.feeling = 'neutral';
      for (let n = 0; n < 40; n++) {
        this.emoAge = spec.age ?? 5;
        this.gestures = spec.gesture ? [{ name: spec.gesture, t: (spec.at ?? 0.5) * GESTURES[spec.gesture].dur, side: 1 }] : [];
        if (n === 26) this.effects.setFeeling(this.emotion);
        this._updateOrb(3 + i * 0.37, 0.05);
      }
      this.renderer.render(this.scene, this.camera);
      const x = (i % cols) * cw, y = Math.floor(i / cols) * ch;
      g.drawImage(this.canvas, x, y, cw, ch);
      g.fillStyle = '#fff';
      g.font = '600 15px "Segoe UI", sans-serif';
      g.fillText(spec.label || spec.emotion || spec.gesture || 'reposo', x + 8, y + 20);
    });
    Object.assign(this, { state: keep.state, emotion: 'neutral', gestures: [], voice: 0 });
    this.act = { name: 'none', opts: {}, t: 0 };
    this.mouth.aa = 0;
    this.fidget.next = this.clock.elapsedTime + 8;
    this.effects.clear(); this.effects.feeling = 'neutral';
    this.setEmotion(keep.emotion);
    this.renderer.setSize(keep.w / this.renderer.getPixelRatio(), keep.h / this.renderer.getPixelRatio(), false);
    this.camera.aspect = keep.aspect;
    this.camera.updateProjectionMatrix();
    this.frame();
    return out;
  }

  // ---------------------------------------------------------------- pruebas
  // Hoja de contactos: dibuja varias poses fijas en una sola imagen, para revisarlas de un vistazo.
  //   specs: [{ label, emotion, state, talk, side, gesture, at, voice, weight }]   → devuelve un <canvas>
  sheet(specs, cols = 4, cw = 300, ch = 420) {
    if (!this.vrm) return this.orbSheet(specs, cols, cw, ch);
    const out = document.createElement('canvas');
    out.width = cols * cw;
    out.height = Math.ceil(specs.length / cols) * ch;
    const g = out.getContext('2d');
    g.fillStyle = '#1a1830';
    g.fillRect(0, 0, out.width, out.height);
    const keep = { state: this.state, emotion: this.emotion, w: this.canvas.width, h: this.canvas.height, aspect: this.camera.aspect };
    this.renderer.setSize(cw, ch, false);
    this.camera.aspect = cw / ch;
    this.camera.updateProjectionMatrix();
    this._sheetFull = specs.some((sp) => sp.full);          // de cuerpo entero (posturas de la mascota)
    const keepClips = this.clipOn;
    this.frame();
    specs.forEach((spec, i) => {
      this.state = spec.state || 'idle';
      this.emotion = spec.emotion || 'neutral';
      this.emoAge = spec.age ?? 5;
      this.gestures = spec.gesture ? [{ name: spec.gesture, t: (spec.at ?? 0.5) * GESTURES[spec.gesture].dur, side: 1 }] : [];
      this.voice = spec.voice ?? (this.state === 'speaking' ? 0.6 : 0);
      this.voiceSlow = this.voice * 0.7;
      this.talk = { name: spec.talk || null, side: spec.side || 'right', w: spec.talk ? 1 : 0, until: 1e9, next: 1e9, last: null };
      this.weight = { cur: spec.weight ?? 0.6, goal: spec.weight ?? 0.6, next: 1e9 };
      this.fidget.next = 1e9;
      this.act = { name: spec.activity || 'none', opts: spec.opts || {}, t: 1 };
      for (const k of ACT_NAMES) this.actW[k] = k === this.act.name ? 1 : 0;
      this.workMode = spec.work || 'read';
      for (const k in this.workW) this.workW[k] = k === this.workMode ? 1 : 0;
      this.stance = spec.stance || 'stand';
      for (const k of STANCES) this.stanceW[k] = k === this.stance ? 1 : 0;
      this.walkPhase = spec.phase ?? 0.8;
      this.clipT = spec.clipT ?? 1;                       // instante de las animaciones grabadas
      this.clipOn = spec.clips ?? keepClips;              // clips: false = solo la animación en código (comparar)
      this.forceClip = spec.clip || null;                 // clip: un clip concreto, entero
      this.posing = true;
      const t = 3 + i * 0.37;
      for (let n = 0; n < 40; n++) {                      // deja asentarse pesos, pelo y efectos
        this._buildPose(t, 0.05);
        this.gestures.forEach((gs) => (gs.t -= 0.05));
        this._applyPose(0);
        this._face(t, 0.05);
        this._gaze(t, 0.05);
        this.vrm.update(0.03);
        this.vrm.scene.updateMatrixWorld(true);
        if (n === 26) { this.effects.clear(); this.effects.feeling = 'neutral'; this.effects.setFeeling(this.emotion); }
        if (n >= 26) this.effects.update(0.05, this._headNow());       // los efectos, a medio vuelo
      }
      this.renderer.render(this.scene, this.camera);
      const x = (i % cols) * cw, y = Math.floor(i / cols) * ch;
      g.drawImage(this.canvas, x, y, cw, ch);
      g.fillStyle = '#fff';
      g.font = '600 15px "Segoe UI", sans-serif';
      g.fillText(spec.label || spec.activity || spec.emotion || spec.talk || spec.gesture || 'reposo', x + 8, y + 20);
    });
    Object.assign(this, { state: keep.state, emotion: 'neutral', gestures: [] });
    this.act = { name: 'none', opts: {}, t: 0 };
    this._sheetFull = false;
    this.clipOn = keepClips;
    this.forceClip = null;
    this.stance = 'stand';
    this.posing = false;
    this.talk = { name: null, side: 'right', w: 0, until: 0, next: 0, last: null };
    this.weight.next = 0;
    this.fidget.next = this.clock.elapsedTime + 8;
    this.effects.clear();
    this.effects.feeling = 'neutral';
    this.setEmotion(keep.emotion);
    this.renderer.setSize(keep.w / this.renderer.getPixelRatio(), keep.h / this.renderer.getPixelRatio(), false);
    this.camera.aspect = keep.aspect;
    this.camera.updateProjectionMatrix();
    this.frame();
    return out;
  }
}
