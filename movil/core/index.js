// Núcleo del companion en el teléfono (iOS ahora, Android después). Lo arranca boot.js.
import { createApi } from './api.js';
import * as llm from './llm.js';
import { call, secrets } from './platform.js';
import { loadPersona } from './prompt.js';
import { describeUser, Session } from './session.js';
import { transcribe } from './ear_cloud.js';
import { cloudVoice } from './voice_cloud.js';
import { elegidos, oir, sileroListo, sileroTrama, vozLocal } from './local.js';
import { estado, vozLigera } from './modelos.js';
import * as store from './store.js';

let open = null;          // la sesión de la conexión abierta (la interfaz abre una sola)

export async function start(realFetch) {
  const [persona, voicesFile] = await Promise.all([
    realFetch('/data/persona.json').then((r) => r.json()),
    realFetch('/data/voices.json').then((r) => r.json()),
  ]);
  await Promise.all([store.load(), store.loadSettings()]);
  const info = await call('app.info').catch(() => ({}));
  await llm.init(await secrets.has(llm.KEY).catch(() => false));

  const core = {
    persona: loadPersona(persona),
    voices: voicesFile.voices,
    keys: { groq: await secrets.has('groq_key').catch(() => false) },
    can: { LIGHT_VOICE: false, LOCAL_BRAIN: false, ...(info.can || {}) },
    listos: { oido: false, cerebro: false, voz: false, silero: false },
    started: Date.now() / 1000,
    // Voz: en la nube, edge (voice_cloud.js). La ligera (Piper, dentro del teléfono) llega con el modo teléfono.
    ttsAvailable: (engine) => (engine === 'nube' ? true : core.listos.voz),
  };
  const selectedVoice = () => {
    const s = store.getSettings();
    return core.voices.find((x) => x.id === s.voice) || core.voices.find((x) => x.default) || core.voices[0];
  };
  core.voice = cloudVoice(selectedVoice, () => Number((core.persona.voice || {}).speed || 1));
  // Oído en la nube: Groq si hay clave, si no Gemini con la clave del cerebro.
  core.ear = (pcm) => transcribe(pcm, { hasGroq: core.keys.groq, hasGemini: llm.keyPresent() });
  core.vozLocal = vozLocal(selectedVoice, () => Number((core.persona.voice || {}).speed || 1));
  // Qué modelos del modo teléfono ya están en el teléfono (al arrancar y tras cada descarga).
  core.revisar = async () => {
    const e = elegidos();
    const v = selectedVoice();
    const voz = vozLigera(((v && v.light) || { model: 'es_MX-claude-high' }).model);
    const [oido, cerebro, ligera, silero] = await Promise.all([e.oido, e.cerebro, voz, e.silero]
      .map((m) => estado(m).then((x) => x.listo).catch(() => false)));
    Object.assign(core.listos, { oido, cerebro, voz: ligera, silero });
    llm.setLocal({ simulado: !!core.can.simulator && !core.can.LOCAL_BRAIN, listo: cerebro });
    core.sileroOk = silero ? await sileroListo() : false;
    return core.listos;
  };
  llm.setLocal({ simulado: !!core.can.simulator && !core.can.LOCAL_BRAIN });
  // Antes del primer «hello»: qué modelos hay (con las listas guardadas es inmediato; sin red, se espera poco).
  await Promise.race([core.revisar().catch((e) => console.warn('No pude revisar los modelos del teléfono', e.message)),
    new Promise((r) => setTimeout(r, 3000))]);
  const api = createApi(core);

  // La ficha común con el nombre y la forma de hablar de la voz elegida (como profile.character).
  const character = () => {
    const v = selectedVoice();
    return v ? { ...core.persona, name: v.name, speaks: v.speaks === 'm' ? 'm' : 'f' } : core.persona;
  };
  const profile = () => describeUser(store.getSettings().profile || {});

  return {
    api,
    connect(deliver) {
      if (open) open.close();
      const cloudMode = () => llm.isCloud();
      const session = new Session(deliver, { persona: character, profile,
        get voice() { return cloudMode() ? core.voice : (core.listos.voz ? core.vozLocal : null); },
        get ear() { return cloudMode() ? core.ear : (core.listos.oido ? oir : null); },
        // Silero (si está bajado) en los dos modos; si no, el detector por energía.
        vadProb: () => (core.sileroOk ? sileroTrama : null) });
      open = session;
      // Como el servidor al abrir /ws: primero «hello» con la configuración.
      api('GET', new URL('/api/config', location.href), null, realFetch).then((r) => r.json())
        .then((cfg) => deliver(JSON.stringify({ type: 'hello', ...cfg })));
      return {
        receive(data) {
          if (typeof data === 'string') {
            let msg;
            try { msg = JSON.parse(data); } catch { return; }
            session.onMessage(msg).catch((e) => console.error(e));
          }
          else if (data instanceof ArrayBuffer) session.onAudio(data);   // micrófono (audio.js)
          else if (ArrayBuffer.isView(data)) session.onAudio(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength));
        },
        close() { session.close(); if (open === session) open = null; },
      };
    },
  };
}
