import path from 'node:path'
import { BrowserWindow, app } from 'electron'

export function createSplashWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 480,
    height: 320,
    resizable: false,
    maximizable: false,
    fullscreenable: false,
    title: 'Dhara',
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  win.once('ready-to-show', () => win.show())
  win.loadFile(path.join(app.getAppPath(), 'splash.html'))
  return win
}

export function createMainWindow(uiUrl: string): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 840,
    minWidth: 960,
    minHeight: 640,
    title: 'Dhara',
    show: false,
    autoHideMenuBar: true,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  })

  win.once('ready-to-show', () => win.show())
  win.loadURL(uiUrl)
  return win
}

export async function setSplashStatus(win: BrowserWindow | null, text: string): Promise<void> {
  if (!win || win.isDestroyed()) return
  try {
    await win.webContents.executeJavaScript(
      `window.dharaDesktop && window.dharaDesktop.setStatus(${JSON.stringify(text)})`,
    )
  } catch {
    /* splash may not be ready yet */
  }
}

export async function setSplashError(win: BrowserWindow | null, text: string): Promise<void> {
  if (!win || win.isDestroyed()) return
  try {
    await win.webContents.executeJavaScript(
      `window.dharaDesktop && window.dharaDesktop.setError(${JSON.stringify(text)})`,
    )
  } catch {
    /* ignore */
  }
}
