// Puente de la ventana «¿Qué quieres compartir?»: pide la lista, la actualiza y devuelve la elección.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('picker', {
  sources: () => ipcRenderer.invoke('picker:sources'),
  refresh: () => ipcRenderer.invoke('picker:refresh'),
  options: () => ipcRenderer.invoke('picker:options'),
  choose: (id, audio) => ipcRenderer.send('picker:choose', String(id), audio === true),
  cancel: () => ipcRenderer.send('picker:choose', ''),
});
