// Captura del micrófono: baja la frecuencia de muestreo a 16 kHz y entrega tramas de 512 muestras (32 ms)
// en PCM de 16 bits, que es lo que espera el servidor.
class MicCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.acc = 0;
    this.count = 0;
    this.pos = 0;
    this.out = new Int16Array(512);
    this.n = 0;
    this.energy = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    for (let i = 0; i < ch.length; i++) {
      this.acc += ch[i];
      this.count++;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const s = Math.max(-1, Math.min(1, this.acc / this.count));
        this.acc = 0;
        this.count = 0;
        this.energy += s * s;
        this.out[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.n === this.out.length) {
          const pcm = this.out.slice().buffer;
          this.port.postMessage({ pcm, level: Math.sqrt(this.energy / this.n) }, [pcm]);
          this.n = 0;
          this.energy = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor('mic-capture', MicCapture);
