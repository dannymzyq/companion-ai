// Puente mínimo entre la página del companion y la app de escritorio. La página no recibe acceso a Node:
// solo estas funciones. Los oyentes devuelven una función para desuscribirse sin fugas.
const { contextBridge, ipcRenderer } = require('electron');

function sub(channel, wrap) {
  const listener = (_e, ...args) => wrap(...args);
  ipcRenderer.on(channel, listener);
  return () => ipcRenderer.removeListener(channel, listener);
}

contextBridge.exposeInMainWorld('desktop', {
  float: (on) => ipcRenderer.invoke('companion:float', !!on),
  onMode: (fn) => sub('companion:mode', (mode) => fn(mode === 'float' ? 'float' : 'window')),
  quit: () => ipcRenderer.send('companion:quit'),
  pet: {
    prefs: (p) => ipcRenderer.send('pet:prefs', p),
    anchors: (a) => ipcRenderer.send('pet:anchors', a),
    state: (s) => ipcRenderer.send('pet:state', String(s)),
    work: (m) => ipcRenderer.send('pet:work', m),
    frame: () => ipcRenderer.send('pet:frame'),
    rest: (on) => ipcRenderer.send('pet:rest', !!on),
    on: (fn) => sub('pet:event', (ev) => fn(ev)),
    info: () => ipcRenderer.invoke('pet:info'),
    testScene: (s) => ipcRenderer.send('pet:test-scene', s),
    test: (c) => ipcRenderer.send('pet:test', c),
  },
  ignoreMouse: (ignore) => ipcRenderer.send('companion:ignore-mouse', !!ignore),
  drag: (phase) => ipcRenderer.send('companion:drag', String(phase)),
  resize: (step) => ipcRenderer.send('companion:resize', step > 0 ? 1 : -1),
  info: () => ipcRenderer.invoke('companion:info'),
  shareInfo: () => ipcRenderer.invoke('companion:share-info'),
  shareAudioNext: (on = true) => ipcRenderer.invoke('companion:share-audio-next', on !== false),
  shareRetryVideo: () => ipcRenderer.invoke('companion:share-retry-video'),
  onShortcut: (fn) => sub('companion:shortcut', (action) => fn(String(action || ''))),
  desktopPrefs: {
    get: () => ipcRenderer.invoke('companion:desktop-prefs-get'),
    set: (p) => ipcRenderer.invoke('companion:desktop-prefs-set', p),
  },
});
