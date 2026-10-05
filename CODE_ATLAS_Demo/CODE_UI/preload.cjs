const { contextBridge, ipcRenderer } = require("electron");
contextBridge.exposeInMainWorld("atlas", {
  status: () => ipcRenderer.invoke("engine:status"),
  action: (payload) => ipcRenderer.invoke("engine:action", payload),
  demo: () => ipcRenderer.invoke("engine:demo"),
  save: (config) => ipcRenderer.invoke("engine:save", config),
  pick: () => ipcRenderer.invoke("engine:pick"),
  service: (start) => ipcRenderer.invoke("engine:service", start),
  open: (id) => ipcRenderer.invoke("engine:open", id),
  onEvent: (callback) => {
    const listener = (_, event) => callback(event);
    ipcRenderer.on("engine:event", listener);
    return () => ipcRenderer.removeListener("engine:event", listener);
  },
});
