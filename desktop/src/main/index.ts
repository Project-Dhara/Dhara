import { app, BrowserWindow, dialog } from 'electron'
import { loadOrCreateRuntimeConfig } from './config'
import { resolveDharaPaths } from './paths'
import { createMainWindow, createSplashWindow, setSplashError, setSplashStatus } from './window'
import { ServiceSupervisor } from '../services/supervisor'

let mainWindow: BrowserWindow | null = null
let splashWindow: BrowserWindow | null = null
let supervisor: ServiceSupervisor | null = null
let stopping = false

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const target = mainWindow || splashWindow
    if (target) {
      if (target.isMinimized()) target.restore()
      target.focus()
    }
  })

  app.whenReady().then(async () => {
    splashWindow = createSplashWindow()
    const paths = resolveDharaPaths()
    const cfg = loadOrCreateRuntimeConfig(paths)

    supervisor = new ServiceSupervisor(paths, cfg, (status) => {
      void setSplashStatus(splashWindow, status.phase)
    })

    try {
      const { uiUrl } = await supervisor.start()
      mainWindow = createMainWindow(uiUrl)
      if (splashWindow && !splashWindow.isDestroyed()) {
        splashWindow.close()
        splashWindow = null
      }
      mainWindow.on('closed', () => {
        mainWindow = null
        void shutdown()
      })
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      await setSplashError(splashWindow, message)
      dialog.showErrorBox('Dhara failed to start', message)
    }
  })

  app.on('window-all-closed', () => {
    void shutdown().finally(() => app.quit())
  })

  app.on('before-quit', (event) => {
    if (stopping) return
    event.preventDefault()
    void shutdown().finally(() => app.exit(0))
  })
}

async function shutdown(): Promise<void> {
  if (stopping) return
  stopping = true
  try {
    await supervisor?.stop()
  } catch (err) {
    console.error('Shutdown error', err)
  } finally {
    supervisor = null
  }
}
