// Port de companion/store.py (mensajes, recuerdos y resúmenes) y de state.py (ajustes), guardados con kv.
import { kv } from './platform.js';

let db = { next: 1, messages: [], memories: [], summaries: [] };
let saveTimer = 0;
const now = () => Date.now() / 1000;

export async function load() {
  db = await kv.get('store', db);
}

function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => kv.set('store', db).catch((e) => console.warn('No pude guardar', e)), 300);
}

export function addMessage(role, text, emotion = null) {
  const id = db.next++;
  db.messages.push({ id, role, text, emotion, ts: now() });
  save();
  return id;
}

// Cuándo fue el último mensaje (segundos), para «hace días que no hablaban».
export const lastTs = () => (db.messages.length ? db.messages[db.messages.length - 1].ts : null);

export function deleteMessage(id) {
  db.messages = db.messages.filter((m) => m.id !== id);
  save();
}

// Primer id de los últimos `keep` mensajes (desde ahí se manda el historial al LLM).
export function anchor(keep) {
  const m = db.messages[db.messages.length - Math.max(1, keep)];
  return m ? m.id : (db.messages[0] ? db.messages[0].id : 0);
}

export const since = (firstId) => db.messages.filter((m) => m.id >= firstId).map((m) => [m.id, m.role, m.text]);

export function addMemory(fact) {
  fact = fact.trim().replace(/\.+$/, '').trim();
  const lower = fact.toLowerCase();
  if (!fact || db.memories.some((m) => m.fact.replace(/\.+$/, '').toLowerCase() === lower)) return;
  db.memories.push({ fact, ts: now() });
  save();
}

export const memories = (limit = 40) => db.memories.slice(-limit).map((m) => m.fact);

export function unsummarized(beforeId, limit = 40) {
  const last = db.summaries.reduce((a, s) => Math.max(a, s.last_id), 0);
  return db.messages.filter((m) => m.id > last && m.id < beforeId).slice(0, limit).map((m) => [m.id, m.role, m.text, m.ts]);
}

export function addSummary(text, firstId, lastId, ts) {
  db.summaries.push({ text: text.trim(), first_id: firstId, last_id: lastId, ts });
  // Lo ya resumido hace mucho no hace falta guardarlo entero: el teléfono tiene menos sitio que la PC.
  const keepFrom = db.summaries.length > 4 ? db.summaries[db.summaries.length - 4].first_id : 0;
  if (db.messages.length > 600) db.messages = db.messages.filter((m) => m.id >= keepFrom);
  save();
}

export const summaries = (limit = 10) => db.summaries.slice(-limit).map((s) => [s.text, s.ts]);

const STOP = new Set(`ahora algo algun alguna algunos antes aqui asi aunque bien cada casi como con contra cosa cosas cual
cuando de del desde donde dijo dice durante ella ellas ellos entre era eran esa ese eso esta estaba estado estar este
esto estos fue fueron gusta habia hablar hablaron hace hacer hasta hoy mas mismo mucho muy nada nadie nos nosotros nunca
otra otro para pero poco porque puede pues que quien quiere sabe sido siempre sobre solo tambien tanto tener tiene todo
todos tras tuvo una unas uno unos usted vamos vez yo`.split(/\s+/));

function keys(text) {
  const s = text.toLowerCase().normalize('NFD').replace(/\p{Mn}/gu, '').normalize('NFC');
  return new Set((s.match(/[a-zñ0-9]{4,}/g) || []).filter((w) => !STOP.has(w)).map((w) => w.slice(0, 5)));
}

// Igual que store.relevant_summaries: resúmenes antiguos que comparten dos palabras poco comunes.
export function relevantSummaries(query, skipRecent = 8, limit = 2, ignore = '') {
  const ig = keys(ignore);
  let words = new Set([...keys(query || '')].filter((w) => !ig.has(w)));
  if (words.size < 2) return [];
  const every = [...db.summaries].reverse().map((s) => [keys(s.text), s.text, s.ts]);
  const threshold = Math.max(2, Math.floor(every.length / 10));
  words = new Set([...words].filter((w) => every.filter(([k]) => k.has(w)).length <= threshold));
  if (words.size < 2) return [];
  return every.slice(skipRecent)
    .map(([k, text, ts]) => [[...words].filter((w) => k.has(w)).length, ts, text])
    .sort((a, b) => b[0] - a[0] || b[1] - a[1])
    .filter(([n]) => n >= 2).slice(0, limit).map(([, ts, text]) => [text, ts]);
}

export function deleteMemory(fact) {
  db.memories = db.memories.filter((m) => m.fact !== fact);
  save();
}

export function forgetAll() {
  db = { next: db.next, messages: [], memories: [], summaries: [] };
  save();
}

// ---------------------------------------------------------------- ajustes (equivale a data/settings.json)
let settings = {};

export async function loadSettings() {
  settings = await kv.get('settings', {});
}

export const getSettings = () => settings;

export async function saveSettings(changes) {
  settings = { ...settings, ...changes };
  await kv.set('settings', settings);
}

export async function clearSettings() {
  settings = {};
  await kv.set('settings', settings);
}
