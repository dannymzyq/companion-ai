// Port de companion/tags.py: convierte el texto que va llegando del LLM en frases listas para la voz.
// Las etiquetas [emo:…], [gesto:…], [recordar: …] y [accion: …] nunca se leen en voz alta.
import { EMOTIONS, GESTURES } from './prompt.js';

const BRACKET = /\[[^\]]*\]/g;
const TAG = /^\[\s*([\p{L}_]+)\s*:\s*([^\]]*)\]$/u;
const SENTENCE_END = /[.!?…]+["»)']*\s+|\n+/g;
const CLAUSE_END = /[,;:]\s+/g;
const MARKDOWN = /[*_`#~\u{1F000}-\u{1FAFF}☀-➿️‍]+/gu;   // y emojis
const HAS_WORD = /[\p{L}\p{N}_]/u;

const FIRST_MIN = 12, NEXT_MIN = 28, CLAUSE_AT = 90;
const HOLD_TAG = 300;

// 'Tímida' → 'timida', 'cariñosa' → 'carinosa'
export function plain(s) {
  return s.trim().toLowerCase().normalize('NFD').replace(/\p{Mn}/gu, '').replace(/ /g, '_');
}

export class TagStream {
  constructor() {
    this.raw = '';
    this.cur = '';
    this.emotion = null;
    this.gestures = [];
    this.memories = [];
    this.actions = [];
    this.count = 0;
    this.spoken = [];
  }

  feed(chunk) {
    this.raw += chunk;
    const cut = this.raw.lastIndexOf('[');
    let ready;
    if (cut !== -1 && !this.raw.slice(cut).includes(']') && this.raw.length - cut < HOLD_TAG) {
      ready = this.raw.slice(0, cut);
      this.raw = this.raw.slice(cut);
    } else {
      ready = this.raw;
      this.raw = '';
    }
    return this._consume(ready, false);
  }

  flush() {
    let rest = this.raw;
    this.raw = '';
    const cut = rest.lastIndexOf('[');
    if (cut !== -1 && !rest.slice(cut).includes(']')) rest = rest.slice(0, cut);
    return this._consume(rest, true);
  }

  _consume(ready, final) {
    const out = [];
    let pos = 0;
    for (const m of ready.matchAll(BRACKET)) {
      this._text(ready.slice(pos, m.index), out);
      this._tag(m[0], out);
      pos = m.index + m[0].length;
    }
    this._text(ready.slice(pos), out);
    if (final && this.cur.trim()) {
      this._emit(this.cur, out);
      this.cur = '';
    }
    return out;
  }

  _tag(raw, out) {
    const m = TAG.exec(raw);
    if (!m) return;
    const kind = plain(m[1]);
    const value = m[2].trim();
    const isEmo = kind === 'emo' && EMOTIONS.includes(plain(value));
    const isGesture = kind === 'gesto' && GESTURES.includes(plain(value));
    if ((isEmo || isGesture) && HAS_WORD.test(this.cur)) {
      this._emit(this.cur, out);
      this.cur = '';
    }
    if (isEmo) this.emotion = plain(value);
    else if (isGesture) this.gestures.push(plain(value));
    else if (kind === 'recordar' && value) this.memories.push(value.slice(0, 300));
    else if (kind === 'accion' && value) {
      const parts = value.split('|').map((p) => p.trim());
      if (parts[0]) this.actions.push([parts[0], parts.slice(1)]);
    }
  }

  _text(text, out) {
    this.cur += text;
    while (true) {
      const idx = this._boundary();
      if (idx == null) return;
      const sentence = this.cur.slice(0, idx);
      this.cur = this.cur.slice(idx);
      this._emit(sentence, out);
    }
  }

  _boundary() {
    const minimum = this.count === 0 ? FIRST_MIN : NEXT_MIN;
    for (const m of this.cur.matchAll(SENTENCE_END)) {
      const end = m.index + m[0].length;
      if (this.cur.slice(0, end).trim().length >= minimum) return end;
    }
    if (this.cur.length > CLAUSE_AT) {
      let last = null;
      for (const m of this.cur.matchAll(CLAUSE_END)) {
        const end = m.index + m[0].length;
        if (end >= 40) last = end;
      }
      return last;
    }
    return null;
  }

  _emit(text, out) {
    const clean = text.replace(MARKDOWN, '').replace(/\s+/g, ' ').trim();
    if (!HAS_WORD.test(clean)) return;
    out.push({ text: clean, emotion: this.emotion, gestures: this.gestures });
    this.spoken.push(clean);
    this.emotion = null;
    this.gestures = [];
    this.count += 1;
  }
}
