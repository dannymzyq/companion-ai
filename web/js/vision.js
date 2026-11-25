// Los ojos de Mika: la cámara (te ve a ti) y la pantalla compartida (ve lo mismo que tú).
// Mientras una fuente está activa se comprueba cada segundo si cambió; si la imagen está estática, ahorra CPU y red.

const LIMITS = {
  camera: { width: 640, quality: 0.7 },
  screen: { width: 1600, quality: 0.75 },
};
const INTERVAL = 1000;
const WATCH_WIDTH = 640;
const STATIC_DELTA = 0.0012;
const HEARTBEAT_MS = 15000;
const MOTION_W = 24, MOTION_H = 14;

function blobToBase64(blob) {
  return new Promise((resolve) => {
    if (!blob) return resolve(null);
    const reader = new FileReader();
    reader.onloadend = () => {
      const res = typeof reader.result === 'string' ? reader.result : '';
      const comma = res.indexOf(',');
      resolve(comma >= 0 ? res.slice(comma + 1) : null);
    };
    reader.onerror = () => resolve(null);
    reader.readAsDataURL(blob);
  });
}

function canvasToJpegBase64(canvas, quality) {
  if (!canvas.toBlob) return Promise.resolve(canvas.toDataURL('image/jpeg', quality).split(',')[1] || null);
  return new Promise((resolve) => canvas.toBlob((b) => blobToBase64(b).then(resolve), 'image/jpeg', quality));
}

export class Vision {
  constructor({ onFrame, onChange }) {
    this.onFrame = onFrame;
    this.onChange = onChange;
    this.sources = {};
    this.canvas = document.createElement('canvas');
    this.canvasCtx = this.canvas.getContext('2d');
    this.thumbCanvas = document.createElement('canvas');
    this.thumbCtx = this.thumbCanvas.getContext('2d');
    this.small = document.createElement('canvas');
    this.small.width = MOTION_W;
    this.small.height = MOTION_H;
    this.smallCtx = this.small.getContext('2d', { willReadFrequently: true });
    setInterval(() => { for (const kind in this.sources) this.push(kind); }, INTERVAL);
  }

  active(kind) { return !!this.sources[kind]; }

