import * as fs from 'node:fs'
import * as path from 'node:path'
import { IpcMainInvokeEvent, app, clipboard, ipcMain, shell } from 'electron'
import { clearAuth, getAuth, setAuth } from './auth-store'
import { buildDiagnostics } from './diagnostics'
import { log } from './logger'
import {
  OLLAMA_DOWNLOAD_PAGE,
  cancelPull,
  getPullStatus,
  ollamaDefaults,
  ollamaStatus,
  pullStart,
  testLocalModel,
} from './ollama'
import { dirs } from './paths'
import { ServiceSupervisor } from './supervisor'
import { WindowManager } from './windows'

const UPLOAD_EXT = new Set(['.pdf', '.xlsx', '.xls', '.csv'])
const MAX_UPLOAD_READ_BYTES = 200 * 1024 * 1024

export interface SplashActions {
  start: () => void
  quit: () => void
}

/** Only the top-level frame of a page served from our own loopback origin may call app IPC. */
function isTrustedAppSender(e: IpcMainInvokeEvent, sup: ServiceSupervisor): boolean {
  const origin = sup.origin
  if (!origin) return false
  const frame = e.senderFrame
  if (!frame || frame !== e.sender.mainFrame) return false
  const url = frame.url
  return url === origin || url.startsWith(origin + '/')
}

function assertApp(e: IpcMainInvokeEvent, sup: ServiceSupervisor): void {
  if (!isTrustedAppSender(e, sup)) throw new Error('Untrusted IPC sender')
}

export async function copyDiagnosticsToClipboard(sup: ServiceSupervisor): Promise<string> {
  const text = await buildDiagnostics(sup)
  clipboard.writeText(text)
  return text
}

export async function openLogsFolder(): Promise<void> {
  const err = await shell.openPath(dirs.logs())
  if (err) log.warn(`openPath(logs) failed: ${err}`)
}

export function registerIpc(sup: ServiceSupervisor, windows: WindowManager, splash: SplashActions): void {
  // ------------------------------------------------------------ upload bridge
  ipcMain.handle('fs:read-upload-file', async (e, filePath: unknown) => {
    assertApp(e, sup)
    const resolved = path.resolve(String(filePath || ''))
    const ext = path.extname(resolved).toLowerCase()
    if (!UPLOAD_EXT.has(ext)) {
      throw new Error(`Unsupported upload type: ${ext || '(none)'}`)
    }
    let st: fs.Stats
    try {
      st = await fs.promises.stat(resolved)
    } catch {
      throw new Error(`File not found: ${path.basename(resolved)}`)
    }
    if (!st.isFile()) throw new Error('Not a regular file')
    if (st.size <= 0) {
      throw new Error(
        `${path.basename(resolved)} is empty on disk (0 bytes). If it is a OneDrive/SharePoint cloud-only file, ` +
          'open it once in Excel to download it, or copy it to a local folder (e.g. Desktop) and upload that copy.',
      )
    }
    if (st.size > MAX_UPLOAD_READ_BYTES) {
      throw new Error(
        `${path.basename(resolved)} is too large to upload (>${MAX_UPLOAD_READ_BYTES / (1024 * 1024)} MB)`,
      )
    }
    const buf = await fs.promises.readFile(resolved)
    return {
      name: path.basename(resolved),
      // Structured clone delivers a Buffer to the renderer as a Uint8Array.
      bytes: buf,
      size: buf.length,
    }
  })

  // --------------------------------------------------------------------- auth
  ipcMain.handle('auth:get', (e) => {
    assertApp(e, sup)
    return getAuth()
  })
  ipcMain.handle('auth:set', (e, value: unknown) => {
    assertApp(e, sup)
    return setAuth(value)
  })
  ipcMain.handle('auth:clear', (e) => {
    assertApp(e, sup)
    clearAuth()
    return true
  })

  // ---------------------------------------------------------- app / support
  ipcMain.handle('app:get-info', (e) => {
    assertApp(e, sup)
    const st = sup.status()
    return {
      version: app.getVersion(),
      platform: process.platform,
      origin: st.origin,
      ports: st.ports,
      state: st.state,
      ramProfile: sup.ramProfile,
    }
  })
  ipcMain.handle('app:open-logs', async (e) => {
    assertApp(e, sup)
    await openLogsFolder()
    return true
  })
  ipcMain.handle('app:copy-diagnostics', async (e) => {
    assertApp(e, sup)
    return copyDiagnosticsToClipboard(sup)
  })

  // ------------------------------------------------- optional local LLM (opt-in)
  ipcMain.handle('ollama:status', async (e) => {
    assertApp(e, sup)
    return ollamaStatus()
  })
  ipcMain.handle('ollama:defaults', (e) => {
    assertApp(e, sup)
    return ollamaDefaults()
  })
  ipcMain.handle('ollama:open-download', async (e) => {
    assertApp(e, sup)
    await shell.openExternal(OLLAMA_DOWNLOAD_PAGE)
    return true
  })
  ipcMain.handle('ollama:pull-start', async (e) => {
    assertApp(e, sup)
    return pullStart(e.sender)
  })
  ipcMain.handle('ollama:pull-cancel', (e) => {
    assertApp(e, sup)
    return cancelPull()
  })
  ipcMain.handle('ollama:pull-status', (e) => {
    assertApp(e, sup)
    return getPullStatus()
  })
  ipcMain.handle('ollama:test-connection', async (e) => {
    assertApp(e, sup)
    return testLocalModel()
  })

  // ------------------------------------------------------------------- splash
  const assertSplash = (e: IpcMainInvokeEvent) => {
    if (!windows.isSplashWebContents(e.sender.id)) throw new Error('Untrusted IPC sender')
  }
  ipcMain.handle('splash:ready', (e) => {
    assertSplash(e)
    return windows.lastSplashState
  })
  ipcMain.handle('splash:action', async (e, action: unknown) => {
    assertSplash(e)
    switch (action) {
      case 'start':
        splash.start()
        return true
      case 'open-logs':
        await openLogsFolder()
        return true
      case 'copy-diagnostics':
        await copyDiagnosticsToClipboard(sup)
        return true
      case 'quit':
        splash.quit()
        return true
      default:
        throw new Error('Unknown action')
    }
  })
}
