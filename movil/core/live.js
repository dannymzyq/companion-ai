// Modo «En vivo» en el teléfono: una sola conversación de voz con Gemini Live (oído + cerebro + voz en la nube),
// port de companion/gemini_live.py y de la parte en vivo de companion/session.py. No carga ningún modelo en el
// teléfono. El WebSocket lo abre el nativo (live.open), que pone la clave: el JS nunca la ve.
// Habla con la interfaz el mismo protocolo que /ws (sentence, caption_delta, express, user_text, state…).
import { call, stream } from './platform.js';
import * as store from './store.js';
import * as mood from './mood.js';
import { buildSystemPrompt, EMOTIONS, GESTURES, GREETING, localTime, samplingFor, turnContext } from './prompt.js';

export const WS_URL = 'wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent';
export const DEFAULT_MODEL = 'gemini-3.1-flash-live-preview';
export const VOICES = ['Aoede', 'Kore', 'Leda', 'Zephyr', 'Puck', 'Charon', 'Fenrir', 'Orus'];
const VOICE_MAP = { mika: 'Aoede', natsumi: 'Leda', ayaka: 'Kore', chiaki: 'Zephyr', kenji: 'Puck', akira: 'Orus',
  goro: 'Charon', ryo: 'Fenrir', satoshi: 'Charon' };
const SEND_BYTES = 3072;              // ~96 ms a 16 kHz: menos mensajes por el puente

// Como LIVE_PROMPT_NOTE de la PC, sin la parte de acciones (en el teléfono no hay acciones).
export const LIVE_NOTE = '\n\n# Modo en vivo (llamada de voz)\n'
  + 'Respondes con tu propia voz en español, en frases naturales y breves como en una llamada, y con TU forma de '
  + 'ser: el tono, el humor, las muletillas y el estilo de tus ejemplos se tienen que notar en cada respuesta. Nada '
  + 'de tono de asistente neutra.\n'
  + 'Tu cara y tu cuerpo se mueven con la herramienta `expresar`: llámala al EMPEZAR cada respuesta con la emoción '
  + 'que de verdad sientes ante lo que te dicen (y un gesto si viene a cuento), y otra vez si cambias de emoción. '
  + 'No cambia lo que dices ni hay que esperar su respuesta: sigue hablando.\n'
  + 'Nunca digas en voz alta etiquetas entre corchetes ([emo:…], [gesto:…]) ni el nombre de una herramienta.';

export const EXPRESS_TOOL = {
  name: 'expresar',
  description: 'Muestra en tu cara y tu cuerpo la emoción que sientes y, si viene a cuento, un gesto. '
    + 'Llámala al empezar cada respuesta. No hace falta esperar su resultado.',
  parameters: { type: 'OBJECT', properties: {
    emocion: { type: 'STRING', enum: EMOTIONS }, gesto: { type: 'STRING', enum: ['ninguno', ...GESTURES] } },
  required: ['emocion'] },
  behavior: 'NON_BLOCKING',
};

export function voiceFor(voiceId, speaks = 'f', chosen = '') {
  if (chosen && VOICES.includes(chosen)) return chosen;
  return VOICE_MAP[voiceId] || (speaks === 'm' ? 'Puck' : 'Aoede');
}

export function liveRecap(p, userName) {
  const q = p.personality || {}, s = p.speech_style || {};
  const lines = [`Recuerda quién eres: ${p.name || 'tú'}${q.name ? `, con la personalidad «${q.name}»` : ''}.`];
  if (p.personality_text) lines.push(String(p.personality_text));
  if (q.emotions && q.emotions.length) lines.push(`Se te notan sobre todo: ${q.emotions.join(', ')}; tu ánimo de siempre es ${q.base_mood || 'neutral'}.`);
  if (s.catchphrases && s.catchphrases.length) lines.push(`Tus muletillas (de vez en cuando): ${s.catchphrases.join(', ')}.`);
  if (q.examples && q.examples.length) lines.push(`Suenas así: ${q.examples.slice(0, 4).map((x) => `«${x}»`).join(' · ')}`);
  lines.push(`Hablas con ${userName}: reacciona a lo que siente y a cómo te habla, como lo harías tú.`);
  return lines.join('\n');
}

