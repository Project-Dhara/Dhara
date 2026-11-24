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

  // Optional local model (explicit opt-in only; Dhara never installs or starts Ollama).
  ollama: {
    status: () => ipcRenderer.invoke('ollama:status'),
    openDownloadPage: (): Promise<boolean> => ipcRenderer.invoke('ollama:open-download'),
  },
})
