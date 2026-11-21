// La cara por partes (17 nov 2026). Las expresiones de VRM (feliz, triste, enfado…) mueven toda la cara a la vez, así
// que todas las alegrías son la misma alegría. Los modelos hechos con VRoid traen además formas sueltas para cejas,
// ojos y boca (Fcl_BRW_*, Fcl_EYE_*, Fcl_MTH_*): aquí se registran como expresiones propias («p_…») y cada emoción
// se arma combinándolas (ojos alegres con media sonrisa, cejas de pena con boca pequeña…). Encima van microgestos
// al azar —una ceja que sube, ojos que se entrecierran, una sonrisita— como en TalkingHead (MIT, met4citizen),
// más seguidos al hablar y marcados por la voz. Los modelos sin esas formas siguen con las expresiones de siempre.
//
// ARKit (17 nov 2026): los modelos con las 52 formas de ARKit («Perfect Sync»: browInnerUp, mouthSmileLeft, jawOpen…)
// arman cada parte con varias de ellas (ARKIT_PARTS), así que todo lo que usa partes (emociones, microgestos,
// pasatiempos, sueño) les sirve tal cual. Además tienen partes propias (`ak…`): media sonrisa de un lado, una sola ceja,
// labios apretados, mejillas hinchadas, nariz arrugada y la forma de los labios al hablar. Orden: ARKit, VRoid, presets.
import { VRMExpression, VRMExpressionMorphTargetBind } from '@pixiv/three-vrm';

// Nuestro nombre → forma de VRoid.
const PARTS = {
  brwAngry: 'Fcl_BRW_Angry', brwFun: 'Fcl_BRW_Fun', brwJoy: 'Fcl_BRW_Joy', brwSorrow: 'Fcl_BRW_Sorrow', brwSurprised: 'Fcl_BRW_Surprised',
  eyeAngry: 'Fcl_EYE_Angry', eyeFun: 'Fcl_EYE_Fun', eyeJoy: 'Fcl_EYE_Joy', eyeJoyL: 'Fcl_EYE_Joy_L', eyeJoyR: 'Fcl_EYE_Joy_R',
  eyeSorrow: 'Fcl_EYE_Sorrow', eyeSurprised: 'Fcl_EYE_Surprised', eyeSpread: 'Fcl_EYE_Spread',
  mthUp: 'Fcl_MTH_Up', mthDown: 'Fcl_MTH_Down', mthAngry: 'Fcl_MTH_Angry', mthSmall: 'Fcl_MTH_Small', mthLarge: 'Fcl_MTH_Large',
  mthFun: 'Fcl_MTH_Fun', mthJoy: 'Fcl_MTH_Joy', mthSorrow: 'Fcl_MTH_Sorrow', mthSurprised: 'Fcl_MTH_Surprised',
  mthFangL: 'Fcl_MTH_SkinFung_L', mthFangR: 'Fcl_MTH_SkinFung_R',
};
export const PART_KEYS = Object.keys(PARTS);