const EMO_WORDS = [
  ['triste', /lo siento|qu[eé] pena|qu[eé] triste|qu[eé] mal|\bpobre|lamento|\bánimo/i],
  ['molesta', /\boye\b|qu[eé] pesad|no me gusta|me molesta|ya basta|qu[eé] rabia/i],
  ['sorprendida', /\bwow\b|en serio\?|de verdad\?|no me digas|no puede ser/i],
  ['emocionada', /qu[eé] emoci[oó]n|incre[ií]ble|felicidades|enhorabuena|me encanta|\bgenial\b/i],
  ['sonrojada', /me sonroj|qu[eé] cosas dices|ay,? (calla|para)/i],
  ['carinosa', /cari[nñ]o|aqu[ií] estoy|te quiero|mi vida|\babrazo/i],
  ['feliz', /\bjaj|\bjej|qu[eé] bien|me alegra|\bbonito|claro que s[ií]/i],
  ['pensativa', /\bhmm|d[eé]jame pensar|\ba ver\b|buena pregunta/i],
  ['confundida', /no entiendo|\bc[oó]mo\?|\bqu[eé] dices/i],
  ['nerviosa', /\beh+\.\.\.|\bum+\b|\bbueno\.\.\./i],
];
export function guessEmotion(text) {
  for (const [emo, rx] of EMO_WORDS) if (rx.test(text || '')) return emo;
  return null;
}
export const cleanSpoken = (t) => String(t || '').replace(/\[[^\]]+\]/g, '').trim();

export function buildSetup({ system, model = DEFAULT_MODEL, voice = 'Aoede', temperature = null }) {
  const gen = { responseModalities: ['AUDIO'], speechConfig: { voiceConfig: { prebuiltVoiceConfig: { voiceName: voice } } } };
  if (temperature != null) gen.temperature = Number(temperature);
  return { setup: {
    model: model.startsWith('models/') ? model : `models/${model}`,
    generationConfig: gen,
    systemInstruction: { parts: [{ text: system + LIVE_NOTE }] },
    inputAudioTranscription: {}, outputAudioTranscription: {},
    tools: [{ functionDeclarations: [EXPRESS_TOOL] }],
  } };
}

function b64(bytes) {
  let s = '';
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  return btoa(s);
}
function unb64(text) {
  const s = atob(text), out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out.buffer;
}

// Transporte por el puente nativo. En las pruebas se cambia por uno de mentira con la misma forma.
export function nativeSocket(auth) {
  return {
    open(onMessage, onClose) {
      return new Promise((resolve, reject) => {
        let opened = false;
        const p = stream('live.open', { url: WS_URL, auth }, (kind, data) => {
          if (kind === 'open') { opened = true; resolve(p.id); } else if (kind === 'message') onMessage(data);
        });
        p.then(() => onClose(null), (e) => { if (!opened) reject(e); onClose(e); });
      });
    },
    send: (id, text) => call('live.send', { id, text }),
    close: (id) => call('stream.cancel', { id }).catch(() => {}),
  };
}

export class LiveSession {
  // ctx: { persona(), profile(), socket(), voice() → nombre de voz de Gemini, model(), summaries() opcional }
  constructor(send, ctx) {
    this.sendRaw = send;
    this.ctx = ctx;
    this.state = 'idle';
    this.closed = false;
    this.sock = null;            // {id, transport}
    this.connecting = null;
    this.ready = null;
    this.pcm = [];
    this.pcmBytes = 0;
    this.sentenceId = 0;
    this.turnOpen = false;
    this.inBuf = [];
    this.outBuf = [];
    this.emo = '';
    this.emotion = 'neutral';
    this.dropAudio = false;      // tras «interrumpir» desde la interfaz, hasta que acabe ese turno
    this.clientPlaying = false;
  }

  send(obj) { if (!this.closed) this.sendRaw(JSON.stringify(obj)); }
  sendBytes(buf) { if (!this.closed) this.sendRaw(buf); }
  setState(v) { if (v !== this.state) { this.state = v; this.send({ type: 'state', value: v }); } }
  get busy() { return this.turnOpen; }

  system() {
    const p = this.ctx.persona(), prof = this.ctx.profile();
    // En vivo es la nube: nunca el bloque +18.
    const past = (this.ctx.summaries ? this.ctx.summaries() : []);
    return `${buildSystemPrompt(p, { userName: prof.name, memories: store.memories(), adult: false, about: prof.about, summaries: past, live: true, vision: true })}`
      + `\n\n${liveRecap(p, prof.name)}\n\n${turnContext(localTime(), mood.describe(p.personality), mood.sinceLastTalk(store.lastTs()))}`;
  }

