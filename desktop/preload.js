// Puente mínimo entre la página del companion y la app de escritorio. La página no recibe acceso a Node:
// solo estas funciones.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('desktop', {
  float: (on) => ipcRenderer.invoke('companion:float', !!on),          // sacar a Mika de la ventana / devolverla
  ignoreMouse: (ignore) => ipcRenderer.send('companion:ignore-mouse', !!ignore),
  drag: (phase) => ipcRenderer.send('companion:drag', String(phase)),  // 'start' | 'move' | 'end'
  resize: (step) => ipcRenderer.send('companion:resize', step > 0 ? 1 : -1),
  info: () => ipcRenderer.invoke('companion:info'),
  shareInfo: () => ipcRenderer.invoke('companion:share-info'),         // {kind, name, audio} de lo que se eligió compartir
  shareAudioNext: (on = true) => ipcRenderer.invoke('companion:share-audio-next', on !== false),   // la próxima captura es solo el sonido
});
