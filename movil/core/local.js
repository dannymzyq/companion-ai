// Motores del modo «todo dentro del teléfono»: oído (WhisperKit), cerebro (Gemma 4 con MLX), voz ligera (Piper
// con sherpa-onnx) y detector de voz (Silero). El trabajo pesado lo hace el nativo; aquí queda lo que se reutiliza
// en Android: elegir modelos, el cambio de tono de la voz ligera (como tts_light.py) y el cerebro simulado.
import { call, stream } from './platform.js';
import { CATALOGO, estado, vozLigera } from './modelos.js';
import { getSettings } from './store.js';

const RATE = 24000;
const cargados = {};                        // motor → id del modelo cargado

export function elegidos() {
  const s = getSettings().phone_models || {};
  const pick = (lista, id) => lista.find((m) => m.id === id) || lista[0];
  return { oido: pick(CATALOGO.oido, s.oido), cerebro: pick(CATALOGO.cerebro, s.cerebro), silero: CATALOGO.silero[0] };
}

async function cargar(motor, cmd, m) {
  if (cargados[motor] === m.id) return;
  const t = performance.now();
  const r = await call(cmd, { id: m.id });
  // Si no cabían los dos, el teléfono soltó el otro motor: se volverá a cargar cuando haga falta.
  for (const otro of (r && r.unloaded) || []) delete cargados[otro];
  cargados[motor] = m.id;
  console.info(`${motor}: ${m.id} cargado en ${((performance.now() - t) / 1000).toFixed(1)} s`);
}

// ---------------------------------------------------------------- oído
export async function oir(pcm) {
  await cargar('oido', 'ear.load', elegidos().oido);
  return call('ear.transcribe', { pcm: b64(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength)) });
}

// ---------------------------------------------------------------- voz ligera
export function vozLocal(getVoice, getSpeed) {
  return {
    async *speak(text) {
      const v = getVoice() || {};
      const light = v.light || { model: 'es_MX-claude-high' };
      const pitch = Number(light.pitch || 1);
      const speed = Math.min(1.3, Math.max(0.7, getSpeed()));
      // Como tts_light.py: se sintetiza `pitch` veces más lento y se reproduce `pitch` veces más rápido.
      const t = performance.now();
      const r = await call('voice.light', { id: vozLigera(light.model).id, text: text.slice(0, 1500),
        speed: (Number(light.speed || 1) * speed) / pitch });
      const src = new Int16Array(Uint8Array.from(atob(r.pcm), (c) => c.charCodeAt(0)).buffer);
      const n = Math.floor((src.length / pitch) * RATE / r.rate);
      const out = new Int16Array(n);
      const step = n > 1 ? (src.length - 1) / (n - 1) : 0;
      for (let i = 0; i < n; i++) {
        const x = i * step, j = Math.floor(x), f = x - j;
        out[i] = src[j] + ((src[Math.min(j + 1, src.length - 1)] - src[j]) * f);
      }
      console.info(`Voz ligera: ${((performance.now() - t) / 1000).toFixed(2)} s para ${(n / RATE).toFixed(1)} s de audio`);
      yield out.buffer;
    },
  };
}

// ---------------------------------------------------------------- cerebro
// En el simulador MLX no corre: allí responde un cerebro simulado (para probar el resto del flujo).
const SIMULADO = '[emo:feliz] ¡Hola! Te hablo desde el modo dentro del teléfono, con un cerebro de prueba. '
  + '[gesto:asentir] En el iPhone de verdad aquí responderá Gemma, sin internet. ¿Seguimos?';

export async function* pensar(messages, sampling, { simulado }) {
  if (simulado) {
    for (const palabra of SIMULADO.split(/(?<= )/)) {
      await new Promise((r) => setTimeout(r, 40));
      yield palabra;
    }
    return;
  }
  await cargar('cerebro', 'brain.load', elegidos().cerebro);
  const queue = [];
  let wake = null, done = false, failure = null;
  const push = (x) => { queue.push(x); if (wake) { wake(); wake = null; } };
  const p = stream('brain.generate', { messages, temperature: sampling.temperature, topP: sampling.top_p,
    maxTokens: sampling.max_tokens }, (kind, data) => {
    if (kind === 'chunk') push(data);
    else if (kind === 'info') console.info(`Cerebro local: primer texto ${data.first.toFixed(2)} s, ${data.prompt} tokens de entrada, `
      + `${data.tokens} generados a ${data.tps.toFixed(1)} tokens/s`);
  });
  const id = p.id;
  p.then(() => { done = true; push(null); }, (e) => { failure = e; done = true; push(null); });
  try {
    while (true) {
      if (!queue.length) await new Promise((r) => (wake = r));
      const x = queue.shift();
      if (x === null) { if (failure) throw failure; return; }
      yield x;
    }
  } finally {
    if (!done && id != null) call('stream.cancel', { id }).catch(() => {});
  }
}

// ---------------------------------------------------------------- detector de voz (Silero)
let silero = null;                          // null = sin probar · false = no disponible · true = listo
export async function sileroListo() {
  if (silero !== null) return silero;
  try {
    const m = elegidos().silero;
    if (!(await estado(m)).listo) { silero = false; return false; }
    await call('vad.load', { id: m.id, file: 'silero_vad.onnx' });
    silero = true;
  } catch (e) {
    console.warn('Silero no disponible: sigo con el detector por energía', e.message);
    silero = false;
  }
  return silero;
}
export const sileroTrama = async (frame) => ((await call('vad.frame', { pcm: b64(new Uint8Array(frame.buffer)) })) ? 1 : 0);

export function listoParaTelefono() {
  return Promise.all([elegidos().oido, elegidos().cerebro].map(estado));
}

function b64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
