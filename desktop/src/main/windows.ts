import * as path from 'node:path'
import { BrowserWindow, app, session, shell, Menu } from 'electron'
import { log } from './logger'
import { iconPath, rendererFile } from './paths'
import { ProgressEvent } from './types'

/** Splash + main window management. */
export class WindowManager {
  private splash: BrowserWindow | null = null
  private main: BrowserWindow | null = null
  private quitting = false
  private lastProgress: ProgressEvent | null = null
  private currentOrigin: string | null = null
  private onSessionEnd: (() => void) | null = null

  setQuitting(): void {
    this.quitting = true
  }

  setSessionEndHandler(cb: () => void): void {
    this.onSessionEnd = cb
  }

  /** Lock down the default session: no device/notification/etc. permission prompts. */
  hardenSession(): void {
    session.defaultSession.setPermissionRequestHandler((_wc, _perm, cb) => cb(false))
    session.defaultSession.setPermissionCheckHandler(() => false)
    if (app.isPackaged) Menu.setApplicationMenu(null)
  }

  // ---------------------------------------------------------------- splash

  isSplashWebContents(id: number): boolean {
    return !!this.splash && !this.splash.isDestroyed() && this.splash.webContents.id === id
  }

  get lastSplashState(): ProgressEvent | null {
    return this.lastProgress
  }

  private ensureSplash(): BrowserWindow {
    if (this.splash && !this.splash.isDestroyed()) return this.splash
    const win = new BrowserWindow({
      width: 520,
      height: 400,
      useContentSize: true,
      frame: false,
      resizable: false,
      maximizable: false,
      fullscreenable: false,
      show: false,
      center: true,
      title: 'Dhara',
      icon: iconPath(),
      backgroundColor: '#0f1a14',
      webPreferences: {
        preload: path.join(__dirname, '..', 'preload', 'splash-preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        devTools: !app.isPackaged,
      },
    })
    win.once('ready-to-show', () => win.show())
    win.on('close', (e) => {
      if (!this.quitting) {
        e.preventDefault()
        win.hide()
      }
    })
    win.webContents.on('will-navigate', (e) => e.preventDefault())
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }))
    void win.loadFile(rendererFile('splash.html'))
    this.splash = win
    return win
  }

  showSplash(): void {
    const win = this.ensureSplash()
    if (!win.isVisible()) win.show()
    win.focus()
  }

  hideSplash(): void {
    if (this.splash && !this.splash.isDestroyed()) this.splash.hide()
  }

  sendProgress(evt: ProgressEvent): void {
    this.lastProgress = evt
    if (this.splash && !this.splash.isDestroyed() && !this.splash.webContents.isLoading()) {
      this.splash.webContents.send('splash:progress', evt)
    }
  }

  // ------------------------------------------------------------------ main

  private ensureMain(): BrowserWindow {
    if (this.main && !this.main.isDestroyed()) return this.main
    const win = new BrowserWindow({
      width: 1280,
      height: 820,
      minWidth: 960,
      minHeight: 640,
      show: false,
      title: 'Dhara',
      icon: iconPath(),
      backgroundColor: '#ffffff',
      webPreferences: {
        preload: path.join(__dirname, '..', 'preload', 'preload.js'),
        contextIsolation: true,
        nodeIntegration: false,
        sandbox: true,
        webSecurity: true,
        devTools: !app.isPackaged,
      },
    })
    win.once('ready-to-show', () => win.show())

    // Hide to tray instead of closing.
    win.on('close', (e) => {
      if (!this.quitting) {
        e.preventDefault()
        win.hide()
      }
    })
    win.on('session-end', () => this.onSessionEnd?.())

    // Keep navigation inside the local app; open everything else in the default browser.
    const isLocal = (url: string) => !!this.currentOrigin && (url === this.currentOrigin || url.startsWith(this.currentOrigin + '/'))
    win.webContents.on('will-navigate', (e, url) => {
      if (!isLocal(url)) {
        e.preventDefault()
        this.openExternalSafe(url)
      }
    })
    win.webContents.setWindowOpenHandler(({ url }) => {
      if (!isLocal(url)) this.openExternalSafe(url)
      return { action: 'deny' }
    })
    win.webContents.on('did-fail-load', (_e, code, desc, url, isMainFrame) => {
      if (isMainFrame) log.warn(`Main window failed to load ${url}: ${code} ${desc}`)
    })
    this.main = win
    return win
  }

  private openExternalSafe(url: string): void {
    try {
      const u = new URL(url)
      if (u.protocol === 'https:' || u.protocol === 'http:' || u.protocol === 'mailto:') {
        void shell.openExternal(url)
      }
    } catch {
      /* ignore bad URL */
    }
  }

  /** Show the app at `origin` (reloads if the origin/port changed) and hide the splash. */
  showMain(origin: string): void {
    const win = this.ensureMain()
    const changed = this.currentOrigin !== origin
    this.currentOrigin = origin
    if (changed || !win.webContents.getURL().startsWith(origin)) {
      void win.loadURL(origin)
    }
    if (win.isMinimized()) win.restore()
    win.show()
    win.focus()
    this.hideSplash()
  }

  hideMain(): void {
    if (this.main && !this.main.isDestroyed()) this.main.hide()
  }

  /** Forget the loaded origin (services stopped) so the next showMain reloads. */
  resetMain(): void {
    this.currentOrigin = null
    if (this.main && !this.main.isDestroyed()) {
      this.main.hide()
      void this.main.loadURL('about:blank')
    }
  }

  isMainVisible(): boolean {
    return !!this.main && !this.main.isDestroyed() && this.main.isVisible()
  }

  hasMain(): boolean {
    return !!this.main && !this.main.isDestroyed()
  }

  destroyAll(): void {
    this.quitting = true
    for (const w of [this.splash, this.main]) {
      if (w && !w.isDestroyed()) w.destroy()
    }
    this.splash = null
    this.main = null
  }
}
