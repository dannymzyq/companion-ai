// Captura del micrófono: filtra paso-bajo (anti-aliasing FIR de 5 tomas) y remuestrea con interpolación
// lineal fraccionaria a 16 kHz entregando tramas exactas de 512 muestras (32 ms) en PCM de 16 bits.
class MicCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.bypassFilter = Math.abs(this.ratio - 1) < 1e-3;
    this.x1 = 0;
    this.x2 = 0;
    this.x3 = 0;
    this.x4 = 0;
    this.prevY = 0;
    this.phase = 1;
    this.out = new Int16Array(512);
    this.n = 0;
    this.energy = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || !ch.length) return true;
    const ratio = this.ratio;
    for (let i = 0; i < ch.length; i++) {
      const x = ch[i];
      let cur = x;
      if (!this.bypassFilter) {
        cur = 0.1 * x + 0.225 * this.x1 + 0.35 * this.x2 + 0.225 * this.x3 + 0.1 * this.x4;
        this.x4 = this.x3;
        this.x3 = this.x2;
        this.x2 = this.x1;
        this.x1 = x;
      }
      while (this.phase <= 1) {
        const s = Math.max(-1, Math.min(1, this.prevY + (cur - this.prevY) * this.phase));
        this.energy += s * s;
        this.out[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.n === this.out.length) {
          const pcm = this.out.slice().buffer;
          this.port.postMessage({ pcm, level: Math.sqrt(this.energy / this.n) }, [pcm]);
          this.n = 0;
          this.energy = 0;
        }
        this.phase += ratio;
      }
      this.phase -= 1;
      this.prevY = cur;
    }
    return true;
  }
}

registerProcessor('mic-capture', MicCapture);
