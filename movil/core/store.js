// Port de companion/store.py (mensajes, recuerdos y resúmenes) y de state.py (ajustes), guardados con kv.
import { kv } from './platform.js';

let db = { next: 1, nextMem: 1, messages: [], memories: [], summaries: [] };
let saveTimer = 0;
const now = () => Date.now() / 1000;

export const PRIVATE_FACT_RE = /\b(contrase[nñ]a|password|passwd|clave\s+secreta|api[\s_-]?key|token|seed\s*phrase|cvv|pin\s+bancario|iban|dni|pasaporte)\b|\b(sk-[A-Za-z0-9_-]{16,}|AIza[0-9A-Za-z_-]{25,}|gsk_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b|\b(?:\d[ -]*?){13,19}\b/i;

export function isPrivateFact(text) {
  return PRIVATE_FACT_RE.test(String(text || ''));
}

function normalizeText(s) {
  return String(s || '').toLowerCase().normalize('NFD').replace(/\p{Mn}/gu, '').normalize('NFC');
}

function ensureMemoryIds() {
  let maxId = Number(db.nextMem || 1) - 1;
  for (const m of db.memories || []) {
    if (!m.id) { maxId += 1; m.id = maxId; }
    else if (m.id > maxId) maxId = m.id;
    if (typeof m.pinned !== 'boolean') m.pinned = false;
  }
  db.nextMem = maxId + 1;
}

export async function load() {
  db = await kv.get('store', db);
  ensureMemoryIds();
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
  fact = String(fact || '').trim().replace(/\.+$/, '').trim();
  if (!fact || isPrivateFact(fact)) return false;
  ensureMemoryIds();
  const lower = fact.toLowerCase();
  if (db.memories.some((m) => m.fact.replace(/\.+$/, '').toLowerCase() === lower)) return false;
  const id = db.nextMem++;
  db.memories.push({ id, fact, ts: now(), pinned: false });
  if (db.memories.length > 200) {
    const idx = db.memories.findIndex((m) => !m.pinned);
    if (idx >= 0) db.memories.splice(idx, 1);
  }
  save();
  return true;
}

export function updateMemory(id, { content, pinned } = {}) {
  ensureMemoryIds();
  const item = db.memories.find((m) => m.id === Number(id));
  if (!item) return false;
  if (content !== undefined) {
    const clean = String(content || '').trim().replace(/\.+$/, '').trim();
    if (!clean || isPrivateFact(clean)) return false;
    item.fact = clean;
  }
  if (typeof pinned === 'boolean') item.pinned = pinned;
  save();
  return true;
}

export const memories = (limit = 40) => {
  ensureMemoryIds();
  const pinned = db.memories.filter((m) => m.pinned).map((m) => m.fact);
  const restCap = Math.max(0, limit - pinned.length);
  const unpinned = db.memories.filter((m) => !m.pinned).slice(-restCap).map((m) => m.fact);
  return [...pinned, ...unpinned];
};

export function diary(query = '') {
  ensureMemoryIds();
  const q = normalizeText(query).trim();
  const fmt = (ts) => {
    const d = new Date((ts || 0) * 1000);
    return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;
  };
  const items = db.memories
    .filter((m) => !q || normalizeText(m.fact).includes(q))
    .map((m) => ({ id: m.id, content: m.fact, pinned: !!m.pinned, ts: m.ts }))
    .sort((a, b) => Number(b.pinned) - Number(a.pinned));
  const sums = db.summaries
    .slice(-50)
    .filter((s) => !q || normalizeText(s.text).includes(q))
    .map((s) => ({ text: s.text, date: fmt(s.ts) }));
  return { items, diary: sums, can_undo: false };
}

export function exportMemories() {
  ensureMemoryIds();
  return {
    memories: db.memories.filter((m) => !isPrivateFact(m.fact)).map((m) => ({ content: m.fact, pinned: !!m.pinned, ts: m.ts })),
    summaries: db.summaries.map((s) => ({ text: s.text, ts: s.ts })),
  };
}

export function importMemories(list = [], merge = true) {
  ensureMemoryIds();
  if (!merge) db.memories = [];
  let added = 0;
  for (const raw of Array.isArray(list) ? list : []) {
    const content = String((raw && (raw.content || raw.fact)) || '').trim().replace(/\.+$/, '').trim();
    if (!content || isPrivateFact(content)) continue;
    const pinned = !!(raw && raw.pinned);
    const lower = content.toLowerCase();
    const existing = db.memories.find((m) => m.fact.replace(/\.+$/, '').toLowerCase() === lower);
    if (existing) {
      if (pinned) existing.pinned = true;
      continue;
    }
    db.memories.push({ id: db.nextMem++, fact: content, ts: Number(raw.ts) || now(), pinned });
    added += 1;
  }
  save();
  return added;
}

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
  db = { next: db.next, nextMem: 1, messages: [], memories: [], summaries: [] };
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
