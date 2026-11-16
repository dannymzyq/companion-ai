// Lo que en la PC responde companion/server.py en /api/*, hecho en el teléfono. Mismas formas de respuesta, para
// que web/js no cambie; lo que no existe aquí (acciones, Ollama, voz completa, VRM propios) responde vacío o 422.
import * as llm from './llm.js';
import { secrets } from './platform.js';
import * as store from './store.js';
import { describeUser } from './session.js';

const GENDER_IDS = ['mujer', 'hombre', 'no_binario', ''];
export const BUILTIN = [
  { id: 'avatar1', name: 'Avatar 1', note: 'Personaje incluido', file: '/models/avatar1.vrm' },
  { id: 'avatar2', name: 'Avatar 2', note: 'Personaje incluido', file: '/models/avatar2.vrm' },
  { id: 'avatar3', name: 'Avatar 3', note: 'Una esfera que cambia de color con lo que siente', file: null },
];
const ENGINES = {
  nube: { id: 'nube', name: 'Voz en la nube', vram_gb: 0, note: 'Voces neuronales de Microsoft Edge: necesita internet.' },
  ligera: { id: 'ligera', name: 'Voz ligera', vram_gb: 0, note: 'Piper, dentro del teléfono: funciona sin internet.' },
};

class HttpError extends Error { constructor(status, detail) { super(detail); this.status = status; } }

