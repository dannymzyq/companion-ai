// El cerebro. Nube: Gemini por su API compatible con OpenAI, con el mismo relevo que companion/llm.py
// (GEMINI_FALLBACK; el trabajo de fondo empieza por BACKGROUND_MODEL). Teléfono: el modelo local del nativo
// (fase 3). Con la nube nunca se cae al modelo del teléfono: allí no hay respaldo local.
import { kv, lines, request } from './platform.js';
import { getSettings } from './store.js';
import { elegidos, pensar } from './local.js';

export const PRESETS = {
  gemini: { name: 'Google Gemini', base: 'https://generativelanguage.googleapis.com/v1beta/openai',
    keys: 'https://aistudio.google.com/apikey', note: 'Tiene capa gratuita. Probado con este companion.' },
  openai: { name: 'OpenAI', base: 'https://api.openai.com/v1', keys: 'https://platform.openai.com/api-keys',
    note: 'De pago. Sin probar aquí.' },
  openrouter: { name: 'OpenRouter', base: 'https://openrouter.ai/api/v1', keys: 'https://openrouter.ai/keys',
    note: 'Muchos modelos con una sola clave. Sin probar aquí.' },
  groq: { name: 'Groq', base: 'https://api.groq.com/openai/v1', keys: 'https://console.groq.com/keys',
    note: 'Muy rápido. Sin probar aquí.' },
  mistral: { name: 'Mistral', base: 'https://api.mistral.ai/v1', keys: 'https://console.mistral.ai/api-keys',
    note: 'Sin probar aquí.' },
  custom: { name: 'Otro (compatible con OpenAI)', base: '', keys: '', note: 'Escribe la dirección de su API.' },
};
export const GEMINI_MODEL = 'gemini-3.6-flash';
export const GEMINI_FALLBACK = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite', 'gemma-4-26b-a4b-it'];
export const BACKGROUND_MODEL = 'gemma-4-26b-a4b-it';
const REASONING = 'minimal';
export const KEY = 'cloud_key';           // nombre del secreto en el llavero

export class LLMError extends Error {}
class QuotaExceeded extends Error {
  constructor(wait, daily) { super('cuota'); this.wait = wait; this.daily = daily; }
}

let blocked = {};                          // modelo → hasta cuándo (ms) no se usa (cuota agotada)
const noReasoning = new Set();
const notices = [];
let hasKey = false;
const local = { simulado: false, listo: false };     // modo teléfono: cerebro simulado (simulador) y si está bajado
export const setLocal = (x) => Object.assign(local, x);

export async function init(keyPresent) {
  hasKey = keyPresent;
  const saved = await kv.get('cuota', {});
  blocked = Object.fromEntries(Object.entries(saved).filter(([, t]) => t > Date.now()));
}
export const setHasKey = (v) => { hasKey = v; };
export const keyPresent = () => hasKey;

export function popNotices() { return notices.splice(0); }

function block(model, waitS) {
  blocked[model] = Date.now() + waitS * 1000;
  kv.set('cuota', blocked).catch(() => {});
}
export function resetCloud() { blocked = {}; noReasoning.clear(); kv.set('cuota', {}).catch(() => {}); }
const usable = (m) => !(blocked[m] > Date.now());

export function cloud() {
  const c = getSettings().cloud || {};
  const preset = PRESETS[c.preset] ? c.preset : 'gemini';
  return { preset, base: (c.base || PRESETS[preset].base).replace(/\/+$/, ''), model: c.model || '' };
}

export function geminiModels(background = false) {
  const c = cloud();
  if (c.preset !== 'gemini') return c.model ? [c.model] : [];
  const main = c.model || GEMINI_MODEL;
  let chain = [main, ...GEMINI_FALLBACK.filter((m) => m !== main)];
  if (background) chain = [BACKGROUND_MODEL, ...chain.filter((m) => m !== BACKGROUND_MODEL)];
  return chain;
}

export const isCloud = () => (getSettings().mode || 'nube') === 'nube';

export function status() {
  if (isCloud()) {
    const models = geminiModels();
    const ready = hasKey && models.length > 0;
    const current = models.find(usable) || null;
    let detail = ready ? '' : 'Falta la clave del cerebro en la nube: ponla en Ajustes › Cerebro';
    if (ready && current !== models[0]) detail = `Cuota de ${models[0]} agotada por ahora`;
    return { provider: 'gemini', model: current || models[0] || GEMINI_MODEL, ready: ready && !!current, detail };
  }
  const m = elegidos().cerebro;
  if (local.simulado) return { provider: 'local', model: `${m.nombre} (simulado)`, ready: true, detail: 'En el simulador el cerebro es de prueba' };
  return { provider: 'local', model: m.nombre, ready: local.listo,
    detail: local.listo ? '' : 'Falta descargar el cerebro del teléfono (Ajustes › Cerebro)' };
}

