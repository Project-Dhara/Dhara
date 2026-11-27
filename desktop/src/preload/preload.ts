// Sandboxed preload for the main (app) window. Only `electron` may be required here.
import { contextBridge, ipcRenderer, webUtils } from 'electron'

interface AuthPayload {
  token: string
  user?: unknown
}

contextBridge.exposeInMainWorld('dharaDesktop', {
  isDesktop: true,

  /**
   * Read a user-picked File from disk. Electron's File.arrayBuffer() often returns 0 bytes for
   * local Excel/PDF picks; webUtils + main-process fs works reliably.
   */
  readUploadFile: async (file: File) => {
    const filePath = webUtils.getPathForFile(file)
    if (!filePath) {
      throw new Error('Could not resolve a local path for this file')
    }
    return ipcRenderer.invoke('fs:read-upload-file', filePath)
  },

  /**
   * Session persistence that survives a port change (localStorage is origin-scoped).
   * Encrypted in the main process with safeStorage.
   */
  getAuth: (): Promise<{ token: string; user: unknown } | null> => ipcRenderer.invoke('auth:get'),
  setAuth: (auth: AuthPayload): Promise<boolean> => ipcRenderer.invoke('auth:set', auth),
  clearAuth: (): Promise<boolean> => ipcRenderer.invoke('auth:clear'),

  // Support helpers (Settings → Help).
  getInfo: () => ipcRenderer.invoke('app:get-info'),
  openLogsFolder: (): Promise<boolean> => ipcRenderer.invoke('app:open-logs'),
  copyDiagnostics: (): Promise<string> => ipcRenderer.invoke('app:copy-diagnostics'),

  // Optional local model (explicit opt-in; may start bundled ollama serve).
  ollama: {
    status: () => ipcRenderer.invoke('ollama:status'),
    defaults: () => ipcRenderer.invoke('ollama:defaults'),
    openDownloadPage: (): Promise<boolean> => ipcRenderer.invoke('ollama:open-download'),
    pullStart: () => ipcRenderer.invoke('ollama:pull-start'),
    pullCancel: () => ipcRenderer.invoke('ollama:pull-cancel'),
    pullStatus: () => ipcRenderer.invoke('ollama:pull-status'),
    testConnection: () => ipcRenderer.invoke('ollama:test-connection'),
    onPullProgress: (cb: (payload: unknown) => void): (() => void) => {
      const listener = (_event: unknown, payload: unknown) => {
        cb(payload)
      }
      ipcRenderer.on('ollama:pull-progress', listener)
      return () => {
        ipcRenderer.removeListener('ollama:pull-progress', listener)
      }
    },
  },
})
