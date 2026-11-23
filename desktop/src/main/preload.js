'use strict'

const { contextBridge, ipcRenderer, webUtils } = require('electron')

contextBridge.exposeInMainWorld('dharaDesktop', {
  runSetup: (opts) => ipcRenderer.invoke('setup:run', opts || {}),
  getState: () => ipcRenderer.invoke('setup:get-state'),
  openExternal: (url) => ipcRenderer.invoke('app:open-external', url),
  /**
   * Read a user-picked File from disk. Electron's File.arrayBuffer() often
   * returns 0 bytes for local Excel/PDF picks; webUtils + main-process fs works.
   */
  readUploadFile: async (file) => {
    const filePath = webUtils.getPathForFile(file)
    if (!filePath) {
      throw new Error('Could not resolve a local path for this file')
    }
    return ipcRenderer.invoke('fs:read-upload-file', filePath)
  },
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
