// Oído en la nube, como companion/stt_cloud.py: Groq (whisper-large-v3-turbo) con su clave y, si no hay o se acabó
// su cuota, Gemini (EAR_GEMINI_MODELS) con la clave del cerebro. Cada frase dicha gasta una petición.
import { cloud, KEY } from './llm.js';
import { request } from './platform.js';

const GROQ_URL = 'https://api.groq.com/openai/v1';
const GROQ_MODEL = 'whisper-large-v3-turbo';
export const GEMINI_MODELS = ['gemini-3.5-flash-lite', 'gemini-3.1-flash-lite'];
const GEMINI_PROMPT = 'Transcribe literalmente lo que dice la persona en este audio, en {lang}, con su puntuación. '
  + 'Responde solo con la transcripción, sin comillas ni comentarios. Si no se oye a nadie hablar, '
  + 'responde exactamente: (silencio)';

const rest = {};                  // proveedor → hasta cuándo (ms) no se usa
export const last = {};           // quién respondió la última vez y cuánto tardó

export class EarError extends Error {}

// Int16Array a 16 kHz → WAV en base64
export function wav16(pcm) {
  const buf = new ArrayBuffer(44 + pcm.length * 2);
  const v = new DataView(buf);
  const str = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  str(0, 'RIFF'); v.setUint32(4, 36 + pcm.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, 16000, true);
  v.setUint32(28, 32000, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); str(36, 'data');
  v.setUint32(40, pcm.length * 2, true);
  new Int16Array(buf, 44).set(pcm);
  let bin = '';
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(bin);
}

const resting = (name) => (rest[name] || 0) > Date.now();
const restAfter = (name, seconds = 600) => { rest[name] = Date.now() + Math.max(60, Math.min(seconds || 600, 6 * 3600)) * 1000; };

async function groq(wav, language, hint) {
  const fields = { model: GROQ_MODEL, response_format: 'verbose_json', temperature: '0' };
  if (language) fields.language = language;
  if (hint) fields.prompt = hint.slice(0, 400);
  const r = await request({ url: `${GROQ_URL}/audio/transcriptions`, method: 'POST', auth: 'groq_key', timeout: 20,
    multipart: { fields, file: { field: 'file', name: 'voz.wav', mime: 'audio/wav', base64: wav } } });
  if (r.status === 429) { restAfter('groq'); throw new EarError('Groq: cuota agotada'); }
  if (r.status !== 200) throw new EarError(`Groq respondió ${r.status}`);
  const out = JSON.parse(r.body);
  if (Array.isArray(out.segments)) {        // sin los tramos que Whisper inventa sobre silencio
    return out.segments.filter((s) => !((s.no_speech_prob || 0) > 0.6 && (s.avg_logprob || 0) < -0.8))
      .map((s) => String(s.text || '').trim()).join(' ').trim();
  }
  return String(out.text || '').trim();
}

async function gemini(model, wav, language) {
  const lang = { es: 'español', en: 'inglés' }[language] || 'el idioma en que hable';
  const body = { model, temperature: 0, messages: [{ role: 'user', content: [
    { type: 'text', text: GEMINI_PROMPT.replace('{lang}', lang) },
    { type: 'input_audio', input_audio: { data: wav, format: 'wav' } }] }] };
  const r = await request({ url: `${cloud().base}/chat/completions`, method: 'POST', auth: KEY, timeout: 30,
    headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (r.status === 429) { restAfter(model); throw new EarError(`${model}: cuota agotada`); }
  if (r.status !== 200) throw new EarError(`${model} respondió ${r.status}`);
  const text = String(JSON.parse(r.body).choices[0].message.content || '').trim().replace(/^["«»]+|["«»]+$/g, '');
  return text.toLowerCase().includes('(silencio)') ? '' : text;
}

// pcm: Int16Array a 16 kHz → texto ('' si no hay habla). EarError si ningún proveedor pudo.
export async function transcribe(pcm, { hasGroq, hasGemini, language = 'es', hint = '' }) {
  const wav = wav16(pcm);
  const tries = [];
  if (hasGroq && !resting('groq')) tries.push(['groq', () => groq(wav, language, hint)]);
  if (hasGemini && cloud().preset === 'gemini') {
    for (const m of GEMINI_MODELS) if (!resting(m)) tries.push([m, () => gemini(m, wav, language)]);
  }
  if (!tries.length) throw new EarError('no hay ningún proveedor del oído en la nube disponible (falta la clave o se acabó la cuota)');
  const errors = [];
  for (const [name, fn] of tries) {
    const t = performance.now();
    try {
      const text = await fn();
      Object.assign(last, { provider: name, seconds: Math.round((performance.now() - t) / 10) / 100 });
      return text;
    } catch (e) {
      errors.push(e instanceof EarError ? e.message : `${name}: ${e.message}`);
    }
  }
  throw new EarError(errors.join('; '));
}
