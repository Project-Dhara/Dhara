'use strict'

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('dharaDesktop', {
  runSetup: (opts) => ipcRenderer.invoke('setup:run', opts || {}),
  getState: () => ipcRenderer.invoke('setup:get-state'),
  openExternal: (url) => ipcRenderer.invoke('app:open-external', url),
  onProgress: (cb) => {
    const handler = (_e, payload) => cb(payload)
    ipcRenderer.on('setup:progress', handler)
    return () => ipcRenderer.removeListener('setup:progress', handler)
  },
  onAutoResume: (cb) => {
    const handler = (_e, payload) => cb(payload)
    ipcRenderer.on('setup:auto-resume', handler)
    return () => ipcRenderer.removeListener('setup:auto-resume', handler)
  },
})
