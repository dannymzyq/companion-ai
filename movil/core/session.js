// Port de la parte del turno de companion/session.py: texto (o lo que oyó el oído) → LLM → frases con sus
// etiquetas → voz → interfaz. Habla el mismo protocolo que /ws (ver el docstring de session.py), así que
// web/js/main.js no sabe que no hay servidor.
import * as llm from './llm.js';
import * as store from './store.js';
import { adultActive, buildSystemPrompt, fill, GENDERS, GREETING, localTime, samplingFor, SUMMARIZE, turnContext } from './prompt.js';
import { TagStream } from './tags.js';
import * as mood from './mood.js';
import { MIN_SPEECH_FRAMES, TurnDetector } from './vad.js';

const HISTORY_KEEP = 14, HISTORY_MAX = 28;
const FRAME_MAX_AGE = 6000;        // una imagen más vieja ya no cuenta como «lo que ve ahora» (como session.py)
const SUMMARY_MIN = 8, SUMMARY_QUIET = 12_000;
const SYSTEM_SUMMARIES = 8;
const FACT = /^\W*dato\s*:\s*(.+)$/i;
const PRIVATE = /\d[\d \-.]{5,}\d|contraseñ|password|clave|pin\b|tarjeta|cuenta bancaria|dni|pasaporte/i;

