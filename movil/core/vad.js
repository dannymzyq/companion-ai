// Detector de voz y corte de turnos, como Session._frame de companion/session.py, con los mismos umbrales.
// PROVISIONAL: la «probabilidad de voz» sale de la energía de cada trama de 32 ms respecto al ruido de fondo, no
// de Silero VAD (eso llegará con sherpa-onnx). Distingue peor la voz de otros ruidos fuertes.
export const FRAME = 512;                    // 32 ms a 16 kHz
export const FRAME_MS = FRAME * 1000 / 16000;
const START_THR = 0.5, START_FRAMES = 3;
const BARGE_THR = 0.6, BARGE_FRAMES = 8;
const END_THR = 0.35;
const PREROLL_FRAMES = 50, PREROLL_GAP = 12, PREROLL_PAD = 8;
export const MIN_SPEECH_FRAMES = 6;
const MAX_UTTERANCE_MS = 30_000;
const END_SILENCE_MS = 550;

// Energía → algo parecido a la probabilidad de Silero: 0 con el ruido de fondo, 0,5 a 4 veces su nivel, 1 a 6 veces.
export class EnergyVAD {
  constructor() { this.floor = 0.004; }
  prob(frame) {
    let e = 0;
    for (let i = 0; i < frame.length; i++) { const s = frame[i] / 32768; e += s * s; }
    const rms = Math.sqrt(e / frame.length);
    const ratio = rms / Math.max(this.floor, 0.0015);
    const p = Math.max(0, Math.min(1, (ratio - 2) / 4));
    // El ruido de fondo se sigue despacio y solo con tramas tranquilas (la voz no lo sube).
    if (ratio < 1.8) this.floor = this.floor * 0.97 + rms * 0.03;
    else if (ratio < 3) this.floor *= 1.002;
    return rms < 0.006 ? Math.min(p, 0.2) : p;
  }
}

export class TurnDetector {
  // on: { start(), end(Int16Array audio, speechFrames), isPlaying(), bargeIn }
  constructor(on) {
    this.on = on;
    this.vad = new EnergyVAD();
    this.pending = new Int16Array(0);
    this.preroll = [];
    this.inSpeech = false;
    this.run = this.silence = this.speechFrames = 0;
    this.utter = [];
  }

  feed(buffer) {
    const incoming = new Int16Array(buffer);
    const all = new Int16Array(this.pending.length + incoming.length);
    all.set(this.pending); all.set(incoming, this.pending.length);
    let pos = 0;
    while (all.length - pos >= FRAME) { this._frame(all.slice(pos, pos + FRAME)); pos += FRAME; }
    this.pending = all.slice(pos);
  }

  _frame(frame) {
    const p = this.vad.prob(frame);
    if (!this.inSpeech) {
      this.preroll.push([frame, p]);
      if (this.preroll.length > PREROLL_FRAMES) this.preroll.shift();
      const playing = this.on.isPlaying();
      if (playing && !this.on.bargeIn) { this.run = 0; return; }
      let need;
      if (playing) { this.run = p >= BARGE_THR ? this.run + 1 : Math.max(0, this.run - 1); need = BARGE_FRAMES; }
      else { this.run = p >= START_THR ? this.run + 1 : 0; need = START_FRAMES; }
      if (this.run >= need) {
        this.inSpeech = true;
        this.utter = this._speechStart();
        this.preroll = [];
        this.speechFrames = this.run; this.silence = 0; this.run = 0;
        this.on.start();
      }
      return;
    }
    this.utter.push(frame);
    if (p >= END_THR) { this.silence = 0; this.speechFrames += 1; } else { this.silence += 1; }
    if (this.silence * FRAME_MS >= END_SILENCE_MS || this.utter.length * FRAME_MS > MAX_UTTERANCE_MS) {
      this.inSpeech = false;
      const audio = new Int16Array(this.utter.length * FRAME);
      this.utter.forEach((f, i) => audio.set(f, i * FRAME));
      const frames = this.speechFrames;
      this.utter = [];
      this.on.end(audio, frames);
    }
  }

  // Desde donde de verdad empezó a hablar, para no perder las primeras palabras.
  _speechStart() {
    const items = this.preroll;
    let start = items.length - 1, gap = 0;
    for (let i = items.length - 1; i >= 0; i--) {
      if (items[i][1] >= END_THR) { start = i; gap = 0; } else if (++gap > PREROLL_GAP) break;
    }
    return items.slice(Math.max(0, start - PREROLL_PAD)).map(([f]) => f);
  }
}
