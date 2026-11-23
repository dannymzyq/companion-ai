// Puente mínimo entre la página del companion y la app de escritorio. La página no recibe acceso a Node:
// solo estas funciones.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  float: (on) => ipcRenderer.invoke('companion:float', !!on),          // sacar a Mika de la ventana / devolverla
  // La página no se recarga al cambiar de modo: aquí se entera de que ahora está flotando ('float') o en ventana.
  onMode: (fn) => ipcRenderer.on('companion:mode', (_e, mode) => fn(mode === 'float' ? 'float' : 'window')),
  quit: () => ipcRenderer.send('companion:quit'),
  // Mascota de escritorio (desktop/pet.js): ajustes, puntos del personaje, estado de la conversación y acciones.
  pet: {
    prefs: (p) => ipcRenderer.send('pet:prefs', p),
    anchors: (a) => ipcRenderer.send('pet:anchors', a),
    state: (s) => ipcRenderer.send('pet:state', String(s)),
    work: (m) => ipcRenderer.send('pet:work', m),
    frame: () => ipcRenderer.send('pet:frame'),                     // un cuadro dibujado (mueve la ventana con él)
    rest: (on) => ipcRenderer.send('pet:rest', !!on),               // le entró sueño: a una esquina a recostarse
    on: (fn) => ipcRenderer.on('pet:event', (_e, ev) => fn(ev)),
    info: () => ipcRenderer.invoke('pet:info'),
    testScene: (s) => ipcRenderer.send('pet:test-scene', s),        // solo con COMPANION_TEST=1
    test: (c) => ipcRenderer.send('pet:test', c),
  },
  ignoreMouse: (ignore) => ipcRenderer.send('companion:ignore-mouse', !!ignore),
  drag: (phase) => ipcRenderer.send('companion:drag', String(phase)),  // 'start' | 'move' | 'end'
  resize: (step) => ipcRenderer.send('companion:resize', step > 0 ? 1 : -1),
  info: () => ipcRenderer.invoke('companion:info'),
  shareInfo: () => ipcRenderer.invoke('companion:share-info'),         // {kind, name, audio} de lo que se eligió compartir
  shareAudioNext: (on = true) => ipcRenderer.invoke('companion:share-audio-next', on !== false),   // la próxima captura es solo el sonido
  shareRetryVideo: () => ipcRenderer.invoke('companion:share-retry-video'),                        // reintenta solo vídeo sin reabrir el selector
  onShortcut: (fn) => ipcRenderer.on('companion:shortcut', (_e, action) => fn(String(action || ''))),
  desktopPrefs: {
    get: () => ipcRenderer.invoke('companion:desktop-prefs-get'),
    set: (p) => ipcRenderer.invoke('companion:desktop-prefs-set', p),
  },
});