// Cada parte con las formas de ARKit (nombre → peso). Pesos revisados con la hoja de contactos en Test-Chan (CC0).
const both = (base, w) => ({ [base + 'Left']: w, [base + 'Right']: w });
const ARKIT_PARTS = {
  brwAngry: { ...both('browDown', 0.9), ...both('noseSneer', 0.12) },
  brwFun: { ...both('browOuterUp', 0.35), browInnerUp: 0.12 },
  brwJoy: { ...both('browOuterUp', 0.6), browInnerUp: 0.45 },
  brwSorrow: { browInnerUp: 0.9, ...both('browDown', 0.22) },
  brwSurprised: { browInnerUp: 0.8, ...both('browOuterUp', 0.9) },
  eyeAngry: { ...both('eyeSquint', 0.6), ...both('eyeBlink', 0.12) },
  eyeFun: { ...both('eyeSquint', 0.45), ...both('cheekSquint', 0.45), ...both('eyeBlink', 0.22) },
  eyeJoy: { ...both('eyeBlink', 0.75), ...both('cheekSquint', 0.6) },
  eyeJoyL: { eyeBlinkLeft: 0.9, cheekSquintLeft: 0.5 },
  eyeJoyR: { eyeBlinkRight: 0.9, cheekSquintRight: 0.5 },
  eyeSorrow: { ...both('eyeBlink', 0.3), ...both('eyeSquint', 0.15) },
  eyeSurprised: both('eyeWide', 0.9),
  eyeSpread: both('eyeWide', 0.5),
  mthUp: { ...both('mouthUpperUp', 0.4), mouthShrugUpper: 0.3 },
  mthDown: { ...both('mouthFrown', 0.6), ...both('mouthLowerDown', 0.2) },
  mthAngry: { ...both('mouthFrown', 0.5), ...both('mouthPress', 0.5), ...both('mouthStretch', 0.25) },
  mthSmall: { mouthPucker: 0.45, ...both('mouthPress', 0.2) },
  mthLarge: { jawOpen: 0.4, ...both('mouthStretch', 0.3) },
  mthFun: { ...both('mouthSmile', 0.7), ...both('cheekSquint', 0.15) },
  mthJoy: { ...both('mouthSmile', 0.9), jawOpen: 0.25, ...both('mouthUpperUp', 0.15) },
  mthSorrow: { ...both('mouthFrown', 0.7), mouthShrugLower: 0.4, ...both('mouthPress', 0.2) },
  mthSurprised: { jawOpen: 0.45, mouthFunnel: 0.45 },
  mthFangL: { mouthSmileLeft: 0.45, mouthUpperUpLeft: 0.4 },
  mthFangR: { mouthSmileRight: 0.45, mouthUpperUpRight: 0.4 },
  // Solo ARKit.
  akSmirkL: { mouthSmileLeft: 0.6, mouthDimpleLeft: 0.4, cheekSquintLeft: 0.3 },
  akSmirkR: { mouthSmileRight: 0.6, mouthDimpleRight: 0.4, cheekSquintRight: 0.3 },
  akBrowL: { browOuterUpLeft: 0.85, browInnerUp: 0.2, browDownRight: 0.15 },
  akBrowR: { browOuterUpRight: 0.85, browInnerUp: 0.2, browDownLeft: 0.15 },
  akPress: { ...both('mouthPress', 0.7), mouthRollLower: 0.2 },
  akPuff: { cheekPuff: 0.7, mouthPucker: 0.25 },
  akSneer: { ...both('noseSneer', 0.6), ...both('mouthUpperUp', 0.2) },
  akDimple: both('mouthDimple', 0.6),
  // La forma de los labios al hablar (avatar.js las mueve con la voz): redondos (o, u) y cerrados (p, b, m).
  akFunnel: { mouthFunnel: 1 },
  akPucker: { mouthPucker: 1 },
  akLips: { ...both('mouthPress', 0.6), mouthRollLower: 0.3, mouthRollUpper: 0.2 },
};
// Las que tiene que traer un modelo para contar como ARKit (si falta alguna, se usa lo siguiente).
const ARKIT_NEED = ['browInnerUp', 'browDownLeft', 'eyeBlinkLeft', 'eyeSquintLeft', 'eyeWideLeft', 'cheekSquintLeft',
  'jawOpen', 'mouthSmileLeft', 'mouthFrownLeft', 'mouthPucker', 'mouthFunnel', 'mouthPressLeft'];
// Las de los labios al hablar: avatar.js las pone con la voz, no con la emoción.
export const LIP_PARTS = ['akFunnel', 'akPucker', 'akLips'];

// Cada emoción, por partes (pesos revisados con la hoja de contactos en los modelos de VRoid). Cuando habla, la boca
// cede sitio a las vocales (avatar.js baja las `mth…`).
export const EMO_PARTS = {
  neutral: {},
  feliz: { brwFun: 0.6, eyeFun: 0.3, eyeJoy: 0.2, mthFun: 0.65 },
  emocionada: { brwJoy: 0.8, eyeJoy: 0.45, eyeSpread: 0.2, mthJoy: 0.6, mthFun: 0.25 },
  timida: { brwSorrow: 0.45, eyeFun: 0.3, mthSmall: 0.45, mthFun: 0.2 },
  sonrojada: { brwSorrow: 0.35, eyeJoy: 0.3, mthFun: 0.35, mthSmall: 0.3 },
  triste: { brwSorrow: 0.85, eyeSorrow: 0.6, mthSorrow: 0.45, mthDown: 0.25 },
  molesta: { brwAngry: 0.8, eyeAngry: 0.45, mthAngry: 0.5, mthSmall: 0.15, akSneer: 0.25, akPuff: 0.15 },
  sorprendida: { brwSurprised: 0.9, eyeSurprised: 0.7, mthSurprised: 0.5 },
  pensativa: { brwSorrow: 0.2, brwAngry: 0.12, eyeAngry: 0.15, mthSmall: 0.4, mthDown: 0.12, akPress: 0.3, akBrowL: 0.25 },
  carinosa: { brwFun: 0.6, eyeFun: 0.5, eyeJoy: 0.18, mthFun: 0.6 },
  enamorada: { brwSorrow: 0.3, eyeJoy: 0.4, mthFun: 0.5, mthSmall: 0.15 },
  nerviosa: { brwSorrow: 0.6, eyeSurprised: 0.22, mthSmall: 0.4, mthDown: 0.2 },
  asustada: { brwSorrow: 0.65, brwSurprised: 0.3, eyeSurprised: 0.55, mthSurprised: 0.3, mthSmall: 0.2 },
  confundida: { brwSurprised: 0.3, brwAngry: 0.2, eyeAngry: 0.12, mthSmall: 0.35, mthDown: 0.18, akBrowR: 0.45, akSmirkL: 0.15 },
};
// Lo que solo tienen los modelos ARKit, sumado a la emoción (las claves `ak…` no existen en los demás y se ignoran).
for (const [emo, extra] of Object.entries({
  feliz: { akDimple: 0.3 }, carinosa: { akDimple: 0.25, akSmirkL: 0.1 }, timida: { akPress: 0.2 }, nerviosa: { akPress: 0.3 },
  sonrojada: { akDimple: 0.2 }, triste: { akPress: 0.15 },
})) Object.assign(EMO_PARTS[emo], extra);

