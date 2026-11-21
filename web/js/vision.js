// Los ojos de Mika: la cámara (te ve a ti) y la pantalla compartida (ve lo mismo que tú).
// Mientras una fuente está activa se toma una imagen por segundo y se entrega a onFrame; el servidor solo
// conserva la última y la adjunta a tu siguiente mensaje. Nada se graba.

const LIMITS = {
  camera: { width: 640, quality: 0.7 },
  screen: { width: 1600, quality: 0.75 },     // la pantalla necesita más detalle para que el texto se lea
};
const INTERVAL = 1000;
const WATCH_WIDTH = 640;

export class Vision {
  constructor({ onFrame, onChange }) {
    this.onFrame = onFrame;
    this.onChange = onChange;
    this.sources = {};
    this.canvas = document.createElement('canvas');
    this.small = document.createElement('canvas');
    setInterval(() => { for (const kind in this.sources) this.push(kind); }, INTERVAL);
  }

  active(kind) { return !!this.sources[kind]; }

  // Cámaras disponibles. Los nombres solo aparecen cuando ya hay permiso.
  async listCams() {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return [];
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter((d) => d.kind === 'videoinput' && d.deviceId)
      .map((d, i) => ({ id: d.deviceId, label: d.label || `Cámara ${i + 1}` }));
  }

  // Abre una cámara concreta (o la predeterminada). Sirve también para pedir el permiso y para la vista de prueba.
  async openCamera(deviceId) {
    // En un teléfono en vertical (la app de iOS), la imagen también en vertical: si no, sale recortada a lo ancho.
    const vertical = navigator.maxTouchPoints > 0 && window.matchMedia && window.matchMedia('(orientation: portrait)').matches;
    const base = vertical ? { width: { ideal: 720 }, height: { ideal: 1280 } } : { width: { ideal: 1280 }, height: { ideal: 720 } };
    const video = deviceId ? { ...base, deviceId: { exact: deviceId } } : { ...base, facingMode: 'user' };
    for (let attempt = 1; ; attempt++) {
      try {
        return await navigator.mediaDevices.getUserMedia({ video });
      } catch (err) {
        // Recién cerrada, una webcam tarda un momento en dejarse abrir otra vez: se reintenta.
        if (err.name === 'NotReadableError' && attempt < 4) { await new Promise((r) => setTimeout(r, 700)); continue; }
        if (!deviceId || !['OverconstrainedError', 'NotFoundError'].includes(err.name)) throw err;
        return navigator.mediaDevices.getUserMedia({ video: base });     // la guardada ya no está conectada
      }
    }
  }

