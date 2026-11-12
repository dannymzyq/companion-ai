// El cuerpo de Mika: carga el modelo VRM y lo anima de forma procedural, sin animaciones grabadas, así que
// sirve para cualquier VRM (se trabaja sobre el esqueleto humanoide normalizado que trae todo modelo).
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
import { VRMLoaderPlugin, VRMUtils } from '@pixiv/three-vrm';
import { Effects } from './effects.js';
import { Orb, ORB_Y } from './orb.js';

const FOV = 26;
const SIDES = ['left', 'right'];
const BONES = ['hips', 'spine', 'chest', 'upperChest', 'neck', 'head',
  ...SIDES.flatMap((s) => ['Shoulder', 'UpperArm', 'LowerArm', 'Hand', 'UpperLeg', 'LowerLeg', 'Foot'].map((b) => s + b))];
const FINGERS = ['Thumb', 'Index', 'Middle', 'Ring', 'Little'];
// Cuánto sigue cada hueso a su objetivo (más bajo = más inercia): los brazos van algo por detrás del tronco.
const RATE = (b) => (/Arm|Hand/.test(b) ? 9 : /Shoulder|Leg|Foot|hips/.test(b) ? 8 : 13);

const FACE_KEYS = ['happy', 'angry', 'sad', 'relaxed', 'surprised'];
const VISEMES = ['aa', 'ih', 'ou', 'ee', 'oh'];

const clamp = (x, a = 0, b = 1) => Math.max(a, Math.min(b, x));
const lerp = (a, b, t) => a + (b - a) * t;
const ease = (t) => t * t * (3 - 2 * t);
const damp = (rate, dt) => 1 - Math.exp(-rate * dt);
const wave = (t, hz) => Math.sin(t * Math.PI * 2 * hz);
const rand = (a, b) => a + Math.random() * (b - a);
const pick = (list, not) => { const l = list.filter((x) => x !== not); return l[Math.floor(Math.random() * l.length)]; };

function envelope(t, dur, edge = 0.22) {
  return ease(clamp(Math.min(t / (dur * edge), (dur - t) / (dur * edge))));
}

class Pose {
  constructor() {
    this.r = {};
    for (const b of BONES) this.r[b] = [0, 0, 0];
    this.gaze = [0, 0];
    this.curl = { left: 0, right: 0 };     // dedos: 0 mano abierta · 1 puño
    this.reset();
  }
  reset() {
    for (const b of BONES) { const v = this.r[b]; v[0] = v[1] = v[2] = 0; }
    this.gaze[0] = this.gaze[1] = 0;
    this.lift = 0;                          // sube o baja el cuerpo (m)
    this.shift = 0;                         // lo desplaza de lado (m)
    this.curl.left = this.curl.right = 0.3;
    this.shake = 0;                         // temblor (susto)
  }
  add(bone, v, w = 1) { const r = this.r[bone]; r[0] += v[0] * w; r[1] += v[1] * w; r[2] += v[2] * w; }
  set(bone, v, w = 1) { const r = this.r[bone]; r[0] = lerp(r[0], v[0], w); r[1] = lerp(r[1], v[1], w); r[2] = lerp(r[2], v[2], w); }
  // Brazo entero escrito para el izquierdo; `side` lo refleja. u = brazo, l = antebrazo, h = mano, c = dedos.
  arm(side, { u, l, h, c }, w = 1, mode = 'set') {
    const s = side === 'left' ? 1 : -1;
    const put = (bone, v) => v && this[mode](side + bone, [v[0], v[1] * s, v[2] * s], w);
    put('UpperArm', u); put('LowerArm', l); put('Hand', h);
    if (c !== undefined) this.curl[side] = lerp(this.curl[side], c, w);
  }
  both(pose, w = 1, mode = 'set') { this.arm('left', pose, w, mode); this.arm('right', pose, w, mode); }
  shoulders(up, w = 1) { this.add('leftShoulder', [0, 0, up], w); this.add('rightShoulder', [0, 0, -up], w); }
}

