// Lo que en la PC responde companion/server.py en /api/*, hecho en el teléfono. Mismas formas de respuesta, para
// que web/js no cambie; lo que no existe aquí (acciones, Ollama, voz completa, voces propias) responde vacío o 422.
import * as llm from './llm.js';
import { secrets } from './platform.js';
import * as store from './store.js';
import { describeUser } from './session.js';
import { elegidos } from './local.js';
import * as modelos from './modelos.js';
import { DEFAULT_MODEL, VOICES as LIVE_VOICES } from './live.js';
import * as mood from './mood.js';
import * as personality from './personality.js';
import * as vrm from './vrm.js';

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
  let propios = [];                  // VRM propios (la lista está en kv; se lee al arrancar y tras cada cambio)
  // Hay que esperarla: si la interfaz pregunta antes, el modelo elegido (si es propio) no existe y cae al de
  // fábrica, y parecía que no se guardaba el último modelo.
  const propiosListos = vrm.list().then((l) => { propios = l; }, () => {});

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
  // En la nube, todo en la nube (voz de Edge); en el teléfono, nada sale de él (voz ligera Piper).
  const engine = () => (S().mode === 'telefono' ? 'ligera' : 'nube');
  const modelId = () => ([...BUILTIN, ...propios].some((m) => m.id === S().model_id) ? S().model_id : 'avatar1');

  function publicCloud() {
    const c = llm.cloud();
    return { preset: c.preset, name: llm.PRESETS[c.preset].name, base: c.base, model: c.model,
      has_key: llm.keyPresent() };   // la clave nunca vuelve a la interfaz (ni un trozo)
  }

  // En vivo en el teléfono: solo Gemini Live (los demás proveedores de la PC no están probados aquí).
  function publicLive() {
    const lv = S().live || {};
    return { provider: 'gemini', name: 'Google Gemini Live', model: lv.model || DEFAULT_MODEL, voice: lv.voice || '', url: '',
      has_key: !!core.liveKey(), own_key: !!core.keys.live,
      providers: [{ id: 'gemini', name: 'Google Gemini Live', free: 'gratis con límite diario', keys: 'https://aistudio.google.com/apikey',
        models: [DEFAULT_MODEL], voices: LIVE_VOICES,
        note: 'Tiene capa gratuita (con límite diario). Usa la clave de Gemini del cerebro si no pones otra. En el teléfono no descarga nada.' }] };
  }
  const mode = () => S().mode || 'nube';

  function config() {
    const user = describeUser(profile());
    const cloudMode = llm.isCloud();
    const eng = engine();
    const cfgOut = {
      name: character(), user: profile().name, llm: { ...llm.status(), provider: mode() === 'telefono' ? 'local' : 'gemini' },
      adult: { active: !cloudMode && user.adult && !!(core.persona.adult || {}).enabled },
      onboarded: !!S().onboarded, profile: profile(), cloud: publicCloud(),
      voice: (voice() || {}).name || '', local_model: llm.isCloud() ? elegidos().cerebro.nombre : llm.status().model,
      voice_engine: eng, voice_engine_name: ENGINES[eng].name, voice_engine_pref: eng, voice_auto: false, voice_reason: '',
      watch: { interval: 7, model: '' },
      stt: { ready: true, device: cloudMode ? 'nube' : 'telefono', model: cloudMode ? 'nube' : 'whisper', error: null,
        engine: cloudMode ? 'nube' : 'local', cloud: { groq: !!core.keys.groq, gemini: llm.keyPresent(), last: null }, restart_frees: false },
      cloud_only: mode() === 'nube', mode: mode(),
      gemini_live: mode() === 'vivo', gemini_live_model: publicLive().model, gemini_live_voice: publicLive().voice, live: publicLive(),
      model: true, model_id: modelId(), model_kind: modelId() === 'avatar3' ? 'orb' : 'vrm',
      barge_in: true, actions: { enabled: false, ask: false, always: [], available: false, catalog: {} },
      started: core.started, tts: core.ttsAvailable(eng), gpu: null,
      personality: (() => { const q = personality.active(); return q ? { id: q.id, name: q.name, temper: personality.temper(q) } : null; })(),
    };
    window.__companionConfig = cfgOut;          // para la capa del teléfono (ui_movil.js)
    return cfgOut;
  }

  function setup() {
    const eng = engine();
    return {
      resources: { total_gb: 0, tier: 'telefono', ear_gb: 0, desktop_gb: 0, room: {}, engines: { [eng]: ENGINES[eng] },
        recommended_engine: 'nube', recommended_model: '' },
      voice_engine: { selected: eng, in_use: eng, reason: '', auto: false, recommended: llm.isCloud() ? 'nube' : 'ligera', node: false,
        fits_now: false, light_installed: true, light_size_mb: 0, light_progress: null },
      ear: { engine: llm.isCloud() ? 'nube' : 'local', groq: !!core.keys.groq, gemini: llm.keyPresent(), last: null },
      cloud_only: mode() === 'nube', gemini_live: mode() === 'vivo', gemini_live_model: publicLive().model, live: publicLive(),
      onboarded: !!S().onboarded, character: character(), year: new Date().getFullYear(),
      profile: profile(), suggested_name: profile().name, provider: llm.isCloud() ? 'gemini' : 'local', cloud: publicCloud(),
      presets: Object.entries(llm.PRESETS).map(([id, v]) => ({ id, name: v.name, base: v.base, keys: v.keys, note: v.note })),
      local: { gpu: null, ollama: false, recommended: '', selected: S().local_model || '', in_use: '', models: [], others: [] },
      voices: voices(), tts: core.ttsAvailable(eng), mode: mode(),
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
    // voice_engine: lo decide el modo (nube → voz de Edge, teléfono → voz ligera); se acepta y se ignora.
    if (body.phone_models) {
      const pm = { ...(S().phone_models || {}) };
      for (const k of ['oido', 'cerebro']) {
        const id = body.phone_models[k];
        if (id != null) {
          const m = modelos.CATALOGO[k].find((x) => x.id === id);
          if (!m) throw new HttpError(422, 'Modelo no reconocido.');
          const e = await modelos.estado(m).catch(() => ({}));
          if (!modelos.cabe(k, e.total || 0, core.can.memory_available)) {
            throw new HttpError(422, `${m.nombre} no cabe en la memoria que iOS le deja a la app en este iPhone.`);
          }
          pm[k] = id;
        }
      }
      changes.phone_models = pm;
    }
    if (body.live) {
      if ((body.live.provider || 'gemini') !== 'gemini') throw new HttpError(422, 'En el teléfono, «En vivo» solo funciona con Gemini Live.');
      const key = String(body.live.key || '').trim();
      if (key) { await secrets.set('live_key', key); core.keys.live = true; }
      const model = String(body.live.model || '').trim().slice(0, 120);
      const voice = String(body.live.voice || '');
      if (voice && !LIVE_VOICES.includes(voice)) throw new HttpError(422, 'Voz no reconocida.');
      changes.live = { model: model || DEFAULT_MODEL, voice };
    }
    // Modo pedido por la interfaz 0.9.1: gemini_live / cloud_only / provider (como chooseMode en main.js).
    let wanted = body.mode || null;
    if (!wanted && body.gemini_live === true) wanted = 'vivo';
    else if (!wanted && body.provider === 'local') wanted = 'telefono';
    else if (!wanted && (body.gemini_live === false || body.cloud_only != null || body.provider != null)) {
      wanted = body.cloud_only === false && body.provider == null && mode() === 'telefono' ? 'telefono' : 'nube';
    }
    if (wanted) {
      const mode = wanted;
      if (!['vivo', 'nube', 'telefono'].includes(mode)) throw new HttpError(422, 'Modo no reconocido.');
      if (mode === 'vivo' && !core.liveKey()) throw new HttpError(422, 'Falta la clave de Gemini para «En vivo».');
      if (mode === 'telefono' && S().mode !== 'telefono') {
        await core.revisar().catch(() => {});
        const brainOk = core.listos.cerebro || (core.can.simulator && !core.can.LOCAL_BRAIN);
        if (!core.listos.oido || !brainOk) {
          throw new HttpError(422, 'Primero descarga los modelos del teléfono (Ajustes › Cerebro › Modelos del teléfono).');
        }
      }
      changes.mode = mode;
    }
    if (body.onboarded != null) changes.onboarded = !!body.onboarded;
    const before = mode();
    await store.saveSettings(changes);
    if (changes.mode || changes.phone_models || changes.voice) await core.revisar().catch(() => {});
    if (core.swap && (changes.mode || changes.live || (changes.voice && before === 'vivo'))) core.swap();
    // En el modo teléfono, cada voz necesita su voz ligera: si falta, se baja sola (unos 80 MB).
    if ((S().mode === 'telefono') && changes.voice && !core.listos.voz) {
      const m = piezas().voz;
      modelos.bajar(m, {}).then(() => core.revisar(), (e) => console.warn(`Voz ligera: ${e.message}`));
    }
    return config();
  }

  // ---------------------------------------------------------------- modelos del modo teléfono
  // Lo que hace falta para «todo dentro del teléfono», con tamaños, lo que ya está y el progreso de la descarga.
  function piezas() {
    const e = elegidos();
    const v = voice() && core.voices.find((x) => x.id === voice().id);
    return { oido: e.oido, cerebro: e.cerebro, voz: modelos.vozLigera(((v && v.light) || { model: 'es_MX-claude-high' }).model),
      silero: e.silero };
  }
  const buscar = (id) => [...modelos.CATALOGO.oido, ...modelos.CATALOGO.cerebro, ...modelos.CATALOGO.silero,
    ...Object.values(piezas())].find((m) => m.id === id);

  async function telefono() {
    const p = piezas();
    const lista = await Promise.all(Object.entries(p).map(async ([kind, m]) => {
      try {
        return { kind, ...(await modelos.estado(m)), note: m.nota || '', progress: modelos.progreso(m.id) };
      } catch (e) {
        return { kind, id: m.id, nombre: m.nombre, error: `No pude ver su tamaño: ${e.message}`, progress: modelos.progreso(m.id) };
      }
    }));
    const simulado = !!core.can.simulator && !core.can.LOCAL_BRAIN;    // en el simulador el cerebro es de prueba
    const falta = lista.filter((x) => !x.listo && !(simulado && x.kind === 'cerebro')).reduce((a, x) => a + Math.max(0, (x.total || 0) - (x.present || 0)), 0);
    return { mode: S().mode || 'nube', models: lista, missing_bytes: falta, missing: modelos.gb(falta),
      options: Object.fromEntries(await Promise.all(['oido', 'cerebro'].map(async (k) => [k, await Promise.all(
        modelos.CATALOGO[k].map(async (m) => {
          const e = await modelos.estado(m).catch(() => ({}));
          return { id: m.id, nombre: m.nombre, nota: m.nota, total: e.total || 0, listo: !!e.listo,
            cabe: modelos.cabe(k, e.total || 0, core.can.memory_available) };
        }))]))),
      can: core.can, simulated_brain: !!core.can.simulator && !core.can.LOCAL_BRAIN };
  }

  async function models() {
    propios = await vrm.list();
    return { active: modelId(), builtin: BUILTIN.map(({ id, name, note }) => ({ id, name, note, available: true })), custom: propios };
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
        await secrets.remove('live_key').catch(() => {});
        core.keys.live = false;
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
      const ok = (x) => (x ? 'listo' : 'error');
      if (mode() === 'vivo') {
        return { items: [{ id: 'vivo', label: 'La conversación en vivo', state: ok(core.liveKey()),
          detail: core.liveKey() ? 'Gemini Live, sin descargas' : 'falta la clave de Gemini' }], busy: false };
      }
      const items = cloudMode ? [
        { id: 'oido', label: 'El oído', state: 'listo', detail: 'en la nube' },
        { id: 'voz', label: 'La voz en la nube', state: 'listo', detail: '' },
        { id: 'cerebro', label: 'El cerebro en la nube', state: ok(st.ready), detail: st.detail },
      ] : [
        { id: 'oido', label: 'El oído', state: ok(core.listos.oido), detail: core.listos.oido ? 'en el teléfono' : 'falta descargarlo: puedes escribirle' },
        { id: 'voz', label: 'La voz ligera', state: ok(core.listos.voz), detail: core.listos.voz ? 'en el teléfono' : 'falta descargarla: responde con texto' },
        { id: 'cerebro', label: 'El cerebro en el teléfono', state: ok(st.ready), detail: st.detail },
      ];
      return { items, busy: false };
    },
    'GET /api/models': () => models(),
    'POST /api/models/select': async (b) => {
      if (![...BUILTIN, ...(await vrm.list())].some((m) => m.id === b.id)) throw new HttpError(422, 'Ese modelo no existe.');
      await store.saveSettings({ model_id: b.id });
      return models();
    },
    // VRM propio: la interfaz manda el archivo tal cual (?filename=…). Queda como modelo activo, como en la PC.
    'POST /api/models': async (b, url) => {
      if (!b || typeof b.arrayBuffer !== 'function') throw new HttpError(400, 'Falta el archivo VRM.');
      let saved;
      try { saved = await vrm.add(url.searchParams.get('filename') || 'modelo.vrm', await b.arrayBuffer(), BUILTIN.map((m) => m.id)); }
      catch (e) { throw new HttpError(e instanceof vrm.VRMError ? 400 : 500, e.message); }
      await store.saveSettings({ model_id: saved.id });
      return { ...saved, ...(await models()) };
    },
    'GET /api/personality': () => ({ ...personality.pub(), mood: mood.pub(personality.active()) }),
    'POST /api/personality/select': async (b) => {
      try { await personality.select(String(b.id || '')); } catch (e) { throw new HttpError(400, e.message); }
      if (core.swap && llm.isLive()) core.swap();      // en vivo, el prompt se fija al conectar
      return { ...personality.pub(), mood: mood.pub(personality.active()) };
    },
    'POST /api/personality/custom': async (b) => {
      try { await personality.saveCustom(b || {}); } catch (e) { throw new HttpError(400, e.message); }
      if (core.swap && llm.isLive()) core.swap();
      return { ...personality.pub(), mood: mood.pub(personality.active()) };
    },
    // El teléfono se actualiza reinstalando desde Xcode: no hay aviso de versión nueva.
    'GET /api/update': () => ({ available: false }),
    'POST /api/voices/custom': () => { throw new HttpError(422, 'Las voces propias se crean en la app de la PC o del Mac: en el teléfono no se pueden clonar voces.'); },
    'GET /api/memory': () => memory(),
    'DELETE /api/memory': () => { store.forgetAll(); return { ok: true }; },
    'POST /api/memory/forget': (b) => { store.deleteMemory(String(b.fact || '')); return memory(); },
    'GET /api/actions': () => ({ enabled: false, ask: false, always: [], available: false, catalog: {}, history: [] }),
    'POST /api/actions': () => ({ enabled: false, ask: false, always: [], available: false, catalog: {}, history: [] }),
    'POST /api/owner': () => ({ ok: true }),
    'GET /api/phone': () => telefono(),
    // Empieza a bajar (no espera): el progreso se lee con GET /api/phone.
    'POST /api/phone/download': async (b) => {
      // Sin id: solo lo que falta (en el simulador, sin el cerebro, que allí es de prueba).
      const simulado = !!core.can.simulator && !core.can.LOCAL_BRAIN;
      const ids = b.id ? [b.id] : (await telefono()).models
        .filter((m) => !m.listo && !(simulado && m.kind === 'cerebro')).map((m) => m.id);
      for (const id of ids) {
        const m = buscar(id);
        if (!m) throw new HttpError(422, 'Modelo no reconocido.');
        modelos.bajar(m, { datosMoviles: !!b.cellular }).then(() => core.revisar(), (e) => console.warn(`Descarga de ${id}: ${e.message}`));
      }
      return telefono();
    },
    'POST /api/phone/cancel': async (b) => { const m = buscar(b.id); if (m) await modelos.cancelar(m); return telefono(); },
    'POST /api/phone/delete': async (b) => {
      const m = buscar(b.id);
      if (!m) throw new HttpError(422, 'Modelo no reconocido.');
      await modelos.borrar(m);
      await core.revisar();
      return telefono();
    },
  };

  function memory() {
    const fmt = (ts) => { const d = new Date(ts * 1000); return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`; };
    return { facts: store.memories(200), summaries: store.summaries(50).map(([text, ts]) => ({ text, date: fmt(ts) })) };
  }

  // fetch(/api/…) de la interfaz → Response
  return async function handle(method, url, body, realFetch) {
    await propiosListos;
    const path = url.pathname;
    if (method === 'GET' && path === '/api/model') {
      const own = propios.find((x) => x.id === modelId());
      if (own) return realFetch(vrm.url(own.id));
      const m = BUILTIN.find((x) => x.id === modelId());
      return realFetch(m && m.file ? m.file : BUILTIN[0].file);
    }
    if (method === 'DELETE' && path.startsWith('/api/models/')) {
      try { await vrm.remove(decodeURIComponent(path.slice('/api/models/'.length))); } catch (e) { return json(400, { detail: e.message }); }
      propios = await vrm.list();
      if (!propios.some((x) => x.id === S().model_id) && !BUILTIN.some((x) => x.id === S().model_id)) await store.saveSettings({ model_id: 'avatar1' });
      return json(200, await models());
    }
    if (method === 'DELETE' && path.startsWith('/api/personality/custom/')) {
      await personality.deleteCustom(decodeURIComponent(path.slice('/api/personality/custom/'.length)));
      if (core.swap && llm.isLive()) core.swap();
      return json(200, { ...personality.pub(), mood: mood.pub(personality.active()) });
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
