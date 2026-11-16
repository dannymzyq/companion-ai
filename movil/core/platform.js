// Puente con la app nativa. El núcleo solo habla con el teléfono por aquí, así que en Android basta con dar
// el mismo objeto (window.companionNative) con otra implementación.
//
//   call(cmd, args)            → Promise con la respuesta del nativo
//   stream(cmd, args, onEvent) → Promise que se resuelve al acabar; el nativo va mandando eventos
//                                window.__native.event(id, kind, data) con kind = head | line | chunk | end | error
//
// Las claves (Gemini, Groq) viven en el llavero del teléfono: el núcleo nunca las lee. Para una petición con
// clave se pasa `auth: "<nombre del secreto>"` y el nativo pone la cabecera Authorization él mismo.

const streams = new Map();
let seq = 0;

function post(msg) {
  const ios = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.native;
  if (ios) return ios.postMessage(msg);                       // WKScriptMessageHandlerWithReply: devuelve Promise
  if (window.companionNative) return window.companionNative.post(msg);   // Android (u otra plataforma)
  return Promise.reject(new Error('Sin app nativa'));
}

window.__native = {
  event(id, kind, data) {
    const s = streams.get(id);
    if (!s) return;
    if (kind === 'end') { streams.delete(id); s.resolve(); return; }
    if (kind === 'error') { streams.delete(id); s.reject(new Error(data || 'Error del teléfono')); return; }
    try { s.onEvent(kind, data); } catch (err) { console.error(err); }
  },
  // El nativo empuja cosas sin que se las pidan (audio del micrófono, avisos): se reparten aquí.
  listeners: new Map(),
  emit(kind, data) { for (const fn of this.listeners.get(kind) || []) fn(data); },
};

export const available = () => !!((window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.native)
  || window.companionNative);

export async function call(cmd, args = {}) {
  const reply = await post({ cmd, args });
  if (reply && reply.error) throw new Error(reply.error);
  return reply ? reply.value : undefined;
}

export function stream(cmd, args, onEvent) {
  const id = ++seq;
  const p = new Promise((resolve, reject) => {
    streams.set(id, { onEvent, resolve, reject });
    call(cmd, { ...args, stream: id }).catch((err) => { streams.delete(id); reject(err); });
  });
  p.id = id;                   // para cortarlo con cancel(id)
  return p;
}

export function cancel(id) { return call('stream.cancel', { id }).catch(() => {}); }

export function on(kind, fn) {
  const l = window.__native.listeners;
  if (!l.has(kind)) l.set(kind, []);
  l.get(kind).push(fn);
}

// Guardado clave → texto (JSON) en la carpeta de la app. IndexedDB no es fiable con el esquema app:// de iOS.
export const kv = {
  async get(key, fallback = null) {
    try {
      const v = await call('kv.get', { key });
      return v == null ? fallback : JSON.parse(v);
    } catch { return fallback; }
  },
  set: (key, value) => call('kv.set', { key, value: JSON.stringify(value) }),
};

export const secrets = {
  has: (name) => call('secret.has', { name }),
  set: (name, value) => call('secret.set', { name, value }),
  remove: (name) => call('secret.remove', { name }),
};

// Petición HTTP hecha por el teléfono (sin CORS). `auth`: nombre del secreto para «Authorization: Bearer …»;
// `bearer`: una clave recién escrita que aún no está guardada (solo para comprobarla).
export async function request({ url, method = 'GET', headers = {}, body = null, auth = null, bearer = null, timeout = 30, multipart = null }) {
  return call('http.request', { url, method, headers, body, auth, bearer, timeout, multipart });   // {status, body}
}

// Respuesta por líneas (eventos SSE). Devuelve un iterador asíncrono de {status} y después de cada línea.
export function lines({ url, method = 'POST', headers = {}, body = null, auth = null, timeout = 60 }) {
  const queue = [];
  let wake = null, done = false, failure = null, streamId = null;
  const push = (item) => { queue.push(item); if (wake) { wake(); wake = null; } };
  const p = stream('http.stream', { url, method, headers, body, auth, timeout }, (kind, data) => {
    if (kind === 'head') { streamId = data.id; push({ status: data.status }); }
    else if (kind === 'line') push({ line: data });
  });
  p.then(() => { done = true; push(null); }, (err) => { failure = err; done = true; push(null); });
  return {
    async *[Symbol.asyncIterator]() {
      try {
        while (true) {
          if (!queue.length) await new Promise((r) => (wake = r));
          const item = queue.shift();
          if (item === null) { if (failure) throw failure; return; }
          yield item;
        }
      } finally {
        if (!done && streamId != null) cancel(streamId);
      }
    },
  };
}
