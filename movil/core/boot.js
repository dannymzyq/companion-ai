// Se ejecuta antes que la interfaz (iOS: WKUserScript al empezar el documento; Android: lo mismo con su WebView).
// Sustituye el servidor de la PC: WebSocket('/ws') y fetch('/api/…') van al núcleo (movil/core/index.js), que
// corre aquí mismo. Es un script clásico: el núcleo se carga como módulo con import().
(() => {
  if (window.__companionBoot) return;
  window.__companionBoot = true;

  // Lo que no existe en el teléfono se oculta. La interfaz puede preguntar con window.CAN.
  window.CAN = { ACTIONS: false, SCREEN: false, FLOAT: false, CLONE: false, CUSTOM_MODELS: true, CAMERA: false };
  const hide = ['#screen', '#preview-screen', '#screen-sound', '#float-btn', '#dock', '#quit', '#camera', '#preview-camera',
    'details[data-group="compartir"]', 'details[data-group="acciones"]',
    '#ob-voice-add', '#ob-voice-form', '#cam-picker', '#cloud-only-note', '#drop'];
  const css = `${hide.join(',')}{display:none!important}
    #cloud-only{pointer-events:none}
    body{-webkit-user-select:none;-webkit-touch-callout:none}
    input,textarea{-webkit-user-select:text}`;
  const style = document.createElement('style');
  style.textContent = css;
  (document.head || document.documentElement).append(style);

  // En el teléfono no hay cámara (window.CAN.CAMERA = false): la interfaz de la PC la pide al listar dispositivos,
  // al mirar sus permisos y al empezar. Aquí, para la interfaz, la cámara no existe: así iOS nunca llega a pedirla
  // (sin esto, en el iPhone la app se cerraba al tocar el micrófono o al abrir Ajustes).
  const md = navigator.mediaDevices;
  if (md) {
    const gum = md.getUserMedia && md.getUserMedia.bind(md);
    if (gum) {
      md.getUserMedia = (c = {}) => {
        if (c.video && !c.audio) return Promise.reject(new DOMException('En el teléfono no se usa la cámara', 'NotAllowedError'));
        return gum({ ...c, video: false });
      };
    }
    const enumerate = md.enumerateDevices && md.enumerateDevices.bind(md);
    if (enumerate) md.enumerateDevices = async () => (await enumerate()).filter((d) => d.kind !== 'videoinput');
  }
  if (navigator.permissions && navigator.permissions.query) {
    const query = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (d) => (d && d.name === 'camera'
      ? Promise.resolve({ name: 'camera', state: 'denied', onchange: null, addEventListener() {}, removeEventListener() {} })
      : query(d));
  }

  // La consola de la web va al registro de la app (Xcode, o «simctl launch --console»).
  const nativeLog = (level, args) => {
    try {
      const text = args.map((a) => (a instanceof Error ? `${a.message}\n${a.stack}` : typeof a === 'string' ? a : JSON.stringify(a))).join(' ');
      window.webkit.messageHandlers.native.postMessage({ cmd: 'log', args: { level, text: text.slice(0, 2000) } });
    } catch { /* sin puente */ }
  };
  for (const level of ['error', 'warn', 'info']) {
    const orig = console[level].bind(console);
    console[level] = (...args) => { orig(...args); nativeLog(level, args); };
  }
  addEventListener('error', (e) => nativeLog('error', [e.message, `${e.filename}:${e.lineno}`]));
  addEventListener('unhandledrejection', (e) => nativeLog('error', ['Promesa rechazada:', e.reason]));

  const realFetch = window.fetch.bind(window);
  // La capa de interfaz del teléfono (textos, márgenes, modo teléfono y descargas).
  const ui = import(new URL('/core/ui_movil.js', location.href).href);
  const start = () => ui.then((m) => m.init()).catch((err) => console.error('La capa del teléfono no arrancó', err));
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
  const core = import(new URL('/core/index.js', location.href).href).then((m) => m.start(realFetch));
  core.catch((err) => console.error('El núcleo no arrancó', err));

  window.fetch = async (input, init = {}) => {
    const url = new URL(typeof input === 'string' ? input : input.url, location.href);
    if (url.origin !== location.origin || !url.pathname.startsWith('/api/')) return realFetch(input, init);
    const method = (init.method || (typeof input === 'string' ? 'GET' : input.method) || 'GET').toUpperCase();
    let body = init.body;
    if (typeof body === 'string') { try { body = JSON.parse(body); } catch { /* no es JSON */ } }
    const c = await core;
    return c.api(method, url, body, realFetch);
  };

  // WebSocket('/ws') falso: lo que manda la interfaz va a la sesión del núcleo y al revés.
  const RealWS = window.WebSocket;
  class CoreSocket extends EventTarget {
    constructor(url) {
      super();
      this.url = String(url);
      this.readyState = 0;
      this.binaryType = 'arraybuffer';
      this.onopen = this.onmessage = this.onclose = this.onerror = null;
      core.then((c) => {
        if (this.readyState !== 0) return;
        this.readyState = 1;
        this._peer = c.connect((data) => this._deliver(data));
        window.__coreSocket = this;          // para las pruebas (meter audio como si fuera el micrófono)
        this._fire('open', new Event('open'));
      }, () => this.close());
    }
    _fire(kind, ev) {
      const h = this[`on${kind}`];
      if (h) h.call(this, ev);
      this.dispatchEvent(ev);
    }
    _deliver(data) {
      if (this.readyState !== 1) return;
      this._fire('message', new MessageEvent('message', { data }));
    }
    send(data) {
      if (this.readyState !== 1) throw new DOMException('No está abierto', 'InvalidStateError');
      this._peer.receive(data);
    }
    close() {
      if (this.readyState >= 2) return;
      this.readyState = 3;
      if (this._peer) this._peer.close();
      this._fire('close', new CloseEvent('close', { code: 1000 }));
    }
  }
  for (const [k, v] of Object.entries({ CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 })) {
    CoreSocket[k] = v;
    CoreSocket.prototype[k] = v;
  }
  window.WebSocket = function WebSocket(url, protocols) {
    const u = new URL(String(url), location.href.replace(/^http/, 'ws'));
    if (u.pathname === '/ws') return new CoreSocket(url);
    return new RealWS(url, protocols);
  };
  Object.assign(window.WebSocket, { CONNECTING: 0, OPEN: 1, CLOSING: 2, CLOSED: 3 });
})();
