// Ritmo musical compartido (N-01): analiza en tiempo real los graves (60–155 Hz) del audio compartido de pantalla
// o pestaña (audio.screen.analyser) sin enviarlo a la nube ni reservar memoria por fotograma. Cuando detecta pulso
// musical sostenido, devuelve { beat: 0..1, bpm: 68..175, active: bool } para acompasar cabeza, hombros y bailes.

const clamp = (x, a, b) => Math.max(a, Math.min(b, x));

export class MusicTracker {
  constructor() {
    this._bins = null;
    this.fast = 0;
    this.slow = 0;
    this.pulse = 0;
    this.lastBeatMs = 0;
    this.activeUntil = 0;
    this.phase = 0;
    this._lastUpdateMs = 0;
    this._intervals = new Float32Array(6);
    this._intCount = 0;
    this._intHead = 0;
    this._sortBuf = new Float32Array(6);
    this._streak = 0;
    this.out = { beat: 0, bpm: 120, active: false };
  }

  update(audio, nowMs = performance.now()) {
    const out = this.out;
    const dt = this._lastUpdateMs ? Math.min(0.1, Math.max(0, (nowMs - this._lastUpdateMs) / 1000)) : 0.016;
    this._lastUpdateMs = nowMs;

    const scr = audio && audio.screen;
    if (!scr || !scr.on || !scr.analyser || !audio.ctx || audio.active) {
      this.pulse *= 0.84;
      out.beat = this.pulse > 0.01 ? this.pulse : 0;
      out.active = false;
      this._streak = 0;
      return out;
    }

    const an = scr.analyser;
    const binCount = an.frequencyBinCount;
    if (!this._bins || this._bins.length !== binCount) {
      this._bins = new Uint8Array(binCount);
    }
    an.getByteFrequencyData(this._bins);

    const hz = audio.ctx.sampleRate / an.fftSize;
    const i0 = Math.max(1, Math.floor(60 / hz));
    const i1 = Math.min(binCount - 1, Math.ceil(155 / hz));
    let sum = 0;
    for (let i = i0; i <= i1; i++) sum += this._bins[i];
    const bass = sum / (Math.max(1, i1 - i0 + 1) * 255);

    // También comprobamos presencia media-alta para distinguir golpes rítmicos reales de un zumbido continuo.
    const m0 = Math.min(binCount - 1, Math.floor(250 / hz));
    const m1 = Math.min(binCount - 1, Math.ceil(2400 / hz));
    let mSum = 0;
    for (let i = m0; i <= m1; i++) mSum += this._bins[i];
    const mid = mSum / (Math.max(1, m1 - m0 + 1) * 255);

    this.fast += (bass - this.fast) * Math.min(1, dt * 28);
    this.slow += (bass - this.slow) * Math.min(1, dt * 2.6);

    const diff = this.fast - this.slow;
    if (bass > 0.13 && mid > 0.03 && diff > 0.045 && this.fast > this.slow * 1.28 && nowMs - this.lastBeatMs > 295) {
      const gap = nowMs - this.lastBeatMs;
      this.lastBeatMs = nowMs;
      if (gap >= 335 && gap <= 900) {
        this._intervals[this._intHead] = gap;
        this._intHead = (this._intHead + 1) % this._intervals.length;
        if (this._intCount < this._intervals.length) this._intCount++;
        this._streak = Math.min(12, this._streak + 1);
        if (this._intCount >= 3) {
          for (let i = 0; i < this._intCount; i++) this._sortBuf[i] = this._intervals[i];
          const sub = this._sortBuf.subarray(0, this._intCount);
          sub.sort();
          const med = sub[Math.floor(this._intCount / 2)];
          out.bpm = Math.round(clamp(60000 / med, 68, 175));
        }
      } else if (gap > 1800) {
        this._streak = 1;
      }
      if (this._streak >= 2) {
        this.pulse = clamp(0.55 + diff * 3.2, 0, 1);
        this.activeUntil = nowMs + 2600;
        this.phase = 0;
      }
    } else {
      this.pulse *= Math.exp(-9 * dt);
    }

    const active = nowMs < this.activeUntil && this._streak >= 2;
    out.active = active;
    if (active) {
      this.phase += dt * Math.PI * 2 * (out.bpm / 60);
      const groove = 0.28 * Math.max(0, Math.sin(this.phase));
      out.beat = clamp(Math.max(this.pulse, groove), 0, 1);
    } else {
      out.beat = this.pulse > 0.01 ? this.pulse : 0;
    }
    return out;
  }
}
