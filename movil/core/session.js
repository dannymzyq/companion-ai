// Port de la parte del turno de companion/session.py: texto (o lo que oyó el oído) → LLM → frases con sus
// etiquetas → voz → interfaz. Habla el mismo protocolo que /ws (ver el docstring de session.py), así que
// web/js/main.js no sabe que no hay servidor.
import * as llm from './llm.js';
import * as store from './store.js';
import { adultActive, buildSystemPrompt, fill, GENDERS, GREETING, localTime, samplingFor, SUMMARIZE, turnContext } from './prompt.js';
import { TagStream } from './tags.js';

const HISTORY_KEEP = 14, HISTORY_MAX = 28;
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
  // ctx: { persona(), profile(), voice: { speak(text, voice) → async iterable de ArrayBuffer (PCM 24 kHz) } | null }
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
    } else if (kind === 'playback_end') {
      this.lastTalk = Date.now();
      this.clientPlaying = false;
      if (!this.turn) this.setState('idle');
    }
    // watch, frame, screen_audio, action_answer…: no existen en el teléfono.
  }

  _start(text, instruction) {
    const turn = { cancelled: false };
    turn.done = this._runTurn(text, instruction, turn).catch((e) => {
      if (!turn.cancelled) { console.error(e); this.send({ type: 'error', message: String(e.message || e) }); }
    }).finally(() => { if (this.turn === turn) this.turn = null; if (!this.clientPlaying && !this.turn) this.setState('idle'); });
    this.turn = turn;
  }

  async interrupt() {
    const t = this.turn;
    if (!t) return;
    t.cancelled = true;
    this.turn = null;
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
    return buildSystemPrompt(p, { userName: prof.name, memories: store.memories(), adult, about: prof.about, summaries: past });
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
      last.content = `${turnContext(localTime())}${done}\n${last.content}`;
    }
    return messages;
  }

  async _runTurn(text, instruction, turn) {
    const t0 = performance.now();
    let msgId = null;
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
    if (turn.cancelled) { this._savePartial(msgId, parser); return; }
    if (failure) {
      this._savePartial(msgId, parser);
      this.send({ type: 'error', message: failure });
      return;
    }
    const full = parser.spoken.join(' ');
    if (full) store.addMessage('assistant', full, this.emotion);
    for (const fact of parser.memories) store.addMemory(fact);
    this.send({ type: 'reply_end', text: full });
  }

  _savePartial(msgId, parser) {
    const said = parser.spoken.join(' ');
    if (said) store.addMessage('assistant', said + ' …', this.emotion);
    else if (msgId != null && !said) { /* el mensaje del usuario se queda: lo dijo */ }
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
      if (idx === 1) console.info(`Primera frase a los ${((performance.now() - t0) / 1000).toFixed(2)} s`);
      if (voice && voiceOk) {
        try {
          for await (const pcm of voice.speak(s.text)) {
            if (turn.cancelled) return;
            if (!this.clientPlaying) { this.clientPlaying = true; this.setState('speaking'); }
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