// Microgestos: { partes, cuánto dura, en qué emociones (vacío = todas), peso relativo }. Duran poco y se mezclan
// encima de la emoción.
const MICRO = [
  { name: 'cejas', parts: { brwSurprised: 0.35 }, dur: [0.35, 0.7], weight: 3, speaking: 2 },
  { name: 'entrecerrar', parts: { eyeAngry: 0.18, eyeFun: 0.12 }, dur: [0.6, 1.4], weight: 1.5 },
  { name: 'sonrisita', parts: { mthFun: 0.3, eyeFun: 0.15 }, dur: [0.6, 1.5], weight: 2, not: ['triste', 'molesta', 'asustada'] },
  { name: 'labios', parts: { mthSmall: 0.3 }, dur: [0.4, 1.0], weight: 1, idleOnly: true },
  { name: 'pena', parts: { brwSorrow: 0.3 }, dur: [0.5, 1.1], weight: 1, only: ['triste', 'nerviosa', 'timida', 'pensativa', 'confundida'] },
  { name: 'colmillo', parts: { mthFangL: 0.6, mthFun: 0.2 }, dur: [0.7, 1.4], weight: 0.6, only: ['feliz', 'emocionada', 'carinosa'] },
  // Solo ARKit (necesitan sus partes: el filtro de Micro.step los quita en los demás modelos).
  { name: 'media sonrisa', parts: { akSmirkL: 0.7 }, dur: [0.8, 1.8], weight: 1.6, not: ['triste', 'asustada'] },
  { name: 'una ceja', parts: { akBrowR: 0.6 }, dur: [0.5, 1.1], weight: 1.4, speaking: 2.2 },
  { name: 'apretar labios', parts: { akPress: 0.55 }, dur: [0.5, 1.2], weight: 1.2, idleOnly: true },
  { name: 'mejillas', parts: { akPuff: 0.6 }, dur: [0.6, 1.2], weight: 0.5, only: ['molesta', 'confundida', 'pensativa', 'timida'] },
  { name: 'nariz', parts: { akSneer: 0.45 }, dur: [0.4, 0.8], weight: 0.6, only: ['molesta', 'confundida'] },
];
// Los mismos, con expresiones completas, para los modelos sin partes.
const MICRO_PRESET = {
  cejas: { surprised: 0.18 }, entrecerrar: { relaxed: 0.2 }, sonrisita: { happy: 0.18 }, labios: {}, pena: { sad: 0.15 }, colmillo: { happy: 0.18 },
};

// Busca una forma por su nombre de ARKit sin importar mayúsculas ni prefijos («blendShape1.MouthSmileLeft»,
// «mouthSmile_L», «MouthSmileLeft»).
function arkitIndex(mesh, name) {
  const dict = mesh.morphTargetDictionary;
  if (name in dict) return dict[name];
  const want = name.toLowerCase(), alt = want.replace(/left$/, '_l').replace(/right$/, '_r');
  for (const [k, i] of Object.entries(dict)) {
    const n = k.toLowerCase().replace(/^.*[.:]/, '');
    if (n === want || n === alt) return i;
  }
  return -1;
}

