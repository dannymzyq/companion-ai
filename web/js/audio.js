// Entrada y salida de audio: micrófono → servidor, y voz del servidor (PCM 24 kHz) → altavoces,
// reproducida sin cortes y sincronizada con las frases (emoción, gesto y subtítulo).

const VOICE_RATE = 24000;
const JITTER = 0.2;            // el contrato de voz recomienda acumular ~200 ms antes de empezar
// Bandas de formantes para la boca (lipsync.js, las de wawa-lipsync).
const LIP_BANDS = [[50, 200], [200, 400], [400, 800], [800, 1500], [1500, 2500], [2500, 4000], [4000, 8000]];

// Salida de audio y volumen elegidos en Ajustes › Voz y sonido (los usa también la muestra ▶ de las voces).
export const OUTPUT_KEY = 'companion.output', VOLUME_KEY = 'companion.volume';
export function savedOutput() { try { return localStorage.getItem(OUTPUT_KEY) || ''; } catch { return ''; } }
export function savedVolume() {
  try { const v = parseFloat(localStorage.getItem(VOLUME_KEY)); return Number.isFinite(v) ? Math.min(1.5, Math.max(0, v)) : 1; } catch { return 1; }
}
// Para un <audio> suelto (la muestra ▶): misma salida y mismo volumen que la voz.
export async function routeElement(el) {
  el.volume = Math.min(1, savedVolume());
  const id = savedOutput();
  if (id && el.setSinkId) { try { await el.setSinkId(id); } catch { /* ya no está conectada: la predeterminada */ } }
}

export class AudioIO {
  constructor({ onMic, onSentence, onPlaybackEnd }) {
    this.onMic = onMic;
    this.onSentence = onSentence;
    this.onPlaybackEnd = onPlaybackEnd;
    this.ctx = null;
    this.micLevel = 0;
    this.signalAt = 0;          // última vez que el micrófono entregó algo distinto de silencio absoluto
    this.healing = false;
    this.healLog = [];          // reaperturas automáticas del micrófono (para diagnosticar)
    this.muted = false;
    this.hasMic = false;
    this.sources = new Set();
    this.timers = new Set();
    this.nextTime = 0;
    this.pending = null;        // frase anunciada cuyo audio aún no empezó
    this.replyDone = false;
    this.active = false;        // hay una respuesta sonando o por sonar
    this.quietAt = 0;           // cuándo terminó de sonar la última respuesta
    this.screen = null;         // sonido de la pantalla compartida (ver startScreen)
  }

  // Debe llamarse desde un clic: el navegador no deja abrir audio sin un gesto del usuario.
  async init() {
    if (!this.ctx) {
      this.ctx = new AudioContext({ latencyHint: 'interactive' });
      this.gain = this.ctx.createGain();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 1024;
      this.analyser.smoothingTimeConstant = 0.5;
      // El volumen va después del analizador: la boca del avatar se mueve igual aunque el volumen esté bajo.
      this.out = this.ctx.createGain();
      this.out.gain.value = savedVolume();
      this.gain.connect(this.analyser).connect(this.out).connect(this.ctx.destination);
      this.setOutput(savedOutput()).catch(() => {});
      this.freq = new Uint8Array(this.analyser.frequencyBinCount);
      this.wave = new Float32Array(this.analyser.fftSize);
      setInterval(() => this._watch(), 80);
    }
    await this.ctx.resume();
  }

