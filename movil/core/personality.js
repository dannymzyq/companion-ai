// Personalidades (port de companion/personality.py): el catálogo incluido (personas/personalidades.json, que el
// paquete copia a /data) y las propias del usuario, guardadas en los ajustes: {personality: {active, custom: []}}.
// La elegida cambia la forma de ser y de hablar; nombre, edad, voz, límites y +18 siguen siendo los de la ficha.
import { EMOTIONS } from './prompt.js';
import * as store from './store.js';

export const DEFAULT = 'confianza';
export const MAX_CUSTOM = 30;
export const TRAITS = {
  warmth: { label: 'Calidez', low: 'Poca', high: 'Mucha', default: 0.7 },
  playfulness: { label: 'Humor', low: 'Nada', high: 'Mucho', default: 0.5 },
  sarcasm: { label: 'Ironía', low: 'Nada', high: 'Mucha', default: 0.2 },
  shyness: { label: 'Timidez', low: 'Nada', high: 'Mucha', default: 0.2 },
  curiosity: { label: 'Curiosidad', low: 'Poca', high: 'Pregunta por todo', default: 0.6 },
  energy: { label: 'Energía', low: 'Calma', high: 'A tope', default: 0.5 },
  expressiveness: { label: 'Expresividad', low: 'Lo guarda', high: 'Lo muestra todo', default: 0.6 },
  assertiveness: { label: 'Opiniones propias', low: 'Te da la razón', high: 'Discute y opina', default: 0.5 },
  talkativeness: { label: 'Cuánto habla', low: 'Lo justo', high: 'Se explaya', default: 0.4 },
};
export const FORMALITY = { casual: 'Casual', neutral: 'Neutro', formal: 'Formal' };
const LIMITS = { name: 40, summary: 120, description: 700, speech: 400, item: 60, example: 200, opinion: 160 };
const JUNK = /[\x00-\x08\x0b-\x1f\x7f[\]{}<>]+/g;

let catalog = [];
export function setCatalog(raw) {
  catalog = (raw || []).map((p) => ({ ...clean(p, true), id: p.id, builtin: true }));
}

function text(value, limit, lines = false) {
  let s = String(value ?? '');
  s = (lines ? s.replace(/\r/g, '') : s.replace(/\n/g, ' ')).replace(JUNK, ' ');
  return s.replace(/[ \t]+/g, ' ').trim().slice(0, limit);
}
function items(value, n, limit) {
  if (typeof value === 'string') value = value.split(/[,;\n]/);
  const out = [];
  for (const v of value || []) {
    const t = text(v, limit);
    if (t && !out.some((x) => x.toLowerCase() === t.toLowerCase())) out.push(t);
  }
  return out.slice(0, n);
}
const lines = (v) => (typeof v === 'string' ? v.split('\n') : v);

export class PersonalityError extends Error {}

export function clean(raw, partial = false) {
  const name = text(raw.name, LIMITS.name);
  if (!name && !partial) throw new PersonalityError('Ponle un nombre a la personalidad.');
  const tin = raw.traits && typeof raw.traits === 'object' ? raw.traits : {};
  const traits = {};
  for (const [k, meta] of Object.entries(TRAITS)) {
    const x = Number.parseFloat(tin[k] ?? meta.default);
    traits[k] = Number.isFinite(x) ? Math.round(Math.min(Math.max(x, 0), 1) * 100) / 100 : meta.default;
  }
  return {
    name, summary: text(raw.summary, LIMITS.summary), description: text(raw.description, LIMITS.description, true),
    traits, formality: FORMALITY[raw.formality] ? raw.formality : 'casual',
    speech: text(raw.speech, LIMITS.speech, true),
    catchphrases: items(raw.catchphrases, 4, 40), likes: items(raw.likes, 8, LIMITS.item),
    dislikes: items(raw.dislikes, 6, LIMITS.item),
    base_mood: EMOTIONS.includes(raw.base_mood) ? raw.base_mood : 'neutral',
    emotions: items(raw.emotions, 4, 20).filter((e) => EMOTIONS.includes(e)).slice(0, 3),
    examples: items(lines(raw.examples), 5, LIMITS.example),
    opinions: items(lines(raw.opinions), 5, LIMITS.opinion),
    reactions: items(lines(raw.reactions), 4, LIMITS.opinion),
  };
}

const saved = () => { const p = store.getSettings().personality; return p && typeof p === 'object' ? p : {}; };
export const custom = () => (saved().custom || []).filter((c) => c && String(c.id || '').startsWith('c_'))
  .map((c) => ({ ...clean(c, true), id: c.id, builtin: false, from: c.from || '' }));
export const all = () => [...catalog, ...custom()];
export const find = (pid) => all().find((p) => p.id === pid) || null;
export function activeId() { const pid = saved().active || DEFAULT; return find(pid) ? pid : DEFAULT; }
export const active = () => find(activeId()) || catalog[0] || null;

export async function select(pid) {
  if (!find(pid)) throw new PersonalityError('Esa personalidad no existe.');
  await store.saveSettings({ personality: { ...saved(), active: pid } });
}

export async function saveCustom(raw) {
  const data = clean(raw);
  const s = saved();
  let list = (s.custom || []).filter((c) => c && typeof c === 'object');
  let pid = String(raw.id || '');
  if (pid.startsWith('c_') && list.some((c) => c.id === pid)) {
    list = list.map((c) => (c.id === pid ? { ...data, id: pid, from: c.from || '' } : c));
  } else {
    if (list.length >= MAX_CUSTOM) throw new PersonalityError(`Ya tienes ${MAX_CUSTOM} personalidades propias: borra alguna antes.`);
    const base = String(raw.from || (find(pid) ? pid : ''));
    pid = 'c_' + [...crypto.getRandomValues(new Uint8Array(4))].map((b) => b.toString(16).padStart(2, '0')).join('');
    list.push({ ...data, id: pid, from: find(base) ? base : '' });
  }
  await store.saveSettings({ personality: { ...s, custom: list, active: pid } });
  return find(pid);
}

export async function deleteCustom(pid) {
  const s = saved();
  const gone = (s.custom || []).find((c) => c && c.id === pid) || {};
  const list = (s.custom || []).filter((c) => c && c.id !== pid);
  let act = s.active;
  if (act === pid) act = catalog.some((p) => p.id === gone.from) ? gone.from : DEFAULT;
  await store.saveSettings({ personality: { ...s, custom: list, active: act } });
}

export const pub = () => ({ active: activeId(), personalities: all(), default: DEFAULT, traits: TRAITS, formality: FORMALITY,
  emotions: EMOTIONS, max_custom: MAX_CUSTOM });

export function temper(p) {
  const t = p.traits;
  return { shy: t.shyness, warm: t.warmth, sharp: Math.round(Math.max(t.sarcasm, t.assertiveness * 0.8) * 100) / 100 };
}

// La ficha común con la forma de ser elegida (nunca nombre, edad, voz, rol, límites ni +18).
export function apply(persona, p = active()) {
  if (!p) return persona;
  const ss = persona.speech_style || {};
  return { ...persona, traits: { ...(persona.traits || {}), ...p.traits },
    speech_style: { ...ss, formality: p.formality, notes: p.speech || ss.notes || '', catchphrases: p.catchphrases },
    backstory: p.description || persona.backstory || '', interests: p.likes.length ? p.likes : (persona.interests || []),
    personality: p };
}