export function splitSummary(text) {
  const summary = [], facts = [];
  for (const raw of text.replace(/\[[^\]]*\]/g, '').split(/\r?\n/)) {
    const line = raw.trim();
    const m = FACT.exec(line);
    if (m) {
      const fact = m[1].trim().replace(/^[«»"' ]+|[«»"' ]+$/g, '');
      if (fact.length >= 8 && fact.length <= 200 && !PRIVATE.test(fact) && facts.length < 3) facts.push(fact);
    } else if (line) {
      summary.push(line);
    }
  }
  return [summary.join(' ').trim(), facts];
}

export class Session {
  // ctx: { persona(), profile(), voice: { speak(text) → async iterable de ArrayBuffer (PCM 24 kHz) } | null,
  //        ear(Int16Array 16 kHz) → Promise<texto> | null }
  constructor(send, ctx) {
    this.sendRaw = send;
    this.ctx = ctx;
    this.state = 'idle';
    this.turn = null;            // {cancelled, done: Promise}
    this.clientPlaying = false;
    this.lastTalk = Date.now();
    this.summaryRetry = 0;
    this.emotion = 'neutral';
    this.anchor = store.anchor(HISTORY_KEEP);
    this.calm = setInterval(() => this._maybeSummarize(), 4000);
    this.closed = false;
    this.playStarted = 0;
    this.audioBytes = 0;
    this.carryAudio = null;           // lo que dijo antes de una pausa, aún sin transcribir
    this.carryText = '';              // ídem, ya transcrito
    this.frames = {};                 // la última imagen de la cámara y de la pantalla {camera|screen: {jpeg, at}}
    this.prevTs = store.lastTs();     // para «hace días que no hablaban» (solo cuenta en el primer turno)
    this.detector = new TurnDetector({
      start: () => this._speechStarted(),
      end: (audio, frames) => this._speechEnded(audio, frames),
      isPlaying: () => {
        // red de seguridad si la interfaz no avisó del fin del audio
        if (this.clientPlaying && Date.now() > this.playStarted + (this.audioBytes / 48000) * 1000 + 1500) this.clientPlaying = false;
        return this.clientPlaying;
      },
      bargeIn: true,
      prob: () => (this.ctx.vadProb ? this.ctx.vadProb() : null),
    });
  }

  // Micrófono: PCM de 16 bits a 16 kHz en tramas de 32 ms (audio.js)
  onAudio(buffer) {
    if (!this.ctx.ear) return;
    this.detector.feed(buffer);
  }

  async _speechStarted() {
    await this.interrupt();
    this.setState('listening');
  }

  _speechEnded(audio, frames) {
    this.lastTalk = Date.now();
    if (frames < MIN_SPEECH_FRAMES && !this.carryAudio && !this.carryText) {
      if (!this.turn) this.setState(this.clientPlaying ? 'speaking' : 'idle');
      return;
    }
    const turn = { cancelled: false, phase: 'stt', audio, text: null };
    turn.done = this._voiceTurn(audio, turn).catch((e) => {
      if (!turn.cancelled) { console.error(e); this.send({ type: 'error', message: String(e.message || e) }); }
    }).finally(() => { if (this.turn === turn) this.turn = null; if (!this.clientPlaying && !this.turn) this.setState('idle'); });
    this.turn = turn;
  }

  async _voiceTurn(audio, turn) {
    if (this.carryAudio) {             // lo dicho antes de la pausa va delante, con 0,3 s de silencio
      const joined = new Int16Array(this.carryAudio.length + 4800 + audio.length);
      joined.set(this.carryAudio); joined.set(audio, this.carryAudio.length + 4800);
      audio = joined;
      turn.audio = audio;
      this.carryAudio = null;
    }
    this.setState('thinking');
    const t0 = performance.now();
    let text;
    try {
      text = await this.ctx.ear(audio);
    } catch (e) {
      if (turn.cancelled) return;
      this.send({ type: 'error', message: `No pude entenderte: ${e.message}. Puedes escribirle.` });
      return;
    }
    if (turn.cancelled) return;
    console.info(`Oído: ${((performance.now() - t0) / 1000).toFixed(2)} s para ${(audio.length / 16000).toFixed(1)} s de audio`);
    if (!text && !this.carryText) { this.setState(this.clientPlaying ? 'speaking' : 'idle'); return; }
    turn.phase = 'llm';
    turn.text = text;
    await this._runTurn(text, null, turn, t0);
  }

  send(obj) { if (!this.closed) this.sendRaw(JSON.stringify(obj)); }
  sendBytes(buf) { if (!this.closed) this.sendRaw(buf); }

  setState(v) {
    if (v !== this.state) { this.state = v; this.send({ type: 'state', value: v }); }
  }

  get busy() { return !!this.turn; }

  async onMessage(data) {
    const kind = data.type;
    if (kind === 'text') {
      const text = String(data.text || '').trim().slice(0, 2000);
      if (text) { await this.interrupt(); this._start(text, null); }
    } else if (kind === 'start') {
      if (!this.busy) this._start(null, GREETING);
    } else if (kind === 'interrupt') {
      await this.interrupt();
      this.setState('idle');
    } else if (kind === 'frame') {
      // Cámara: una imagen por segundo (vision.js). Solo la ven los cerebros en la nube.
      if (['camera', 'screen'].includes(data.source) && typeof data.jpeg === 'string' && data.jpeg.length < 2_000_000) {
        this.frames[data.source] = { jpeg: data.jpeg, at: Date.now() };
      }
    } else if (kind === 'frame_stop') {
      delete this.frames[data.source];
    } else if (kind === 'playback_end') {
      this.lastTalk = Date.now();
      this.clientPlaying = false;
      if (!this.turn) this.setState('idle');
    }
    // watch, screen_audio, action_answer…: no existen en el teléfono.
  }

  _start(text, instruction) {
    const turn = { cancelled: false, phase: 'llm', text };
    turn.done = this._runTurn(text, instruction, turn).catch((e) => {
      if (!turn.cancelled) { console.error(e); this.send({ type: 'error', message: String(e.message || e) }); }
    }).finally(() => { if (this.turn === turn) this.turn = null; if (!this.clientPlaying && !this.turn) this.setState('idle'); });
    this.turn = turn;
  }

  async interrupt() {
    const t = this.turn;
    if (!t && !this.clientPlaying) return;
    if (t) {
      t.cancelled = true;
      this.turn = null;
      // Si aún no había empezado a hablar, lo que dijo el usuario no se pierde: se une a lo siguiente.
      if (t.phase === 'stt' && t.audio) this.carryAudio = t.audio;
      else if (t.phase === 'llm' && t.text && !t.spoke) this.carryText = t.text;
    }
    this.send({ type: 'interrupt' });
    this.clientPlaying = false;
    // No se espera a que acabe: el turno viejo mira `cancelled` en cada trozo y su petición se corta sola.
  }

  persona() { return this.ctx.persona(); }

  _system() {
    const p = this.persona();
    const prof = this.ctx.profile();
    const adult = adultActive(p, { isCloud: llm.isCloud(), userAdult: prof.adult });
    const past = store.summaries(SYSTEM_SUMMARIES).map(([t, ts]) => `${fmtDate(ts)}: ${t}`);
    return buildSystemPrompt(p, { userName: prof.name, memories: store.memories(), adult, about: prof.about, summaries: past,
      vision: llm.isCloud() });
  }

  _messages(instruction) {
    const system = this._system();
    let rows = store.since(this.anchor);
    if (rows.length > HISTORY_MAX) {
      rows = rows.slice(-HISTORY_KEEP);
      while (rows.length && rows[0][1] !== 'user') rows.shift();
      this.anchor = rows.length ? rows[0][0] : store.anchor(1);
    }
    const messages = [{ role: 'system', content: system }, ...rows.map(([, role, content]) => ({ role, content }))];
    if (instruction) messages.push({ role: 'user', content: instruction });
    const last = [...messages].reverse().find((m) => m.role === 'user');
    if (last) {
      let done = '';
      if (!instruction) {
        const prof = this.ctx.profile();
        const old = store.relevantSummaries(last.content, SYSTEM_SUMMARIES, 2, `${prof.name} ${this.persona().name}`);
        done += old.map(([t, ts]) => `\n(Recuerdas de una conversación del ${fmtDate(ts)}: ${t})`).join('');
      }
      const p = this.persona();
      const gap = mood.sinceLastTalk(this.prevTs);
      this.prevTs = Date.now() / 1000;
      last.content = `${turnContext(localTime(), mood.describe(p.personality), gap)}${done}\n${last.content}`;
      // Con la cámara activa y el cerebro en la nube, la imagen de ahora va con su mensaje (como _images_openai).
      // Con la pantalla compartida, igual: la pantalla de su teléfono (lo que está viendo).
      const fresh = (f) => f && Date.now() - f.at <= FRAME_MAX_AGE;
      const parts = [];
      if (fresh(this.frames.screen)) parts.push({ type: 'text', text: '(Captura de la pantalla de su teléfono, lo que está viendo ahora mismo)' },
        { type: 'image_url', image_url: { url: `data:image/jpeg;base64,${this.frames.screen.jpeg}` } });
      if (fresh(this.frames.camera)) parts.push({ type: 'text', text: '(Imagen de la cámara de su teléfono, ahora mismo)' },
        { type: 'image_url', image_url: { url: `data:image/jpeg;base64,${this.frames.camera.jpeg}` } });
      if (!instruction && parts.length && llm.isCloud()) last.content = [...parts, { type: 'text', text: last.content }];
    }
    return messages;
  }

  async _runTurn(text, instruction, turn, t0 = performance.now()) {
    let msgId = null;
    if (text != null && this.carryText) {
      text = `${this.carryText} ${text}`.trim();
      this.carryText = '';
    }
    turn.text = text;
    if (text != null) {
      msgId = store.addMessage('user', text);
      this.send({ type: 'user_text', text });
    }
    this.setState('thinking');
    const messages = this._messages(instruction);
    this.lastTalk = Date.now();

    const parser = new TagStream();
    const queue = new Queue();
    const speaker = this._speak(queue, turn, t0);
    let failure = null;
    try {
      for await (const piece of llm.streamChat(messages, samplingFor(this.persona()))) {
        if (turn.cancelled) break;
        for (const s of parser.feed(piece)) queue.put(s);
      }
      if (!turn.cancelled) for (const s of parser.flush()) queue.put(s);
    } catch (e) {
      if (!(e instanceof llm.LLMError)) throw e;
      failure = e.message;
    }
    queue.put(null);
    await speaker;
    for (const n of llm.popNotices()) this.send({ type: 'notice', message: n });
    if (turn.cancelled) {
      // Lo que se alcanzó a mostrar o decir es lo que cuenta (parser.spoken incluye frases aún en la cola).
      this._savePartial(msgId, turn.spoke ? parser : { spoken: [] });
      return;
    }
    if (failure) {
      this._savePartial(msgId, parser);
      this.send({ type: 'error', message: failure });
      return;
    }
    const full = parser.spoken.join(' ');
    if (full) { store.addMessage('assistant', full, this.emotion); mood.feel(this.emotion, (this.persona().personality)); }
    for (const fact of parser.memories) store.addMemory(fact);
    this.send({ type: 'reply_end', text: full });
  }

  // Turno cortado: se guarda lo que alcanzó a decir; si no dijo nada, el mensaje del usuario se retira (vuelve
  // unido a lo siguiente que diga, o se descarta si el LLM falló).
  _savePartial(msgId, parser) {
    const said = parser.spoken.join(' ');
    if (said) store.addMessage('assistant', said + '…', this.emotion);
    else if (msgId != null) store.deleteMessage(msgId);
  }

  async _speak(queue, turn, t0) {
    const voice = this.ctx.voice;
    let idx = 0, voiceOk = true;
    while (true) {
      const s = await queue.get();
      if (s === null || turn.cancelled) return;
      idx += 1;
      if (s.emotion) this.emotion = s.emotion;
      this.send({ type: 'sentence', id: idx, text: s.text, emotion: s.emotion, gestures: s.gestures });
      if (idx === 1) { turn.spoke = true; console.info(`Primera frase a los ${((performance.now() - t0) / 1000).toFixed(2)} s`); }
      if (voice && voiceOk) {
        try {
          for await (const pcm of voice.speak(s.text)) {
            if (turn.cancelled) return;
            if (!this.clientPlaying) {
              this.clientPlaying = true;
              this.playStarted = Date.now();
              this.audioBytes = 0;
              this.setState('speaking');
              if (idx === 1) console.info(`Primer audio a los ${((performance.now() - t0) / 1000).toFixed(2)} s`);
            }
            this.audioBytes += pcm.byteLength;
            this.sendBytes(pcm);
          }
        } catch (e) {
          voiceOk = false;
          console.warn('Sin voz', e);
          this.send({ type: 'error', message: 'La voz no está disponible ahora. Sigo en texto.' });
        }
      }
      this.send({ type: 'sentence_end', id: idx });
    }
  }

  // Memoria a largo plazo: en un rato de calma se resume lo que quedó fuera del historial.
  async _maybeSummarize() {
    if (this.turn || this.summarizing || this.clientPlaying) return;
    if (Date.now() - this.lastTalk < SUMMARY_QUIET || Date.now() < this.summaryRetry || !llm.status().ready) return;
    if (llm.simulated()) return;              // el cerebro de prueba del simulador no sabe resumir
    const rows = store.unsummarized(this.anchor);
    if (rows.length < SUMMARY_MIN) return;
    this.summarizing = true;
    const name = this.persona().name, user = this.ctx.profile().name;
    const dialog = rows.map(([, role, text]) => `${role === 'user' ? user : name}: ${text}`).join('\n');
    const known = store.memories(40).join('; ') || 'nada todavía';
    try {
      const text = await llm.complete([{ role: 'user', content: fill(SUMMARIZE, {
        user, name, dialog: dialog.slice(0, 12000), known: known.slice(0, 2000) }) }], 320);
      const [summary, facts] = splitSummary(text);
      for (const f of facts) store.addMemory(f);
      if (summary.length > 20) store.addSummary(summary.slice(0, 900), rows[0][0], rows[rows.length - 1][0], rows[rows.length - 1][3]);
    } catch (e) {
      console.warn('No pude resumir la conversación', e.message);
      this.summaryRetry = Date.now() + 300_000;
    } finally {
      llm.popNotices();
      this.summarizing = false;
    }
  }

  close() {
    this.closed = true;
    clearInterval(this.calm);
    if (this.turn) this.turn.cancelled = true;
  }
}

export function describeUser(profile) {
  const year = profile.birth_year;
  const age = Number.isInteger(year) ? new Date().getFullYear() - year - 1 : null;
  const years = age != null ? `Tiene ${age} años (o está por cumplir ${age + 1}). ` : '';
  return { name: profile.name || 'tú', adult: age != null && age >= 18,
    about: `${years}Háblale ${GENDERS[profile.gender] || GENDERS['']}.` };
}

function fmtDate(ts) {
  const d = new Date(ts * 1000);
  return `${String(d.getDate()).padStart(2, '0')}/${String(d.getMonth() + 1).padStart(2, '0')}/${d.getFullYear()}`;
}

class Queue {
  constructor() { this.items = []; this.waiters = []; }
  put(x) { const w = this.waiters.shift(); if (w) w(x); else this.items.push(x); }
  get() { return this.items.length ? Promise.resolve(this.items.shift()) : new Promise((r) => this.waiters.push(r)); }
}
