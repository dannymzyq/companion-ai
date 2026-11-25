// Entrada y salida de audio: micrófono → servidor, y voz del servidor (PCM 24 kHz) → altavoces,
// reproducida sin cortes y sincronizada con las frases (emoción, gesto y subtítulo).

const VOICE_RATE = 24000;
const JITTER_INITIAL = 0.14;
const JITTER_CONT = 0.08;
// Bandas de formantes para la boca (lipsync.js).
const LIP_BANDS = [[50, 200], [200, 400], [400, 800], [800, 1500], [1500, 2500], [2500, 4000], [4000, 8000]];
const SILENT_PCM = new Int16Array(512).buffer;

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
    this._muteTail = 0;
    this.hasMic = false;
    this.sources = new Set();
    this.timers = new Set();
    this._endTimer = 0;
    this.nextTime = 0;
    this.pending = null;        // frase anunciada cuyo audio aún no empezó
    this.replyDone = false;
    this.active = false;        // hay una respuesta sonando o por sonar
    this.quietAt = 0;           // cuándo terminó de sonar la última respuesta
    this.screen = null;         // sonido de la pantalla compartida (ver startScreen)
    this.volume = savedVolume();
    this._bargeFrames = 0;
    this._ducked = false;
    this._duckQuietAt = 0;
    this._bands = new Float32Array(7);
    this._emptyAnalysis = { vol: 0, low: 0, mid: 0, high: 0, bands: null, centroid: 0 };
    this._analysis = { vol: 0, low: 0, mid: 0, high: 0, bands: this._bands, centroid: 0 };
  }

  // Debe llamarse desde un clic: el navegador no deja abrir audio sin un gesto del usuario.
  async init() {
    if (!this.ctx) {
      this.ctx = new AudioContext({ latencyHint: 'interactive' });
      this.gain = this.ctx.createGain();
      this.analyser = this.ctx.createAnalyser();
      this.analyser.fftSize = 2048;
      this.analyser.smoothingTimeConstant = 0.35;
      // El volumen va después del analizador: la boca del avatar se mueve igual aunque el volumen esté bajo.
      this.out = this.ctx.createGain();
      this.volume = savedVolume();
      this.out.gain.value = this.volume;
      this.gain.connect(this.analyser).connect(this.out).connect(this.ctx.destination);
      this.setOutput(savedOutput()).catch(() => {});
      this.freq = new Uint8Array(this.analyser.frequencyBinCount);
      this.wave = new Float32Array(this.analyser.fftSize);
    }
    await this.ctx.resume();
  }

  async openMic(deviceId) {
    await this.init();
    const base = { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 };
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: deviceId ? { ...base, deviceId: { exact: deviceId } } : base });
    } catch (err) {
      if (!deviceId || !['OverconstrainedError', 'NotFoundError'].includes(err.name)) throw err;
      stream = await navigator.mediaDevices.getUserMedia({ audio: base });
    }
    if (!this.capture) {
      await this._worklet();
      this.capture = new AudioWorkletNode(this.ctx, 'mic-capture');
      this.capture.port.onmessage = (e) => {
        const lvl = e.data.level;
        if (lvl > 0) this.signalAt = performance.now();
        if (this.muted) {
          this.micLevel = 0;
          this._bargeFrames = 0;
          if (this._ducked) this._setDucked(false);
          if (this._muteTail > 0) {
            this._muteTail--;
            this.onMic(SILENT_PCM.slice(0));
          }
          return;
        }
        this.micLevel = lvl;
        // Atenuación local (barge-in suave): si el usuario habla encima >160 ms mientras Mika suena, baja un poco su voz.
        if (this.active && lvl > 0.038) {
          this._bargeFrames++;
          this._duckQuietAt = performance.now();
          if (this._bargeFrames >= 5 && !this._ducked) this._setDucked(true);
        } else {
          this._bargeFrames = 0;
          if (this._ducked && (!this.active || performance.now() - this._duckQuietAt > 420)) this._setDucked(false);
        }
        this.onMic(e.data.pcm);
      };
      const silent = this.ctx.createGain();
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
    track.addEventListener('ended', () => { if (this.stream === stream) this.heal(4); });
    return { id: this.micId, label: this.micLabel };
  }

  _setDucked(on) {
    this._ducked = on;
    if (!this.out || !this.ctx) return;
    const target = on ? this.volume * 0.32 : this.volume;
    this.out.gain.setTargetAtTime(target, this.ctx.currentTime, on ? 0.03 : 0.08);
  }

  _worklet() {
    if (!this.workletReady) this.workletReady = this.ctx.audioWorklet.addModule('js/mic-worklet.js');
    return this.workletReady;
  }

  // Sonido de lo que se comparte (vídeos, juegos, llamadas, música): paso a 16 kHz en trozos de 1 s para onChunk,
  // más un AnalyserNode ligero para detectar el pulso musical en tiempo real (music.js) sin tocar los altavoces.
  async startScreen(stream, onChunk) {
    this.stopScreen();
    const track = stream.getAudioTracks()[0];
    if (!track) return false;
    await this.init();
    await this._worklet();
    const source = this.ctx.createMediaStreamSource(new MediaStream([track]));
    const node = new AudioWorkletNode(this.ctx, 'mic-capture');
    const analyser = this.ctx.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.25;
    const silent = this.ctx.createGain();
    silent.gain.value = 0;
    source.connect(analyser);
    source.connect(node);
    node.connect(silent).connect(this.ctx.destination);
    const parts = [];
    let n = 0;
    const flushParts = () => {
      const out = new Int16Array(n);
      let at = 0;
      for (const p of parts) { out.set(p, at); at += p.length; }
      parts.length = 0;
      n = 0;
      onChunk(out);
    };
    const screen = { track, source, node, analyser, silent, on: true, level: 0 };
    node.port.onmessage = (e) => {
      screen.level = e.data.level;
      const speaking = this.active || performance.now() - this.quietAt < 500;
      if (!screen.on || speaking) {
        if (screen.on && speaking && n >= 4800) flushParts();
        else { parts.length = 0; n = 0; }
        return;
      }
      const pcm = new Int16Array(e.data.pcm);
      parts.push(pcm);
      n += pcm.length;
      if (n < 16000) return;
      flushParts();
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
    s.analyser.disconnect();
    s.node.disconnect();
    s.silent.disconnect();
  }

  sameDeviceAs(cam) {
    if (!cam || !this.hasMic) return false;
    const usb = (label) => (/\(([0-9a-f]{4}:[0-9a-f]{4})\)/i.exec(label || '') || [])[1];
    return (!!this.micGroup && this.micGroup === cam.group) || (!!usb(this.micLabel) && usb(this.micLabel) === usb(cam.label));
  }

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
        if (live && (this.muted || this.signalAt > t0)) return true;
        if (i === tries) break;
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

  async listMics() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'audioinput' && d.deviceId)
      .map((d, i) => ({ id: d.deviceId, label: d.label || `Micrófono ${i + 1}` }));
  }

  async listOutputs() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'audiooutput' && d.deviceId && !['default', 'communications'].includes(d.deviceId))
      .map((d, i) => ({ id: d.deviceId, label: d.label || `Salida ${i + 1}` }));
  }

  async setOutput(id) {
    this.outputId = id || '';
    if (this.ctx && this.ctx.setSinkId) await this.ctx.setSinkId(this.outputId);
  }

  setVolume(v) {
    this.volume = Math.min(1.5, Math.max(0, v));
    if (this.out && this.ctx) {
      const target = this._ducked ? this.volume * 0.32 : this.volume;
      this.out.gain.setTargetAtTime(target, this.ctx.currentTime, 0.02);
    }
  }

  setMuted(muted) {
    const wasMuted = this.muted;
    this.muted = muted;
    if (muted && !wasMuted) this._muteTail = 2;
    if (this.stream) this.stream.getAudioTracks().forEach((t) => (t.enabled = !muted));
  }

  // ---------------------------------------------------------------- reproducción
  beginSentence(meta) {
    this.active = true;
    this.replyDone = false;
    this._firePending();
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
    if (this.nextTime < now + 0.015) {
      this.nextTime = now + (this.sources.size === 0 ? JITTER_INITIAL : JITTER_CONT);
    }
    const at = this.nextTime;
    const src = this.ctx.createBufferSource();
    src.buffer = audio;
    src.connect(this.gain);
    src.start(at);
    src.onended = () => {
      this.sources.delete(src);
      this._checkEnd();
    };
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
    const meta = this.pending;
    this.pending = null;
    const now = this.ctx ? this.ctx.currentTime : 0;
    const at = Math.max(now, this.nextTime);
    this._schedule(meta, at);
    this.nextTime = at + Math.min(6, 0.6 + meta.text.length * 0.055);
    this._armEndTimer();
  }

  markReplyDone() {
    this._firePending();
    this.replyDone = true;
    this._checkEnd();
  }

  flush() {
    if (this._endTimer) { clearTimeout(this._endTimer); this._endTimer = 0; }
    if (this.ctx && this.gain && this.sources.size > 0) {
      // Rampa de 10 ms sobre el nodo saliente para evitar chasquidos al interrumpir, dejando un gain limpio para lo nuevo.
      const oldGain = this.gain;
      const now = this.ctx.currentTime;
      try {
        oldGain.gain.cancelScheduledValues(now);
        oldGain.gain.setValueAtTime(oldGain.gain.value, now);
        oldGain.gain.linearRampToValueAtTime(0.0001, now + 0.01);
      } catch { /* ignorar */ }
      const oldSources = [...this.sources];
      this.sources.clear();
      for (const s of oldSources) {
        try { s.onended = null; s.stop(now + 0.012); } catch { /* ya terminó */ }
      }
      setTimeout(() => { try { oldGain.disconnect(); } catch {} }, 35);
      this.gain = this.ctx.createGain();
      this.gain.connect(this.analyser);
    } else {
      for (const s of this.sources) {
        try { s.onended = null; s.stop(); } catch {}
      }
      this.sources.clear();
    }
    for (const t of this.timers) clearTimeout(t);
    this.timers.clear();
    this.pending = null;
    this.nextTime = 0;
    this.replyDone = false;
    this._bargeFrames = 0;
    if (this._ducked) this._setDucked(false);
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
      this._checkEnd();
    }, delay);
    this.timers.add(timer);
  }

  _armEndTimer() {
    if (this._endTimer) return;
    const waitMs = this.ctx ? Math.max(30, (this.nextTime - this.ctx.currentTime) * 1000 + 25) : 50;
    this._endTimer = setTimeout(() => {
      this._endTimer = 0;
      this._checkEnd();
    }, waitMs);
  }

  _checkEnd() {
    if (!this.active || !this.replyDone) return;
    if (!this.ctx) {
      if (this.timers.size > 0) return;
      if (this._endTimer) { clearTimeout(this._endTimer); this._endTimer = 0; }
      this.active = false;
      this.replyDone = false;
      this.nextTime = 0;
      this._bargeFrames = 0;
      if (this._ducked) this._setDucked(false);
      this.quietAt = performance.now();
      this.onPlaybackEnd();
      return;
    }
    if (this.sources.size === 0 && this.timers.size === 0 && this.ctx.currentTime >= this.nextTime - 0.02) {
      if (this._endTimer) { clearTimeout(this._endTimer); this._endTimer = 0; }
      this.active = false;
      this.replyDone = false;
      this._bargeFrames = 0;
      if (this._ducked) this._setDucked(false);
      this.quietAt = performance.now();
      this.onPlaybackEnd();
    } else if (this.sources.size === 0) {
      this._armEndTimer();
    }
  }

  // Volumen y reparto por bandas de la voz que suena: cero reservas por fotograma.
  analyse() {
    if (!this.analyser || !this.active) return this._emptyAnalysis;
    this.analyser.getFloatTimeDomainData(this.wave);
    let sum = 0;
    for (let i = 0; i < this.wave.length; i++) sum += this.wave[i] * this.wave[i];
    const vol = Math.sqrt(sum / this.wave.length);
    this.analyser.getByteFrequencyData(this.freq);
    const hz = this.ctx.sampleRate / this.analyser.fftSize;
    const maxBin = this.freq.length - 1;
    const band = (a, b) => {
      let s = 0;
      const i0 = Math.floor(a / hz), i1 = Math.min(maxBin, Math.ceil(b / hz));
      for (let i = i0; i <= i1; i++) s += this.freq[i];
      return s / ((i1 - i0 + 1) * 255);
    };
    const bands = this._bands;
    for (let k = 0; k < 7; k++) bands[k] = band(LIP_BANDS[k][0], LIP_BANDS[k][1]);
    let w = 0, c = 0;
    for (let i = 0; i <= maxBin; i++) { const v = this.freq[i] / 255; w += v; c += i * hz * v; }
    const out = this._analysis;
    out.vol = vol;
    out.low = band(150, 700);
    out.mid = band(700, 2000);
    out.high = band(2000, 5000);
    out.centroid = w > 0 ? c / w : 0;
    return out;
  }
}