  // Pide permiso (la primera vez) y abre el micrófono elegido; sin deviceId, el predeterminado del sistema.
  // Lanza el error del navegador si el usuario lo niega o no hay ninguno.
  async openMic(deviceId) {
    await this.init();
    const base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: deviceId ? { ...base, deviceId: { exact: deviceId } } : base });
    } catch (err) {
      if (!deviceId || !['OverconstrainedError', 'NotFoundError'].includes(err.name)) throw err;
      stream = await navigator.mediaDevices.getUserMedia({ audio: base });   // el guardado ya no está conectado
    }
    if (!this.capture) {
      await this._worklet();
      this.capture = new AudioWorkletNode(this.ctx, 'mic-capture');
      this.capture.port.onmessage = (e) => {
        this.micLevel = this.muted ? 0 : e.data.level;
        if (e.data.level > 0) this.signalAt = performance.now();     // llega sonido (aunque sea ruido de fondo)
        this.onMic(e.data.pcm);
      };
      const silent = this.ctx.createGain();          // mantiene vivo el nodo de captura sin que se oiga
      silent.gain.value = 0;
      this.capture.connect(silent).connect(this.ctx.destination);
    }
    if (this.micSource) this.micSource.disconnect();
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = stream;
    this.micSource = this.ctx.createMediaStreamSource(stream);
    this.micSource.connect(this.capture);
    const track = stream.getAudioTracks()[0];
    this.micId = track.getSettings().deviceId || deviceId || '';
    this.micGroup = track.getSettings().groupId || '';
    this.micLabel = track.label;
    this.hasMic = true;
    this.setMuted(this.muted);
    // Si el sistema corta el micrófono (se desenchufa, o el dispositivo se reinicia), se vuelve a abrir solo.
    track.addEventListener('ended', () => { if (this.stream === stream) this.heal(4); });
    return { id: this.micId, label: this.micLabel };
  }

  _worklet() {
    if (!this.workletReady) this.workletReady = this.ctx.audioWorklet.addModule('js/mic-worklet.js');
    return this.workletReady;
  }

  // Sonido de lo que se comparte (vídeos, juegos, llamadas): el mismo paso a 16 kHz que el micrófono, en trozos
  // de 1 s para onChunk. Nunca va a los altavoces. Mientras Mika habla (y medio segundo después) no se entrega:
  // el sonido de la PC incluye su propia voz y no debe oírse a sí misma.
  async startScreen(stream, onChunk) {
    this.stopScreen();
    const track = stream.getAudioTracks()[0];
    if (!track) return false;
    await this.init();
    await this._worklet();
    const source = this.ctx.createMediaStreamSource(new MediaStream([track]));
    const node = new AudioWorkletNode(this.ctx, 'mic-capture');
    const silent = this.ctx.createGain();
    silent.gain.value = 0;
    source.connect(node);
    node.connect(silent).connect(this.ctx.destination);
    const parts = [];
    let n = 0;
    const screen = { track, source, node, silent, on: true, level: 0 };
    node.port.onmessage = (e) => {
      screen.level = e.data.level;
      const speaking = this.active || performance.now() - this.quietAt < 500;
      if (!screen.on || speaking) { parts.length = 0; n = 0; return; }
      const pcm = new Int16Array(e.data.pcm);
      parts.push(pcm);
      n += pcm.length;
      if (n < 16000) return;
      const out = new Int16Array(n);
      let at = 0;
      for (const p of parts) { out.set(p, at); at += p.length; }
      parts.length = 0;
      n = 0;
      onChunk(out);
    };
    this.screen = screen;
    return true;
  }

  setScreenOn(on) { if (this.screen) this.screen.on = on; }

  stopScreen() {
    const s = this.screen;
    if (!s) return;
    this.screen = null;
    s.node.port.onmessage = null;
    s.source.disconnect();
    s.node.disconnect();
    s.silent.disconnect();
  }

  // ¿El micrófono es el mismo aparato que esa cámara? (una webcam con micrófono)
  sameDeviceAs(cam) {
    if (!cam || !this.hasMic) return false;
    const usb = (label) => (/\(([0-9a-f]{4}:[0-9a-f]{4})\)/i.exec(label || '') || [])[1];
    return (!!this.micGroup && this.micGroup === cam.group) || (!!usb(this.micLabel) && usb(this.micLabel) === usb(cam.label));
  }

  // Comprueba que el micrófono sigue entregando sonido y, si no, lo vuelve a abrir (hasta `tries` veces).
  // Hace falta con las webcams que son micrófono y cámara a la vez: al apagar su vídeo, Windows reinicia el
  // dispositivo entero y el micrófono se queda «vivo» pero entregando silencio absoluto (visto con la
  // Logitech Brio). Un micrófono sano nunca da ceros exactos durante un segundo: siempre hay ruido de fondo.
  async heal(tries = 1) {
    if (!this.hasMic || this.healing) return false;
    this.healing = true;
    const wait = (ms) => new Promise((r) => setTimeout(r, ms));
    try {
      for (let i = 0; i <= tries; i++) {
        await wait(i ? 900 : 500);
        const t0 = performance.now();
        await wait(1100);
        const track = this.stream && this.stream.getAudioTracks()[0];
        const live = track && track.readyState === 'live';
        if (live && (this.muted || this.signalAt > t0)) return true;       // en silencio a propósito no se puede saber
        if (i === tries) break;
        // Primero se suelta del todo el micrófono mudo: si se abre el nuevo con el viejo aún abierto, el
        // navegador reutiliza la misma captura rota y sigue sin sonar.
        if (this.micSource) this.micSource.disconnect();
        if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
        this.micSource = this.stream = null;
        await wait(500);
        try {
          await this.openMic(this.micId);
          this.healLog.push(`${Math.round(performance.now())} reabierto (${live ? 'sin señal' : 'pista cortada'})`);
        } catch (err) {
          this.healLog.push(`${Math.round(performance.now())} no se dejó abrir: ${err.name}`);
        }
      }
      this.healLog.push(`${Math.round(performance.now())} sigue sin señal`);
      return false;
    } finally {
      this.healing = false;
    }
  }

  // Micrófonos disponibles. Los nombres solo aparecen cuando ya hay permiso.
  async listMics() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'audioinput' && d.deviceId)
      .map((d, i) => ({ id: d.deviceId, label: d.label || `Micrófono ${i + 1}` }));
  }

  // Altavoces o auriculares disponibles ('' = la salida predeterminada de Windows).
  async listOutputs() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'audiooutput' && d.deviceId && !['default', 'communications'].includes(d.deviceId))
      .map((d, i) => ({ id: d.deviceId, label: d.label || `Salida ${i + 1}` }));
  }

  // Lanza el error si esa salida ya no está; entonces se queda la anterior.
  async setOutput(id) {
    this.outputId = id || '';
    if (this.ctx && this.ctx.setSinkId) await this.ctx.setSinkId(this.outputId);
  }

  setVolume(v) {
    this.volume = Math.min(1.5, Math.max(0, v));
    if (this.out) this.out.gain.setTargetAtTime(this.volume, this.ctx.currentTime, 0.02);
  }

  setMuted(muted) {
    this.muted = muted;
    if (this.stream) this.stream.getAudioTracks().forEach((t) => (t.enabled = !muted));
  }

  // ---------------------------------------------------------------- reproducción
  beginSentence(meta) {
    this.active = true;
    this.replyDone = false;
    this._firePending();          // la anterior no trajo audio: se muestra igual
    this.pending = meta;
  }

  enqueue(buffer) {
    if (!this.ctx) return;
    const pcm = new Int16Array(buffer);
    if (!pcm.length) return;
    const audio = this.ctx.createBuffer(1, pcm.length, VOICE_RATE);
    const data = audio.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) data[i] = pcm[i] / 32768;
    const now = this.ctx.currentTime;
    if (this.nextTime < now + 0.02) this.nextTime = now + JITTER;
    const at = this.nextTime;
    const src = this.ctx.createBufferSource();
    src.buffer = audio;
    src.connect(this.gain);
    src.start(at);
    src.onended = () => this.sources.delete(src);
    this.sources.add(src);
    this.nextTime = at + audio.duration;
    this.active = true;
    if (this.pending) {
      this._schedule(this.pending, at);
      this.pending = null;
    }
  }

  endSentence() {
    if (!this.pending) return;
    // Frase sin audio (voz apagada): se muestra a su turno y se le da un tiempo de lectura.
    const meta = this.pending;
    this.pending = null;
    const now = this.ctx ? this.ctx.currentTime : 0;
    const at = Math.max(now, this.nextTime);
    this._schedule(meta, at);
    this.nextTime = at + Math.min(6, 0.6 + meta.text.length * 0.055);
  }

  markReplyDone() {
    this._firePending();
    this.replyDone = true;
  }

  flush() {
    for (const s of this.sources) {
      try { s.onended = null; s.stop(); } catch { /* ya terminó */ }
    }
    this.sources.clear();
    for (const t of this.timers) clearTimeout(t);
    this.timers.clear();
    this.pending = null;
    this.nextTime = 0;
    this.replyDone = false;
    if (this.active) this.quietAt = performance.now();
    this.active = false;
  }

  _firePending() {
    if (this.pending) this.endSentence();
  }

  _schedule(meta, at) {
    const delay = this.ctx ? Math.max(0, (at - this.ctx.currentTime) * 1000) : 0;
    const timer = setTimeout(() => {
      this.timers.delete(timer);
      this.onSentence(meta);
    }, delay);
    this.timers.add(timer);
  }

  _watch() {
    if (!this.active || !this.replyDone || !this.ctx) return;
    if (this.ctx.currentTime >= this.nextTime - 0.02 && this.timers.size === 0) {
      this.active = false;
      this.replyDone = false;
      this.quietAt = performance.now();
      this.onPlaybackEnd();
    }
  }

  // Volumen y reparto por bandas de la voz que suena: mueve la boca del avatar.
  analyse() {
    if (!this.analyser) return { vol: 0, low: 0, mid: 0, high: 0, bands: null, centroid: 0 };
    this.analyser.getFloatTimeDomainData(this.wave);
    let sum = 0;
    for (let i = 0; i < this.wave.length; i++) sum += this.wave[i] * this.wave[i];
    const vol = Math.sqrt(sum / this.wave.length);
    this.analyser.getByteFrequencyData(this.freq);
    const hz = this.ctx.sampleRate / this.analyser.fftSize;
    const band = (a, b) => {
      let s = 0;
      const i0 = Math.floor(a / hz), i1 = Math.min(this.freq.length - 1, Math.ceil(b / hz));
      for (let i = i0; i <= i1; i++) s += this.freq[i];
      return s / ((i1 - i0 + 1) * 255);
    };
    // Para la boca (lipsync.js, adaptado de wawa-lipsync): 7 bandas de formantes y el centroide del espectro.
    const bands = LIP_BANDS.map(([a, b]) => band(a, b));
    let w = 0, c = 0;
    for (let i = 0; i < this.freq.length; i++) { const v = this.freq[i] / 255; w += v; c += i * hz * v; }
    return { vol, low: band(150, 700), mid: band(700, 2000), high: band(2000, 5000), bands, centroid: w > 0 ? c / w : 0 };
  }
}
