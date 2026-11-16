// Núcleo del companion en el teléfono (iOS ahora, Android después). Lo arranca boot.js.
import { createApi } from './api.js';
import * as llm from './llm.js';
import { call, secrets } from './platform.js';
import { loadPersona } from './prompt.js';
import { describeUser, Session } from './session.js';
import { transcribe } from './ear_cloud.js';
import { cloudVoice } from './voice_cloud.js';
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
    can: { LIGHT_VOICE: false, ...(info.can || {}) },
    started: Date.now() / 1000,
    // Voz: en la nube, edge (voice_cloud.js). La ligera (Piper, dentro del teléfono) llega con el modo teléfono.
    ttsAvailable: (engine) => engine === 'nube',
  };
  const selectedVoice = () => {
    const s = store.getSettings();
    return core.voices.find((x) => x.id === s.voice) || core.voices.find((x) => x.default) || core.voices[0];
  };
  core.voice = cloudVoice(selectedVoice, () => Number((core.persona.voice || {}).speed || 1));
  // Oído en la nube: Groq si hay clave, si no Gemini con la clave del cerebro.
  core.ear = (pcm) => transcribe(pcm, { hasGroq: core.keys.groq, hasGemini: llm.keyPresent() });
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
        get voice() { return cloudMode() ? core.voice : null; },
        get ear() { return cloudMode() ? core.ear : null; } });
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