function addArkit(vrm, em, meshes) {
  const has = (n) => meshes.some((m) => arkitIndex(m, n) >= 0);
  if (!ARKIT_NEED.every(has)) return [];
  const found = [];
  for (const [key, combo] of Object.entries(ARKIT_PARTS)) {
    const name = 'p_' + key;
    if (!em.getExpression(name)) {
      const ex = new VRMExpression(name);
      for (const [shape, w] of Object.entries(combo)) {
        for (const m of meshes) {
          const i = arkitIndex(m, shape);
          if (i >= 0) ex.addBind(new VRMExpressionMorphTargetBind({ primitives: [m], index: i, weight: w }));
        }
      }
      if (!ex.binds.length) continue;
      vrm.scene.add(ex);
      em.registerExpression(ex);
    }
    found.push(key);
  }
  found.kind = 'arkit';
  return found;
}

// Registra las partes que tenga el modelo. Devuelve la lista de las que hay (vacía si no es de VRoid).
export function addParts(vrm) {
  const em = vrm.expressionManager;
  if (!em) return [];
  const meshes = [];
  vrm.scene.traverse((o) => { if (o.isMesh && o.morphTargetDictionary) meshes.push(o); });
  const arkit = addArkit(vrm, em, meshes);
  if (arkit.length) return arkit;
  const found = [];
  for (const [key, morph] of Object.entries(PARTS)) {
    const prims = meshes.filter((m) => morph in m.morphTargetDictionary);
    if (!prims.length) continue;
    const name = 'p_' + key;
    if (!em.getExpression(name)) {
      const ex = new VRMExpression(name);
      // Mismo índice en todas las mallas de la cara (VRoid las parte por material): una unión por malla.
      for (const m of prims) ex.addBind(new VRMExpressionMorphTargetBind({ primitives: [m], index: m.morphTargetDictionary[morph], weight: 1 }));
      vrm.scene.add(ex);
      em.registerExpression(ex);
    }
    found.push(key);
  }
  // Hacen falta cejas, ojos y boca para armar emociones; si no, mejor las expresiones completas.
  const ok = ['brwFun', 'brwSorrow', 'eyeJoy', 'mthFun'].every((k) => found.includes(k));
  if (!ok) return [];
  found.kind = 'vroid';
  return found;
}

const rand = (a, b) => a + Math.random() * (b - a);

// Estado de los microgestos de un personaje.
export class Micro {
  constructor() { this.cur = null; this.next = 2; this.beatLast = 0; }

  // Elige y avanza el microgesto. t = segundos, speaking = 0..1, beat = golpe de voz (0..1). Devuelve
  // { partes → peso } (para modelos de VRoid) o { preset → peso } (para los demás).
  step(t, dt, emotion, speaking, beat, parts) {
    const out = this._out || (this._out = {});
    for (const k in out) out[k] = 0;
    // Un golpe fuerte de voz al hablar suele llevar las cejas arriba (énfasis), como cuando una persona recalca algo.
    if (speaking > 0.5 && beat > 0.55 && t - this.beatLast > 1.6 && (!this.cur || this.cur.name !== 'cejas') && Math.random() < 0.5) {
      this.beatLast = t;
      this._start(MICRO[0], t);
    }
    if (!this.cur && t > this.next) {
      const pool = MICRO.filter((m) => (!m.only || m.only.includes(emotion)) && (!m.not || !m.not.includes(emotion))
        && (!m.idleOnly || speaking < 0.3) && (parts.length ? Object.keys(m.parts).every((k) => parts.includes(k)) : !!MICRO_PRESET[m.name]));
      let total = pool.reduce((s, m) => s + (speaking > 0.5 ? m.speaking || m.weight : m.weight), 0);
      let r = Math.random() * total;
      for (const m of pool) {
        r -= speaking > 0.5 ? m.speaking || m.weight : m.weight;
        if (r <= 0) { this._start(m, t); break; }
      }
      this.next = t + (speaking > 0.5 ? rand(1.2, 3.5) : rand(2.5, 7));
    }
    const c = this.cur;
    if (c) {
      const u = (t - c.t0) / c.dur;
      if (u >= 1) { this.cur = null; return out; }
      const env = Math.sin(Math.PI * Math.min(1, u * 1.15)) ** 0.7;          // sube rápido, baja algo más despacio
      const src = parts.length ? c.m.parts : MICRO_PRESET[c.m.name];
      if (src) for (const [k, v] of Object.entries(src)) out[k] = (out[k] || 0) + v * c.amp * env;
    }
    return out;
  }

  _start(m, t) { this.cur = { m, name: m.name, t0: t, dur: rand(m.dur[0], m.dur[1]), amp: rand(0.7, 1.15) }; }
}

export const MOUTH_PARTS = PART_KEYS.filter((k) => k.startsWith('mth'));