  async ensure() {
    if (this.sock) return this.sock;
    if (!this.connecting) {
      this.connecting = this._connect().finally(() => { this.connecting = null; });
    }
    return this.connecting;
  }

  async _connect() {
    const transport = this.ctx.socket();
    let setupDone;
    this.ready = new Promise((r) => (setupDone = r));
    const id = await transport.open((text) => this._onServer(text, setupDone), (err) => this._onClosed(err));
    const sock = { id, transport };
    const samp = samplingFor(this.ctx.persona());
    await transport.send(id, JSON.stringify(buildSetup({ system: this.system(), model: this.ctx.model(),
      voice: this.ctx.voice(), temperature: samp.temperature })));
    const ok = await Promise.race([this.ready, new Promise((r) => setTimeout(() => r(false), 15000))]);
    if (!ok) { transport.close(id); throw new Error('Gemini Live no respondió a la configuración'); }
    if (this.closed) { transport.close(id); throw new Error('cerrada'); }
    this.sock = sock;
    console.info('En vivo conectado');
    return sock;
  }

  _onClosed(err) {
    this.sock = null;
    if (this.turnOpen) this._endTurn();
    if (err && !this.closed) {
      console.warn('En vivo se cortó', err.message);
      this.send({ type: 'error', message: String(err.message || err) });
      this.setState('idle');
    }
  }

  async _raw(obj) {
    const s = await this.ensure();
    await s.transport.send(s.id, JSON.stringify(obj));
  }

  async onMessage(data) {
    const kind = data.type;
    try {
      if (kind === 'text') {
        const text = String(data.text || '').trim().slice(0, 2000);
        if (!text) return;
        this.inBuf = [text];
        this.send({ type: 'user_text', text });
        this.setState('thinking');
        await this._raw({ clientContent: { turns: [{ role: 'user', parts: [{ text }] }], turnComplete: true } });
      } else if (kind === 'start') {
        this.setState('thinking');
        await this._raw({ clientContent: { turns: [{ role: 'user', parts: [{ text: GREETING }] }], turnComplete: true } });
      } else if (kind === 'interrupt') {
        if (this.turnOpen) { this.dropAudio = true; this._endTurn(true); }
        this.clientPlaying = false;
        this.setState('idle');
      } else if (kind === 'frame') {
        // Cámara o pantalla compartida: como mucho una imagen por segundo a Gemini, solo con la conversación abierta.
        if (!['camera', 'screen'].includes(data.source) || typeof data.jpeg !== 'string' || !this.sock) return;
        if (Date.now() - (this.frameAt || 0) < 1000) return;
        this.frameAt = Date.now();
        this.sock.transport.send(this.sock.id, JSON.stringify({ realtimeInput: { video: { mimeType: 'image/jpeg', data: data.jpeg } } })).catch(() => {});
      } else if (kind === 'playback_end') {
        this.clientPlaying = false;
        if (!this.turnOpen) this.setState('idle');
      }
    } catch (e) {
      if (this.closed) return;
      this.send({ type: 'error', message: `En vivo no está disponible: ${e.message}` });
      this.setState('idle');
    }
  }

  // Micrófono: PCM de 16 bits a 16 kHz en tramas de 32 ms. Gemini decide cuándo acabó de hablar y si interrumpe
  // (la cancelación de eco la da WebKit: echoCancellation en getUserMedia, audio.js). No se toca la sesión de audio
  // del teléfono: pasarla a «voiceChat» dejaba la voz de la página en «interrupted» y no se oía (21 nov 2026).
  onAudio(buffer) {
    if (this.closed) return;
    this.pcm.push(new Uint8Array(buffer));
    this.pcmBytes += buffer.byteLength;
    if (this.pcmBytes < SEND_BYTES) return;
    const all = new Uint8Array(this.pcmBytes);
    let o = 0;
    for (const c of this.pcm) { all.set(c, o); o += c.length; }
    this.pcm = []; this.pcmBytes = 0;
    if (!this.sock) { this.ensure().catch(() => {}); return; }       // conecta con la primera voz; ese trozo se pierde
    this.sock.transport.send(this.sock.id, JSON.stringify({ realtimeInput: { audio: { mimeType: 'audio/pcm;rate=16000', data: b64(all) } } }))
      .catch(() => {});
  }