// Respuesta completa, sin voz (resúmenes).
export async function complete(messages, maxTokens = 220, background = true) {
  let out = '';
  for await (const p of streamChat(messages, { temperature: 0.3, top_p: 0.9, max_tokens: maxTokens }, background)) out += p;
  return out;
}

export async function* streamChat(messages, sampling, background = false) {
  if (!isCloud()) {
    if (!local.simulado && !local.listo) throw new LLMError('Falta descargar el cerebro del teléfono (Ajustes › Cerebro).');
    try {
      yield* pensar(messages, sampling, { simulado: local.simulado });
    } catch (e) {
      throw new LLMError(`El cerebro del teléfono falló: ${e.message}`);
    }
    return;
  }
  const chain = geminiModels(background);
  if (!hasKey || !chain.length) {
    throw new LLMError('Falta la clave del cerebro en la nube. Ponla en Ajustes › Cerebro.');
  }
  for (const model of chain) {
    if (!usable(model)) continue;
    let sent = false;
    try {
      for await (const piece of gemini(model, messages, sampling)) { sent = true; yield piece; }
      return;
    } catch (e) {
      if (e instanceof QuotaExceeded) {
        block(model, e.wait);
        const nxt = chain.find(usable) || null;
        if (!background && e.daily) {
          notices.push(`Se agotó la cuota gratuita de hoy de ${model}. `
            + (nxt ? `Sigo con ${nxt}.` : 'No quedan modelos de Gemini por hoy.'));
        }
        continue;
      }
      if (background && model === BACKGROUND_MODEL && !sent) { block(model, 3600); continue; }
      throw e;
    }
  }
  throw new LLMError(background ? 'Se agotó la cuota del cerebro en la nube por ahora; el trabajo de fondo espera a que vuelva.'
    : 'Se agotó la cuota del cerebro en la nube por ahora. Vuelve a probar más tarde o revisa el plan de tu proveedor.');
}

async function* gemini(model, messages, sampling) {
  const c = cloud();
  const body = { model, messages, stream: true, temperature: sampling.temperature, top_p: sampling.top_p,
    max_tokens: sampling.max_tokens + 256 };
  if (c.preset === 'gemini' && !noReasoning.has(model)) body.reasoning_effort = REASONING;
  for (const attempt of [1, 2]) {
    let status = 0, detail = '';
    try {
      for await (const item of lines({ url: `${c.base}/chat/completions`, body: JSON.stringify(body), auth: KEY,
        headers: { 'Content-Type': 'application/json' } })) {
        if (item.status !== undefined) { status = item.status; console.info(`Nube ${model}: ${status}`); continue; }
        if (status !== 200) { detail += item.line + '\n'; continue; }
        const line = item.line;
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (data === '[DONE]') return;
        let choices;
        try { choices = JSON.parse(data).choices || []; } catch { continue; }
        const piece = choices.length ? (choices[0].delta || {}).content : null;
        if (piece) yield piece;
      }
    } catch (e) {
      if (e instanceof QuotaExceeded || e instanceof LLMError) throw e;
      throw new LLMError('No pude conectar con el cerebro en la nube. Revisa tu conexión a internet.');
    }
    if (status === 200) return;
    const low = detail.toLowerCase();
    if (attempt === 1 && status === 400 && (low.includes('reasoning') || low.includes('thinking'))) {
      noReasoning.add(model);
      delete body.reasoning_effort;
      continue;
    }
    if (status === 429) {
      const wait = /"retryDelay":\s*"(\d+)/.exec(detail);
      const daily = low.includes('perday');
      throw new QuotaExceeded(wait ? Number(wait[1]) : (daily ? 12 * 3600 : 60), daily);
    }
    console.warn(`Nube ${status} (${model})`);
    if (status === 401 || status === 403 || low.includes('api key')) throw new LLMError('El proveedor rechazó la clave de API. Revísala en Ajustes › Cerebro.');
    if (status === 404) throw new LLMError(`El modelo «${model}» no existe o no está disponible para tu clave. Elige otro en Ajustes › Cerebro.`);
    throw new LLMError(`El cerebro en la nube devolvió un error (${status}).`);
  }
}

// Comprueba una clave antes de guardarla. `key` vacía: la guardada en el llavero.
export async function checkCloud(base, key) {
  let r;
  try {
    r = await request({ url: `${base.replace(/\/+$/, '')}/models`, auth: key ? null : KEY, bearer: key || null, timeout: 15 });
  } catch {
    throw new LLMError('No pude conectar con esa dirección.');
  }
  if ([400, 401, 403].includes(r.status)) throw new LLMError('El proveedor rechazó la clave. Cópiala de nuevo, completa.');
  if (r.status !== 200) throw new LLMError(`El proveedor respondió ${r.status} al comprobar la clave.`);
  let ids = [];
  try { ids = (JSON.parse(r.body).data || []).map((m) => String(m.id || '').replace(/^models\//, '')); } catch { /* sin lista */ }
  return ids.filter(Boolean).sort().slice(0, 400);
}