  async listCams() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'videoinput' && d.deviceId)
      .map((d, i) => ({ id: d.deviceId, label: d.label || `Cámara ${i + 1}` }));
  }

  async openCamera(deviceId) {
    const vertical = navigator.maxTouchPoints > 0 && window.matchMedia && window.matchMedia('(orientation: portrait)').matches;
    const base = vertical ? {} : { width: { ideal: 1280 }, height: { ideal: 720 } };
    const video = deviceId ? { ...base, deviceId: { exact: deviceId } } : { ...base, facingMode: 'user' };
    for (let attempt = 1; ; attempt++) {
      try {
        return await navigator.mediaDevices.getUserMedia({ video });
      } catch (err) {
        if (err.name === 'NotReadableError' && attempt < 4) { await new Promise((r) => setTimeout(r, 700)); continue; }
        if (!deviceId || !['OverconstrainedError', 'NotFoundError'].includes(err.name)) throw err;
        return navigator.mediaDevices.getUserMedia({ video: base });
      }
    }
  }

  async start(kind, deviceId, ready) {
    if (this.sources[kind]) { if (ready) ready.getTracks().forEach((t) => t.stop()); return; }
    const media = navigator.mediaDevices;
    const usable = ready && ready.getVideoTracks()[0] && ready.getVideoTracks()[0].readyState === 'live';
    let stream;
    if (usable) {
      stream = ready;
    } else if (kind === 'camera') {
      stream = await this.openCamera(deviceId);
    } else {
      try {
        stream = await media.getDisplayMedia({ video: { frameRate: { ideal: 5 } }, audio: true });
      } catch (err) {
        if (!window.desktop || err.name === 'AbortError' || err.name === 'NotAllowedError') throw err;
        const ok = await window.desktop.shareRetryVideo?.().catch(() => false);
        if (!ok) throw err;
        stream = await media.getDisplayMedia({ video: { frameRate: { ideal: 5 } }, audio: false });
      }
    }
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    await video.play();
    const track = stream.getVideoTracks()[0];
    track.addEventListener('ended', () => this.stop(kind));
    const detail = kind === 'screen' ? await shareDetail(track) : null;
    if (detail && detail.wantsAudio && stream.getAudioTracks().length === 0) {
      await addDesktopSound(stream, detail);
    } else if (detail) {
      delete detail.wantsAudio;
    }
    this.sources[kind] = {
      stream, video, detail,
      bufA: new Float32Array(MOTION_W * MOTION_H),
      bufB: new Float32Array(MOTION_W * MOTION_H),
      hasLast: false,
      useA: true,
      sentAt: 0,
      busy: false,
    };
    if (kind === 'camera') this.lastCam = { group: track.getSettings().groupId || '', label: track.label };
    this.onChange(kind, stream, this.sources[kind].detail);
    this.push(kind, true);
  }

  detail(kind) { return this.sources[kind]?.detail || null; }

  stop(kind) {
    const src = this.sources[kind];
    if (!src) return;
    delete this.sources[kind];
    src.stream.getTracks().forEach((t) => t.stop());
    src.video.srcObject = null;
    this.onChange(kind, null);
  }

  toggle(kind, deviceId) { return this.active(kind) ? this.stop(kind) : this.start(kind, deviceId); }

  _drawToMain(src, width) {
    const scale = Math.min(1, width / src.video.videoWidth);
    const w = Math.max(1, Math.round(src.video.videoWidth * scale));
    const h = Math.max(1, Math.round(src.video.videoHeight * scale));
    if (this.canvas.width !== w) this.canvas.width = w;
    if (this.canvas.height !== h) this.canvas.height = h;
    this.canvasCtx.drawImage(src.video, 0, 0, w, h);
    return { w, h };
  }

  grab(kind, width = LIMITS[kind].width, quality = LIMITS[kind].quality) {
    const src = this.sources[kind];
    if (!src || !src.video.videoWidth) return null;
    this._drawToMain(src, width);
    return this.canvas.toDataURL('image/jpeg', quality).split(',')[1] || null;
  }

  // Diferencia media de brillo 24×14 con doble buffer Float32Array reutilizable (cero asignaciones por segundo).
  motion(kind) {
    const src = this.sources[kind];
    if (!src || !src.video.videoWidth) return 0;
    this.smallCtx.drawImage(src.video, 0, 0, MOTION_W, MOTION_H);
    const px = this.smallCtx.getImageData(0, 0, MOTION_W, MOTION_H).data;
    const now = src.useA ? src.bufA : src.bufB;
    const prev = src.useA ? src.bufB : src.bufA;
    for (let i = 0; i < now.length; i++) {
      now[i] = (px[i * 4] * 0.3 + px[i * 4 + 1] * 0.59 + px[i * 4 + 2] * 0.11) / 255;
    }
    let diff = 0;
    if (src.hasLast) {
      for (let i = 0; i < now.length; i++) diff += Math.abs(now[i] - prev[i]);
    }
    const delta = src.hasLast ? diff / now.length : 1;
    src.hasLast = true;
    src.useA = !src.useA;
    return delta;
  }

  async push(kind, force = false) {
    const src = this.sources[kind];
    if (!src || !src.video.videoWidth || src.busy) return;
    const delta = this.motion(kind);
    const now = performance.now();
    if (!force && src.sentAt > 0 && delta < STATIC_DELTA && now - src.sentAt < HEARTBEAT_MS) return;

    src.busy = true;
    try {
      const lim = LIMITS[kind];
      const { w, h } = this._drawToMain(src, lim.width);
      const jpeg = await canvasToJpegBase64(this.canvas, lim.quality);
      if (!jpeg || this.sources[kind] !== src) return;
      const extra = { ...(this.detail(kind) || {}), delta: +delta.toFixed(4) };
      if (kind === 'screen') {
        const ts = Math.min(1, WATCH_WIDTH / w);
        const tw = Math.max(1, Math.round(w * ts)), th = Math.max(1, Math.round(h * ts));
        if (this.thumbCanvas.width !== tw) this.thumbCanvas.width = tw;
        if (this.thumbCanvas.height !== th) this.thumbCanvas.height = th;
        this.thumbCtx.drawImage(this.canvas, 0, 0, tw, th);
        extra.thumb = await canvasToJpegBase64(this.thumbCanvas, 0.6);
      }
      src.sentAt = performance.now();
      if (this.sources[kind] === src) this.onFrame(kind, jpeg, extra);
    } finally {
      src.busy = false;
    }
  }
}

async function shareDetail(track) {
  let info = null;
  try { info = await window.desktop?.shareInfo?.(); } catch { /* sin app de escritorio */ }
  const surface = track.getSettings().displaySurface;
  const kind = info?.kind || (surface && surface !== 'monitor' ? 'window' : 'screen');
  const out = { surface: kind, name: info?.name || '' };
  if (info?.audio) out.wantsAudio = true;
  return out;
}

async function addDesktopSound(stream, detail) {
  delete detail.wantsAudio;
  let extra = null;
  try {
    if (!(await window.desktop.shareAudioNext())) throw new Error('la app no aceptó la petición de sonido');
    extra = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
    extra.getVideoTracks().forEach((t) => t.stop());
    const sound = extra.getAudioTracks()[0];
    if (!sound) throw new Error('Windows no entregó el sonido');
    stream.addTrack(sound);
  } catch (err) {
    if (extra) extra.getTracks().forEach((t) => t.stop());
    window.desktop.shareAudioNext(false).catch(() => {});
    detail.audioError = `${err.name || 'Error'}: ${err.message || err}`;
    console.warn('Sin sonido de la PC:', err);
  }
}
