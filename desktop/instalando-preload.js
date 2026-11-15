// Puente de la ventana de instalación del Mac (instalando.html): solo recibe el progreso y pide reintentar o
// enseñar el registro.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('instalar', {
  on: (fn) => ipcRenderer.on('instalar:evento', (_e, kind, ...args) => fn(String(kind), ...args)),
  retry: () => ipcRenderer.send('instalar:reintentar'),
  showLog: () => ipcRenderer.send('instalar:registro'),
});