  _openSentence() {
    if (this.turnOpen) return;
    this.turnOpen = true;
    this.sentenceId += 1;
    this.outBuf = [];
    this.clientPlaying = true;
    this.setState('speaking');
    this.send({ type: 'sentence', id: this.sentenceId, text: '', emotion: this.emotion, gestures: [] });
  }

  _express(emotion, gesture, how) {
    emotion = EMOTIONS.includes(emotion) ? emotion : null;
    gesture = GESTURES.includes(gesture) ? gesture : null;
    if (!emotion && !gesture) return;
    if (emotion) { this.emotion = emotion; this.emo = how; }
    this.send({ type: 'express', emotion, gestures: gesture ? [gesture] : [] });
  }

  _endTurn(cut = false) {
    const reply = cleanSpoken(this.outBuf.join(''));
    const said = this.inBuf.join('').trim();
    if (!cut) {
      if (said) store.addMessage('user', said);
      if (reply) { store.addMessage('assistant', reply, this.emotion); mood.feel(this.emotion, this.ctx.persona().personality); }
    }
    if (!cut && this.audioBytes) console.info(`En vivo: ${(this.audioBytes / 48000).toFixed(1)} s de voz recibida`);
    this.audioBytes = 0;
    if (this.turnOpen) {
      this.send({ type: 'sentence_end', id: this.sentenceId });
      this.send({ type: 'reply_end', text: reply });
    }
    this.turnOpen = false;
    this.inBuf = []; this.outBuf = []; this.emo = '';
  }

  _onServer(text, setupDone) {
    let msg;
    try { msg = JSON.parse(text); } catch { return; }
    if (msg.setupComplete) { setupDone(true); return; }
    const tc = msg.toolCall;
    if (tc && Array.isArray(tc.functionCalls)) {
      const answers = [];
      for (const fc of tc.functionCalls) {
        const args = fc.args && typeof fc.args === 'object' ? fc.args : {};
        if (fc.name === 'expresar') this._express(String(args.emocion || ''), String(args.gesto || ''), 'tool');
        // Respuesta SILENT: no frena la voz ni hace que vuelva a hablar. Otra herramienta: no existe aquí.
        answers.push({ id: String(fc.id || ''), name: fc.name,
          response: fc.name === 'expresar' ? { ok: true, scheduling: 'SILENT' } : { ok: false, error: 'no disponible en el teléfono' } });
      }
      if (this.sock) this.sock.transport.send(this.sock.id, JSON.stringify({ toolResponse: { functionResponses: answers } })).catch(() => {});
    }
    const sc = msg.serverContent;
    if (!sc || typeof sc !== 'object') return;
    if (sc.interrupted) {
      this.emo = '';
      if (this.turnOpen) { this.turnOpen = false; this.outBuf = []; }
      this.clientPlaying = false;
      this.send({ type: 'interrupt' });
      this.setState('listening');
    }
    if (sc.inputTranscription && sc.inputTranscription.text) {
      this.inBuf.push(String(sc.inputTranscription.text));
      const said = this.inBuf.join('').trim();
      if (said) this.send({ type: 'user_text', text: said });
      if (!this.turnOpen) this.setState('listening');
    }
    if (sc.outputTranscription && sc.outputTranscription.text && !this.dropAudio) {
      this._openSentence();
      this.outBuf.push(String(sc.outputTranscription.text));
      const clean = cleanSpoken(this.outBuf.join(''));
      if (!this.emo && clean.length >= 12) { this.emo = 'guess'; this._express(guessEmotion(clean), null, 'guess'); }
      this.send({ type: 'caption_delta', id: this.sentenceId, text: clean });
    }
    const parts = (sc.modelTurn && sc.modelTurn.parts) || [];
    for (const part of parts) {
      const inline = part && part.inlineData;
      if (inline && inline.data && (!inline.mimeType || String(inline.mimeType).startsWith('audio/pcm')) && !this.dropAudio) {
        this._openSentence();
        const pcm = unb64(inline.data);
        this.audioBytes = (this.audioBytes || 0) + pcm.byteLength;
        this.sendBytes(pcm);                       // PCM 24 kHz, como la voz de Edge
      }
    }
    if (sc.turnComplete) {
      if (this.dropAudio) { this.dropAudio = false; this.inBuf = []; this.outBuf = []; this.turnOpen = false; return; }
      this._endTurn();
    }
  }

  close() {
    this.closed = true;
    if (this.sock) { this.sock.transport.close(this.sock.id); this.sock = null; }
  }
}
