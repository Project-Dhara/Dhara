import { app } from 'electron'
import { copyDiagnosticsToClipboard, openLogsFolder, registerIpc } from './ipc'
import { log } from './logger'
import { abortPullFireAndForget } from './ollama'
import { dirs, ensureDir, userDataRoot } from './paths'
import { readRuntime, writeRuntime } from './runtime-state'
import { ServiceSupervisor } from './supervisor'
import { DharaTray } from './tray'
import { ProgressEvent } from './types'
import { WindowManager } from './windows'

// Everything mutable lives under %LOCALAPPDATA%\Dhara — including Chromium's profile, so the
// safeStorage key that protects auth.bin stays stable across launches.
ensureDir(userDataRoot())
app.setPath('userData', dirs.electron())
app.setAppUserModelId('org.ekstep.datadhara.desktop')

const supervisor = new ServiceSupervisor()
const windows = new WindowManager()
let tray: DharaTray | null = null
let quitInProgress = false

process.on('uncaughtException', (err) => log.error('uncaughtException', err))
process.on('unhandledRejection', (err) => log.error('unhandledRejection', err))

// ---------------------------------------------------------------- lifecycle

async function startServices(): Promise<void> {
  windows.hideMain()
  windows.showSplash()
  const res = await supervisor.start()
  if (res.ok && supervisor.origin) {
    windows.showMain(supervisor.origin)
  } else {
    windows.showSplash()
  }
}

async function stopServices(): Promise<void> {
  await supervisor.stop()
  windows.resetMain()
  windows.showSplash()
}

function openDhara(): void {
  if (supervisor.state === 'running' && supervisor.origin) {
    windows.showMain(supervisor.origin)
  } else {
    windows.showSplash()
  }
}

async function quitApp(): Promise<void> {
  if (quitInProgress) return
  quitInProgress = true
  windows.setQuitting()
  // Do not await the Ollama pull stream — abort and continue shutting down.
  abortPullFireAndForget()
  try {
    const keep = Boolean(readRuntime().keepRunningOnQuit)
    if (keep && supervisor.state === 'running') {
      // Children outlive Electron; the next launch adopts them.
      await supervisor.detachForQuit()
    } else {
      await supervisor.stop()
    }
  } catch (err) {
    log.error('error while quitting', err)
  } finally {
    supervisor.closeJob()
    tray?.destroy()
    windows.destroyAll()
    log.info('Dhara exiting')
    log.close()
    app.exit(0)
  }
}

// ----------------------------------------------------------------- boot

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
} else {
  // A second launch focuses the running app; `Dhara.exe --quit` asks it to quit (honouring
  // “Keep services running on quit”).
  app.on('second-instance', (_e, argv) => {
    if (argv.includes('--quit')) void quitApp()
    else openDhara()
  })

  // Hide-to-tray: closing the last window must not quit.
  app.on('window-all-closed', () => {
    /* stay in tray */
  })

  // Route every quit path (Alt+F4 on a hidden window, installer, OS) through the orderly shutdown.
  app.on('before-quit', (e) => {
    if (!quitInProgress) {
      e.preventDefault()
      void quitApp()
    }
  })

  void app.whenReady().then(async () => {
    log.info(`Dhara ${app.getVersion()} starting (packaged=${app.isPackaged})`)
    windows.hardenSession()
    windows.setSessionEndHandler(() => void quitApp())

    supervisor.on('progress', (evt: ProgressEvent) => windows.sendProgress(evt))
    supervisor.on('state', (s) => tray?.update(s))
    supervisor.on('service-failed', (which: string) => {
      log.error(`service failed: ${which}`)
      tray?.balloon('Dhara', 'A Dhara service stopped unexpectedly. Open the tray menu for options.')
      if (which === 'api' || which === 'postgres') {
        windows.hideMain()
        windows.sendProgress({
          step: 'error',
          message: supervisor.status().lastError ?? 'A Dhara service stopped unexpectedly.',
          percent: 0,
          error: supervisor.status().lastError ?? 'A Dhara service stopped unexpectedly.',
        })
        windows.showSplash()
      }
    })

    registerIpc(supervisor, windows, {
      start: () => void startServices(),
      quit: () => void quitApp(),
    })

    tray = new DharaTray({
      open: openDhara,
      startServices: () => void startServices(),
      stopServices: () => void stopServices(),
      setKeepRunning: (keep) => {
        writeRuntime({ keepRunningOnQuit: keep })
      },
      openLogs: () => void openLogsFolder(),
      copyDiagnostics: () => void copyDiagnosticsToClipboard(supervisor),
      quit: () => void quitApp(),
    })
    tray.create(Boolean(readRuntime().keepRunningOnQuit))

    windows.showSplash()
    await startServices()
  })
}
