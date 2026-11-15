// Puente de la ventana «¿Qué quieres que vea Mika?»: solo puede pedir la lista y devolver la elección.
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('picker', {
  sources: () => ipcRenderer.invoke('picker:sources'),
  options: () => ipcRenderer.invoke('picker:options'),          // {audio: se puede ofrecer el sonido, audioOn: elegido la última vez}
  choose: (id, audio) => ipcRenderer.send('picker:choose', String(id), audio === true),
  cancel: () => ipcRenderer.send('picker:choose', ''),
});