  // Debe llamarse desde un clic. Lanza el error del navegador si el usuario lo niega.
  // `deviceId` elige la cámara; sin él se usa la predeterminada. `ready` es una cámara ya abierta (la vista
  // de prueba del inicio): se aprovecha tal cual, porque cerrar y reabrir una webcam puede dejar mudo su micrófono.
  async start(kind, deviceId, ready) {
    if (this.sources[kind]) { if (ready) ready.getTracks().forEach((t) => t.stop()); return; }
    const media = navigator.mediaDevices;
    const usable = ready && ready.getVideoTracks()[0] && ready.getVideoTracks()[0].readyState === 'live';
    const stream = usable ? ready : kind === 'camera'
      ? await this.openCamera(deviceId)
      // En un navegador se pide el sonido aquí (su casilla «Compartir audio»). En la app de escritorio, aparte
      // y después (addDesktopSound): si el sonido falla, la imagen sigue compartida.
      : await media.getDisplayMedia({ video: { frameRate: { ideal: 5 } }, audio: !window.desktop });
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    await video.play();
    const track = stream.getVideoTracks()[0];
    track.addEventListener('ended', () => this.stop(kind));   // «Dejar de compartir» del sistema, o la ventana se cerró
    const detail = kind === 'screen' ? await shareDetail(track) : null;
    if (detail && detail.wantsAudio) await addDesktopSound(stream, detail);
    this.sources[kind] = { stream, video, detail };
    if (kind === 'camera') this.lastCam = { group: track.getSettings().groupId || '', label: track.label };
    this.onChange(kind, stream, this.sources[kind].detail);
    this.push(kind);
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

  // Imagen actual como JPEG en base64 (sin el prefijo data:), o null si el vídeo aún no tiene imagen.
  // Sin `width`, al tamaño normal de esa fuente; con él, una copia más pequeña.
  grab(kind, width = LIMITS[kind].width, quality = LIMITS[kind].quality) {
    const src = this.sources[kind];
    if (!src || !src.video.videoWidth) return null;
    const scale = Math.min(1, width / src.video.videoWidth);
    const w = Math.round(src.video.videoWidth * scale), h = Math.round(src.video.videoHeight * scale);
    this.canvas.width = w;
    this.canvas.height = h;
    this.canvas.getContext('2d').drawImage(src.video, 0, 0, w, h);
    return this.canvas.toDataURL('image/jpeg', quality).split(',')[1] || null;
  }

  // Cuánto cambió la imagen desde la anterior (0..1): diferencia media de brillo en una rejilla de 24×14.
  // Con esto el servidor sabe si pasó algo y solo entonces deja que Mika mire por su cuenta.
  motion(kind) {
    const src = this.sources[kind];
    if (!src || !src.video.videoWidth) return 0;
    const W = 24, H = 14;
    this.small.width = W;
    this.small.height = H;
    const ctx = this.small.getContext('2d', { willReadFrequently: true });
    ctx.drawImage(src.video, 0, 0, W, H);
    const px = ctx.getImageData(0, 0, W, H).data;
    const now = new Float32Array(W * H);
    for (let i = 0; i < now.length; i++) now[i] = (px[i * 4] * 0.3 + px[i * 4 + 1] * 0.59 + px[i * 4 + 2] * 0.11) / 255;
    let diff = 0;
    if (src.last) for (let i = 0; i < now.length; i++) diff += Math.abs(now[i] - src.last[i]);
    const delta = src.last ? diff / now.length : 0;
    src.last = now;
    return delta;
  }

  push(kind) {
    const jpeg = this.grab(kind);
    if (!jpeg) return;
    const extra = { ...(this.detail(kind) || {}), delta: +this.motion(kind).toFixed(4) };
    // La pantalla va además en pequeño: es la copia que usa la mirada en vivo. Para notar que algo cambió
    // no hace falta leer la letra pequeña, y una imagen de 640 px le cuesta al modelo local 93 tokens en
    // vez de 629 (medido con gemma4:e4b), así que mira en una fracción del tiempo.
    if (kind === 'screen') extra.thumb = this.grab(kind, WATCH_WIDTH, 0.6);
    this.onFrame(kind, jpeg, extra);
  }
}

// Qué se está compartiendo: la pantalla entera o una sola ventana (y cuál). En la app de escritorio lo dice
// la ventana de selección; en un navegador, la propia pista de vídeo.
async function shareDetail(track) {
  let info = null;
  try { info = await window.desktop?.shareInfo?.(); } catch { /* sin app de escritorio */ }
  const surface = track.getSettings().displaySurface;                  // monitor | window | browser
  const kind = info?.kind || (surface && surface !== 'monitor' ? 'window' : 'screen');
  const out = { surface: kind, name: info?.name || '' };
  if (info?.audio) out.wantsAudio = true;          // en la ventana de selección se activó «Escuchar también el sonido»
  return out;
}

// El sonido de toda la PC, pedido aparte de la imagen (la app de escritorio responde sin volver a preguntar).
// Llega junto con una imagen de pantalla que no se usa: se para al momento. Si falla, se apunta el motivo en
// detail.audioError y se comparte solo la imagen.
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
    window.desktop.shareAudioNext(false).catch(() => {});     // que el próximo «Compartir» vuelva a preguntar
    detail.audioError = `${err.name || 'Error'}: ${err.message || err}`;
    console.warn('Sin sonido de la PC:', err);
  }
}
