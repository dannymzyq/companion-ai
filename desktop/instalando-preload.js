// Puente de la ventana de instalación del Mac (instalando.html): recibe el progreso y devuelve función de limpieza.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('instalar', {
  on: (fn) => {
    const listener = (_e, kind, ...args) => fn(String(kind), ...args);
    ipcRenderer.on('instalar:evento', listener);
    return () => ipcRenderer.removeListener('instalar:evento', listener);
  },
  retry: () => ipcRenderer.send('instalar:reintentar'),
  showLog: () => ipcRenderer.send('instalar:registro'),
});
