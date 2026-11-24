// Sandboxed preload for the splash window. Only `electron` may be required here.
import { contextBridge, ipcRenderer } from 'electron'

type Action = 'start' | 'open-logs' | 'copy-diagnostics' | 'quit'

contextBridge.exposeInMainWorld('dharaSplash', {
  /** Last progress event (so a late-loading splash can catch up). */
  ready: () => ipcRenderer.invoke('splash:ready'),
  onProgress: (cb: (evt: unknown) => void) => {
    const handler = (_e: unknown, payload: unknown) => cb(payload)
    ipcRenderer.on('splash:progress', handler)
    return () => ipcRenderer.removeListener('splash:progress', handler)
  },
  action: (a: Action) => ipcRenderer.invoke('splash:action', a),
})
