// Voz en la nube: las voces neuronales de la lectura en voz alta de Edge, como companion/tts_cloud.py (edge-tts).
// El protocolo se arma aquí; el teléfono solo abre el WebSocket (ws.collect) y devuelve el MP3 de la frase, que se
// pasa a PCM de 16 bits a 24 kHz con Web Audio (lo que espera audio.js).
import { call } from './platform.js';
import { secMsGec, SEC_MS_GEC_VERSION, TRUSTED_CLIENT_TOKEN, CHROMIUM_FULL_VERSION } from './edge_token.js';

const WSS = `wss://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=${TRUSTED_CLIENT_TOKEN}`;
const MAJOR = CHROMIUM_FULL_VERSION.split('.')[0];
const HEADERS = {
  'User-Agent': `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/${MAJOR}.0.0.0 Safari/537.36 Edg/${MAJOR}.0.0.0`,
  'Accept-Language': 'en-US,en;q=0.9',
  Pragma: 'no-cache',
  'Cache-Control': 'no-cache',
  Origin: 'chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold',
};
const DEFAULT = { f: 'es-MX-DaliaNeural', m: 'es-MX-JorgeNeural' };
export const SAMPLE_RATE = 24000;

let skew = 0;                       // segundos que el reloj del teléfono va por detrás del servidor

const hex = (n) => [...crypto.getRandomValues(new Uint8Array(n))].map((x) => x.toString(16).padStart(2, '0')).join('');
const percent = (x) => `${x >= 0 ? '+' : ''}${Math.round(x * 100)}%`;
const dateString = () => new Date().toUTCString().replace(/^(\w+), (\d+) (\w+) (\d+) (.*) GMT$/, '$1 $3 $2 $4 $5')
  + ' GMT+0000 (Coordinated Universal Time)';
const escapeXml = (s) => s.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, ' ')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');

export function specFor(voice) {
  if (voice && voice.cloud && voice.cloud.voice) return voice.cloud;
  return { voice: DEFAULT[voice && voice.speaks === 'm' ? 'm' : 'f'] };
}

async function mp3For(text, spec, speed) {
  const rate = Number(spec.rate || 0) + (Math.min(1.3, Math.max(0.7, speed)) - 1);
  const pitch = Math.trunc(Number(spec.pitch || 0));
  const ssml = "<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='en-US'>"
    + `<voice name='${spec.voice}'><prosody pitch='${pitch >= 0 ? '+' : ''}${pitch}Hz' rate='${percent(rate)}' volume='+0%'>`
    + `${escapeXml(text.slice(0, 1500))}</prosody></voice></speak>`;
  const config = `X-Timestamp:${dateString()}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n`
    + '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},'
    + '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}\r\n';
  const request = `X-RequestId:${hex(16)}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:${dateString()}Z\r\nPath:ssml\r\n\r\n${ssml}`;
  for (const attempt of [1, 2]) {
    const url = `${WSS}&ConnectionId=${hex(16)}&Sec-MS-GEC=${secMsGec(Date.now() / 1000 + skew)}&Sec-MS-GEC-Version=${SEC_MS_GEC_VERSION}`;
    const r = await call('ws.collect', { url, headers: { ...HEADERS, Cookie: `muid=${hex(16).toUpperCase()};` },
      messages: [config, request], endPath: 'turn.end', timeout: 20 });
    if (r && r.audio) return r.audio;
    if (attempt === 1 && r && r.date) {             // reloj desfasado: se corrige con la hora del servidor
      const server = Date.parse(r.date);
      if (!Number.isNaN(server)) { skew += (server - Date.now()) / 1000; continue; }
    }
    throw new Error((r && r.error) || 'La voz en la nube no devolvió audio');
  }
  throw new Error('La voz en la nube no devolvió audio');
}

// MP3 (base64) → PCM 16 bits mono 24 kHz
async function decode(b64) {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  if (!bytes.length) throw new Error('La voz en la nube no devolvió audio');
  const ctx = new OfflineAudioContext(1, SAMPLE_RATE, SAMPLE_RATE);
  const buf = await ctx.decodeAudioData(bytes.buffer);
  const f = buf.getChannelData(0);
  const pcm = new Int16Array(f.length);
  for (let i = 0; i < f.length; i++) { const s = Math.max(-1, Math.min(1, f[i])); pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff; }
  return pcm.buffer;
}

// Para session.js: speak(text) → iterable asíncrono de ArrayBuffer (una sola pieza por frase).
export function cloudVoice(getVoice, getSpeed) {
  return {
    async *speak(text) {
      const t = performance.now();
      const b64 = await mp3For(text, specFor(getVoice()), getSpeed());
      const pcm = await decode(b64);
      console.info(`Voz en la nube: ${((performance.now() - t) / 1000).toFixed(2)} s para ${(pcm.byteLength / 48000).toFixed(1)} s de audio`);
      yield pcm;
    },
  };
}