export function createApi(core) {
  const S = () => store.getSettings();

  function profile() {
    const p = S().profile || {};
    return { name: String(p.name || ''), birth_year: p.birth_year ?? null, gender: String(p.gender || '') };
  }

  function voices() {
    const chosen = S().voice;
    const list = core.voices.map((v) => ({ id: v.id, name: v.name, speaks: v.speaks === 'm' ? 'm' : 'f', tts_voice: v.tts_voice,
      default: !!v.default, note: v.note || '', custom: false, available: true, selected: false }));
    const pick = list.find((v) => v.id === chosen) || list.find((v) => v.default) || list[0];
    if (pick) pick.selected = true;
    return list;
  }
  const voice = () => voices().find((v) => v.selected) || null;
  const character = () => (voice() || { name: core.persona.name }).name;
  const engine = () => (S().voice_engine in ENGINES ? S().voice_engine : (S().mode === 'telefono' ? 'ligera' : 'nube'));
  const modelId = () => (BUILTIN.some((m) => m.id === S().model_id) ? S().model_id : 'avatar1');

  function publicCloud() {
    const c = llm.cloud();
    return { preset: c.preset, name: llm.PRESETS[c.preset].name, base: c.base, model: c.model,
      has_key: llm.keyPresent(), key_hint: llm.keyPresent() ? 'guardada' : '' };   // la clave nunca vuelve a la interfaz
  }

  function config() {
    const user = describeUser(profile());
    const cloudMode = llm.isCloud();
    const eng = engine();
    return {
      name: character(), user: profile().name, llm: llm.status(),
      adult: { active: !cloudMode && user.adult && !!(core.persona.adult || {}).enabled },
      onboarded: !!S().onboarded, profile: profile(), cloud: publicCloud(),
      voice: (voice() || {}).name || '', local_model: S().local_model || 'gemma-4-e2b',
      voice_engine: eng, voice_engine_name: ENGINES[eng].name, voice_engine_pref: eng, voice_auto: false, voice_reason: '',
      watch: { interval: 7, model: '' },
      stt: { ready: true, device: cloudMode ? 'nube' : 'telefono', model: cloudMode ? 'nube' : 'whisper', error: null,
        engine: cloudMode ? 'nube' : 'local', cloud: { groq: !!core.keys.groq, gemini: llm.keyPresent(), last: null }, restart_frees: false },
      cloud_only: cloudMode, mode: cloudMode ? 'nube' : 'telefono',
      model: true, model_id: modelId(), model_kind: modelId() === 'avatar3' ? 'orb' : 'vrm',
      barge_in: true, actions: { enabled: false, ask: false, always: [], available: false, catalog: {} },
      started: core.started, tts: core.ttsAvailable(eng), gpu: null,
    };
  }

  function setup() {
    const eng = engine();
    return {
      resources: { total_gb: 0, tier: 'telefono', ear_gb: 0, desktop_gb: 0, room: {}, engines: core.can.LIGHT_VOICE ? ENGINES : { nube: ENGINES.nube },
        recommended_engine: 'nube', recommended_model: '' },
      voice_engine: { selected: eng, in_use: eng, reason: '', auto: false, recommended: llm.isCloud() ? 'nube' : 'ligera', node: false,
        fits_now: false, light_installed: !!core.can.LIGHT_VOICE, light_size_mb: 0, light_progress: null },
      ear: { engine: llm.isCloud() ? 'nube' : 'local', groq: !!core.keys.groq, gemini: llm.keyPresent(), last: null },
      cloud_only: llm.isCloud(), onboarded: !!S().onboarded, character: character(), year: new Date().getFullYear(),
      profile: profile(), suggested_name: profile().name, provider: llm.isCloud() ? 'gemini' : 'local', cloud: publicCloud(),
      presets: Object.entries(llm.PRESETS).map(([id, v]) => ({ id, name: v.name, base: v.base, keys: v.keys, note: v.note })),
      local: { gpu: null, ollama: false, recommended: '', selected: S().local_model || '', in_use: '', models: [], others: [] },
      voices: voices(), tts: core.ttsAvailable(eng), mode: llm.isCloud() ? 'nube' : 'telefono',
    };
  }

  function cleanProfile(raw) {
    const name = String(raw.name || '').replace(/[\r\n\t[\]{}<>]+/g, ' ').trim().slice(0, 40);
    if (!name) throw new HttpError(422, 'Dime cómo quieres que te llame.');
    const year = Number.parseInt(raw.birth_year, 10);
    if (!Number.isInteger(year)) throw new HttpError(422, 'Escribe tu año de nacimiento con cuatro cifras.');
    if (year < 1900 || year > new Date().getFullYear()) throw new HttpError(422, 'Ese año de nacimiento no es válido.');
    const gender = String(raw.gender || '');
    if (!GENDER_IDS.includes(gender)) throw new HttpError(422, 'Género no reconocido.');
    return { name, birth_year: year, gender };
  }

  async function postSetup(body) {
    const changes = {};
    if (body.profile) changes.profile = cleanProfile(body.profile);
    if (body.cloud) {
      const preset = String(body.cloud.preset || 'gemini');
      if (!llm.PRESETS[preset]) throw new HttpError(422, 'Proveedor no reconocido.');
      const base = String(body.cloud.base || llm.PRESETS[preset].base).trim().replace(/\/+$/, '');
      if (!base.startsWith('https://')) throw new HttpError(422, 'La dirección de la API tiene que empezar por https://');
      const key = String(body.cloud.key || '').trim();
      const same = llm.cloud().preset === preset;
      if (!key && !(same && llm.keyPresent())) throw new HttpError(422, 'Falta la clave de API.');
      const model = String(body.cloud.model || '').trim().slice(0, 120);
      if (preset !== 'gemini' && !model) throw new HttpError(422, 'Elige el modelo que quieres usar.');
      if (key) { await secrets.set(llm.KEY, key); llm.setHasKey(true); }
      changes.cloud = { preset, base, model };
      llm.resetCloud();
    }
    if (body.voice != null) {
      if (!voices().some((v) => v.id === body.voice)) throw new HttpError(422, 'Esa voz todavía no está disponible.');
      changes.voice = body.voice;
    }
    if (body.voice_engine != null) {
      if (!(body.voice_engine in ENGINES) || (body.voice_engine === 'ligera' && !core.can.LIGHT_VOICE)) {
        throw new HttpError(422, 'Ese motor de voz no está disponible en el teléfono.');
      }
      changes.voice_engine = body.voice_engine;
    }
    if (body.mode != null || body.provider != null) {
      const mode = body.mode || (body.provider === 'local' ? 'telefono' : 'nube');
      if (!['nube', 'telefono'].includes(mode)) throw new HttpError(422, 'Modo no reconocido.');
      changes.mode = mode;
    }
    if (body.onboarded != null) changes.onboarded = !!body.onboarded;
    await store.saveSettings(changes);
    return config();
  }

  async function models() {
    return { active: modelId(), builtin: BUILTIN.map(({ id, name, note }) => ({ id, name, note, available: true })), custom: [] };
  }

  const routes = {
    'GET /api/config': () => config(),
    'POST /api/config': async (b) => { if (b.provider) await postSetup({ provider: b.provider }); return config(); },
    'GET /api/setup': () => setup(),
    'POST /api/setup': (b) => postSetup(b),
    'POST /api/setup/reset': async (b) => {
      if (b.data) {
        await store.clearSettings();
        store.forgetAll();
        await secrets.remove(llm.KEY).catch(() => {});
        llm.setHasKey(false);
        llm.resetCloud();
      } else {
        await store.saveSettings({ onboarded: false });
      }
      return config();
    },
    'POST /api/cloud/check': async (b) => {
      const preset = llm.PRESETS[b.preset] ? b.preset : null;
      if (!preset) throw new HttpError(422, 'Proveedor no reconocido.');
      const base = String(b.base || llm.PRESETS[preset].base).trim();
      const key = String(b.key || '').trim();
      if ((!key && !(llm.cloud().preset === preset && llm.keyPresent())) || !base.startsWith('https://')) {
        throw new HttpError(422, 'Falta la clave o la dirección de la API.');
      }
      try { return { ok: true, models: await llm.checkCloud(base, key) }; } catch (e) { throw new HttpError(400, e.message); }
    },
    'GET /api/loading': () => {
      const cloudMode = llm.isCloud();
      const st = llm.status();
      const items = [
        { id: 'oido', label: 'El oído', state: 'listo', detail: cloudMode ? 'en la nube' : 'en el teléfono' },
        { id: 'voz', label: cloudMode ? 'La voz en la nube' : 'La voz ligera', state: core.ttsAvailable(engine()) ? 'listo' : 'error',
          detail: core.ttsAvailable(engine()) ? '' : 'llega en la siguiente fase: responde con texto' },
        { id: 'cerebro', label: cloudMode ? 'El cerebro en la nube' : 'El cerebro en el teléfono', state: st.ready ? 'listo' : 'error', detail: st.detail },
      ];
      return { items, busy: false };
    },
    'GET /api/models': () => models(),
    'POST /api/models/select': async (b) => {
      if (!BUILTIN.some((m) => m.id === b.id)) throw new HttpError(422, 'Ese modelo no existe.');
      await store.saveSettings({ model_id: b.id });
      return models();
    },
    'POST /api/models': () => { throw new HttpError(422, 'En el teléfono solo están los personajes incluidos.'); },
    'GET /api/memory': () => memory(),
    'DELETE /api/memory': () => { store.forgetAll(); return { ok: true }; },
    'POST /api/memory/forget': (b) => { store.deleteMemory(String(b.fact || '')); return memory(); },
    'GET /api/actions': () => ({ enabled: false, ask: false, always: [], available: false, catalog: {}, history: [] }),
    'POST /api/actions': () => ({ enabled: false, ask: false, always: [], available: false, catalog: {}, history: [] }),
    'POST /api/owner': () => ({ ok: true }),
  };

  function memory() {
    const fmt = (ts) => { const d = new Date(ts * 1000); return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`; };
    return { facts: store.memories(200), summaries: store.summaries(50).map(([text, ts]) => ({ text, date: fmt(ts) })) };
  }

  // fetch(/api/…) de la interfaz → Response
  return async function handle(method, url, body, realFetch) {
    const path = url.pathname;
    if (method === 'GET' && path === '/api/model') {
      const m = BUILTIN.find((x) => x.id === modelId());
      return realFetch(m && m.file ? m.file : BUILTIN[0].file);
    }
    if (method === 'POST' && path === '/api/voices/preview') {
      const id = (body && body.id) || (voice() || {}).id;
      const v = core.voices.find((x) => x.id === id);
      return v ? realFetch(`/voices/previews/${v.id}.wav`) : json(404, { detail: 'Sin muestra.' });
    }
    const fn = routes[`${method} ${path}`];
    if (!fn) return json(404, { detail: 'Esto no existe en el teléfono.' });
    try {
      return json(200, await fn(body || {}, url));
    } catch (e) {
      if (e instanceof HttpError) return json(e.status, { detail: e.message });
      console.error(e);
      return json(500, { detail: 'Algo falló en el teléfono. Inténtalo otra vez.' });
    }
  };
}

const json = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json' } });