// ---------------------------------------------------------------- posturas de brazos
const ARMS = {
  rest:    { u: [0.05, -0.12, -1.27], l: [0, -0.36, 0], h: [0, 0, -0.06], c: 0.3 },     // colgando, codo algo doblado
  ready:   { u: [-0.06, -0.2, -1.22], l: [0, -0.75, 0], h: [0, 0, 0], c: 0.22 },       // antebrazos algo levantados
  explain: { u: [-0.24, -0.25, -1.18], l: [0, -1.4, 0], h: [-0.45, 0, 0.12], c: 0.12 }, // una mano delante, palma abierta
  open:    { u: [-0.14, 0.02, -1.2], l: [0, -1.25, 0], h: [-0.7, 0, 0.16], c: 0.06 },   // antebrazos delante, palmas abiertas
  chest:   { u: [-0.34, -0.8, -1.22], l: [0, -2.15, 0], h: [0, 0, 0.1], c: 0.25 },      // mano al pecho
  point:   { u: [-0.7, -0.2, -1.12], l: [0, -1.85, 0], h: [0, 0, 0.18], c: 0.2 },       // mano levantada
  front:   { u: [-0.16, -0.55, -1.24], l: [0, -1.4, 0], h: [0, 0, 0.1], c: 0.35 },      // manos juntas delante
  guard:   { u: [-0.42, -0.6, -1.12], l: [0, -2.3, 0], h: [0, 0, 0.1], c: 0.75 },       // encogida, puños al pecho
  chin:    { u: [-0.55, 0, -1.05], l: [0, -2.0, 0], h: [0, 0, 0], c: 0.55 },            // mano a la barbilla
  fists:   { u: [0.12, -0.1, -1.31], l: [0, -0.45, 0], h: [0, 0, 0], c: 0.95 },         // brazos tensos, puños
  startle: { u: [-0.15, -0.2, -1.17], l: [0, -1.95, 0], h: [0, 0, 0], c: -0.1 },        // manos arriba, dedos abiertos
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
  cuenta(p, side, w, beat, t) {
    p.arm(side, ARMS.point, w);
    p.add(side + 'Hand', [0, 0, (side === 'left' ? 1 : -1) * (0.12 * Math.sin(t * 7) + 0.25 * beat)], w);
    p.add('head', [-0.03, (side === 'left' ? 1 : -1) * 0.06, 0], w);
  },
  ambas(p, side, w, beat, t) {
    p.both(ARMS.explain, w);
    const s = 0.14 * Math.sin(t * 3.1);
    p.add('leftLowerArm', [0, -0.16 * beat + s, 0], w);
    p.add('rightLowerArm', [0, 0.16 * beat + s, 0], w);
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
  triste:      { face: { sad: 0.8 }, head: [0.2, 0, 0.04], gaze: [0, -0.25], hands: true, blink: 0.7, body(p, t, w) {
    p.both(ARMS.limp, w);
    p.shoulders(-0.07, w);
    p.add('spine', [0.08, 0, 0], w);
    p.add('chest', [0.07, 0, 0], w);
    p.lift -= 0.012 * w;
  } },
  molesta:     { face: { angry: 0.7 }, head: [0.08, 0, -0.05], hands: true, body(p, t, w) {
    p.both(ARMS.fists, w);
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
};
const IDLE_GESTURES = ['_mirar', '_ladear', '_hombros'];

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

    this.controls = new OrbitControls(this.camera, canvas);
    Object.assign(this.controls, { enablePan: false, enableDamping: true, dampingFactor: 0.08,
      minDistance: 0.7, maxDistance: 4.5, minPolarAngle: Math.PI * 0.36, maxPolarAngle: Math.PI * 0.56,
      minAzimuthAngle: -0.7, maxAzimuthAngle: 0.7 });
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
    this.gestures = [];
    this.talk = { name: null, side: 'right', w: 0, until: 0, next: 0, last: null };
    this.weight = { cur: 0.5, goal: 0.5, next: 4 };          // sobre qué pierna descansa (-1..1)
    this.fidget = { next: 7 };
    this.thinkArm = 0;
    this.tilt = 1;
    this.blink = { next: 2, t: -1, twice: false };
    this.saccade = { next: 1.5, x: 0, y: 0 };
    this.nod = { next: 3 };
    this._q = new THREE.Quaternion();
    this._q2 = new THREE.Quaternion();
    this._e = new THREE.Euler();
    this._v = new THREE.Vector3();
    this._headInfo = { eyes: new THREE.Vector3(), cheeks: [new THREE.Vector3(), new THREE.Vector3()], unit: 0.11, facing: 1 };
    this.floating = false;
    this.probe = null;              // punto (px de la ventana) donde se mira si hay avatar o fondo transparente
    this.probeHit = false;
    this._px = new Uint8Array(4);

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
        segs.forEach((seg, i) => { const n = node(side + f + seg); if (n) this.fingers[side].push({ node: n, thumb: f === 'Thumb', i, little: f === 'Little' }); });
      }
    }
    this.hipsRest = this.bones.hips ? this.bones.hips.position.clone() : null;
    if (vrm.lookAt) vrm.lookAt.target = this.lookTarget;
    this.scene.add(vrm.scene);
    this._measureHead(vrm);

    this._buildPose(this.clock.elapsedTime, 0);
    this._applyPose(0);             // pose de reposo antes del primer cuadro (evita ver la «T»)
    vrm.update(0);
    vrm.scene.updateMatrixWorld(true);
    const head = node('head');
    this.headY = head ? head.getWorldPosition(this._v).y : 1.4;
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
      cheeks: [1, -1].map((s) => local(new THREE.Vector3(mid.x + s * (half + 0.2 * unit), mid.y - 0.42 * unit, mid.z + 0.08 * unit))),
    };
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
    this.userMoved = false;
    this.frame();
  }

  get loaded() { return !!this.vrm || !!this.orb; }

  unload() {
    this.effects.clear();
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

  // Modo flotante: sin girar la cámara con el ratón (arrastrar mueve la ventana) y con el encuadre fijo.
  setFloating(on) {
    this.floating = on;
    this.controls.enabled = !on;
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
    // La esfera va centrada; un personaje con cuerpo, encuadrado de la cintura a la cabeza.
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
    if (state === 'listening') this.tilt = Math.random() < 0.5 ? -1 : 1;
  }
  setEmotion(name) {
    if (!(name in EMOTIONS) || name === this.emotion) return;
    this.emotion = name;
    this.emoAge = 0;
    this.effects.setFeeling(name);
  }
  playGesture(name, side = Math.random() < 0.5 ? -1 : 1) {
    if (!(name in GESTURES)) return;
    this.gestures = this.gestures.filter((g) => g.name !== name);
    this.gestures.push({ name, t: 0, side });
  }
  setVoice({ vol, low, mid, high }) {
    const open = clamp((vol - 0.012) * 7);
    const total = low + mid + high + 1e-5;
    // Topes medidos con el modelo de VRoid: sus visemas al 100 % abren la boca de forma exagerada.
    const target = {
      aa: open * clamp(0.35 + 1.5 * mid / total) * 0.5,
      oh: open * clamp(1.3 * low / total) * 0.3,
      ee: open * clamp(2.2 * high / total) * 0.25,
      ih: open * clamp(1.6 * high / total) * 0.12,
      ou: open * clamp(1.0 * low / total) * 0.18,
    };
    const sum = VISEMES.reduce((s, k) => s + target[k], 0);
    if (sum > 0.7) for (const k of VISEMES) target[k] *= 0.7 / sum;
    for (const k of VISEMES) this.mouth[k] = lerp(this.mouth[k], target[k], target[k] > this.mouth[k] ? 0.55 : 0.28);
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
      this.vrm.update(dt);
      this.vrm.scene.updateMatrixWorld(true);
      this.effects.update(dt, this._headNow());
    } else if (this.orb) {
      this._updateOrb(t, dt);
    }
    this.renderer.render(this.scene, this.camera);
    if (this.floating) this._readProbe();
  }

  // La esfera: mismos estados, emociones, voz y gestos, sin esqueleto.
  _updateOrb(t, dt) {
    for (const s in this.stateW) this.stateW[s] = lerp(this.stateW[s], s === this.state ? 1 : 0, damp(5, dt));
    this.emoAge += dt;
    this.voiceSlow = lerp(this.voiceSlow, this.voice, damp(2.5, dt));
    this.beat = lerp(this.beat, clamp((this.voice - this.voiceSlow) * 5), damp(this.voice > this.voiceSlow ? 18 : 7, dt));
    const { idle, listening } = this.stateW;
    if (idle > 0.9 && !this.gestures.length) {
      if (t > this.fidget.next) { this.playGesture(pick(IDLE_GESTURES)); this.fidget.next = t + rand(7, 16); }
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
    this.orb.update({ t, dt, emotion: this.emotion, emoAge: this.emoAge, state: this.stateW, voice: this.voice,
      beat: this.beat * this.stateW.speaking, mouth: VISEMES.reduce((s, k) => s + this.mouth[k], 0), gestures: this.gestures });
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

    // Respiración: pecho, hombros y, un poco, los brazos.
    const breath = Math.sin(t * 1.45), breath2 = Math.sin(t * 1.45 - 0.6);
    p.add('chest', [0.02 * breath, 0, 0]);
    p.add('upperChest', [0.014 * breath, 0, 0]);
    p.add('neck', [-0.01 * breath, 0, 0]);
    p.shoulders(0.014 * breath2);
    p.both({ u: [0, 0, 0.012 * breath2], l: [0, -0.015 * breath2, 0] }, 1, 'add');

    // Peso: descansa sobre una pierna y cada cierto tiempo cambia a la otra. La cadera se ladea, el tronco
    // compensa para que la cabeza siga recta, las piernas quedan verticales y la rodilla libre se dobla un poco.
    const wt = this.weight;
    if (t > wt.next) {
      wt.goal = (wt.goal > 0 ? -1 : 1) * rand(0.45, 1);
      wt.next = t + rand(5, 12);
    }
    wt.cur = lerp(wt.cur, wt.goal, damp(1.3, dt));
    const s = wt.cur;
    p.shift = 0.016 * s;
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

    // Balanceo lento de todo el cuerpo; los brazos lo siguen con retraso, como péndulos.
    const sway = Math.sin(t * 0.42), sway2 = Math.sin(t * 0.27 + 1.3);
    p.add('hips', [0, 0.03 * sway2, 0.008 * sway]);
    p.add('spine', [0.01 * sway2, -0.018 * sway2, -0.01 * sway]);
    p.add('head', [0.014 * Math.sin(t * 0.9), 0.03 * Math.sin(t * 0.33), 0.012 * Math.sin(t * 0.51)]);
    p.arm('left', { u: [0.022 * Math.sin(t * 0.63), 0, 0.014 * Math.sin(t * 0.42 - 0.9)], l: [0, -0.04 * (0.5 + 0.5 * Math.sin(t * 0.5)), 0] }, 1, 'add');
    p.arm('right', { u: [0.022 * Math.sin(t * 0.57 + 1.7), 0, 0.014 * Math.sin(t * 0.42 - 2.1)], l: [0, -0.04 * (0.5 + 0.5 * Math.sin(t * 0.44 + 2)), 0] }, 1, 'add');

    // Sin nada que hacer: de vez en cuando mira a un lado, ladea la cabeza o mueve los hombros.
    if (idle > 0.9 && !this.gestures.length) {
      if (t > this.fidget.next) { this.playGesture(pick(IDLE_GESTURES)); this.fidget.next = t + rand(7, 16); }
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
    if (!tk.name && talking && this.voice > 0.12 && t > tk.next) {
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

    // Gestos en curso (los que pide el LLM y los ociosos).
    for (const g of this.gestures) {
      const def = GESTURES[g.name];
      g.t += dt;
      def.run(p, g.t, envelope(g.t, def.dur), g.side);
    }
    this.gestures = this.gestures.filter((g) => g.t < GESTURES[g.name].dur);
  }

  // dt = 0 coloca la pose de golpe (al cargar y en las capturas de prueba).
  _applyPose(dt) {
    const flip = this.isV0 ? -1 : 1;
    for (const b in this.bones) {
      const r = this.pose.r[b];
      this._e.set(r[0] * flip, r[1], r[2] * flip, 'XYZ');
      this._q.setFromEuler(this._e);
      this.bones[b].quaternion.slerp(this._q, dt ? damp(RATE(b), dt) : 1);
    }
    // Dedos: se cierran hacia la palma según `curl`; el meñique un poco más y el pulgar hacia dentro.
    for (const side of SIDES) {
      const s = side === 'left' ? 1 : -1;
      const c = clamp(this.pose.curl[side], -0.15, 1);
      for (const f of this.fingers[side]) {
        if (f.thumb) this._e.set(0, -s * (0.1 + 0.42 * c) * (f.i === 0 ? 1 : 0.6), -s * 0.12 * c * flip, 'XYZ');
        else this._e.set(0, 0, -s * c * [1.05, 1.25, 0.85][f.i] * (f.little ? 1.12 : 1) * flip, 'XYZ');
        this._q.setFromEuler(this._e);
        f.node.quaternion.slerp(this._q, dt ? damp(10, dt) : 1);
      }
    }
    if (this.bones.hips && this.hipsRest) {
      const a = dt ? damp(8, dt) : 1, pos = this.bones.hips.position;
      pos.y = lerp(pos.y, this.hipsRest.y + this.pose.lift, a);
      pos.x = lerp(pos.x, this.hipsRest.x + this.pose.shift * flip, a);
    }
  }

  _face(t, dt) {
    const em = this.vrm.expressionManager;
    if (!em) return;
    const target = EMOTIONS[this.emotion].face;
    const talking = this.stateW.speaking;
    for (const k of FACE_KEYS) {
      const goal = (target[k] || 0) * (1 - 0.45 * talking);    // al hablar deja sitio a la boca
      this.face[k] = lerp(this.face[k], goal, damp(6, dt));
      em.setValue(k, this.face[k]);
    }
    for (const k of VISEMES) em.setValue(k, this.mouth[k]);

    // Parpadeo: más seguido si está nerviosa o enamorada, casi nada si está asustada o sorprendida.
    const b = this.blink;
    const rate = EMOTIONS[this.emotion].blink || 1;
    if (b.t < 0 && t > b.next) b.t = 0;
    let blink = 0;
    if (b.t >= 0) {
      b.t += dt;
      blink = Math.sin(clamp(b.t / 0.15) * Math.PI);
      if (b.t >= 0.15) {
        b.t = -1;
        b.twice = !b.twice && Math.random() < 0.18;            // a veces parpadea dos veces seguidas
        b.next = t + (b.twice ? 0.09 : (2.2 + Math.random() * 4) / rate);
      }
    }
    em.setValue('blink', blink);
  }

  _gaze(t, dt) {
    // Mira a la cámara, con pequeños desvíos como los de un ojo de verdad (más, si está nerviosa).
    const s = this.saccade;
    const dart = EMOTIONS[this.emotion].dart || 0;
    if (t > s.next) {
      const away = Math.random() < 0.25 + 0.5 * dart;
      s.x = (Math.random() - 0.5) * (away ? 0.5 + 0.4 * dart : 0.08);
      s.y = (Math.random() - 0.5) * (away ? 0.25 : 0.05);
      s.next = t + (away ? 0.5 + Math.random() * 0.7 : 1.2 + Math.random() * 2.5) / (1 + 2 * dart);
    }
    this._v.copy(this.camera.position);
    this._v.x += (this.pose.gaze[0] + s.x) * 1.2;
    this._v.y += (this.pose.gaze[1] + s.y) * 1.2;
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
      g.fillText(spec.label || spec.emotion || spec.talk || spec.gesture || 'reposo', x + 8, y + 20);
    });
    Object.assign(this, { state: keep.state, emotion: 'neutral', gestures: [] });
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
