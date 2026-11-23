'use strict'

const path = require('path')
const { app, BrowserWindow, Tray, Menu, ipcMain, nativeImage, shell } = require('electron')
const { runSetup, startStackOnly } = require('./setup')
const compose = require('./compose')
const { readState, writeState } = require('./store')
const { UI_ORIGIN, ensureDir, userDataRoot } = require('./paths')

let mainWindow = null
let tray = null
let quitting = false
let keepStackOnQuit = false

function iconPath() {
  const png = path.join(__dirname, '..', '..', 'resources', 'logo.png')
  return png
}

function createWindow({ setupMode = false } = {}) {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 760,
    minWidth: 900,
    minHeight: 600,
    show: false,
    title: 'Dhara',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
    },
  })

  mainWindow.once('ready-to-show', () => mainWindow.show())

  mainWindow.on('close', (e) => {
    if (!quitting && process.platform === 'win32') {
      e.preventDefault()
      mainWindow.hide()
    }
  })

  if (setupMode) {
    mainWindow.loadFile(path.join(__dirname, '..', 'renderer', 'setup.html'))
  } else {
    mainWindow.loadURL(UI_ORIGIN)
  }
}

function createTray() {
  const img = nativeImage.createFromPath(iconPath())
  tray = new Tray(img.isEmpty() ? nativeImage.createEmpty() : img.resize({ width: 16, height: 16 }))
  tray.setToolTip('Dhara')
  const menu = Menu.buildFromTemplate([
    {
      label: 'Open Dhara',
      click: async () => {
        if (!mainWindow) createWindow({ setupMode: false })
        else {
          mainWindow.show()
          mainWindow.focus()
        }
      },
    },
    {
      label: 'Start services',
      click: async () => {
        await startStackOnly((p) => {
          if (mainWindow) mainWindow.webContents.send('setup:progress', p)
        })
      },
    },
    {
      label: 'Stop services',
      click: async () => {
        await compose.down({ volumes: false })
      },
    },
    { type: 'separator' },
    {
      label: 'Keep services running on quit',
      type: 'checkbox',
      checked: keepStackOnQuit,
      click: (item) => {
        keepStackOnQuit = item.checked
        writeState({ keepStackOnQuit })
      },
    },
    {
      label: 'Quit',
      click: async () => {
        quitting = true
        if (!keepStackOnQuit) {
          await compose.down({ volumes: false })
        }
        app.quit()
      },
    },
  ])
  tray.setContextMenu(menu)
  tray.on('double-click', () => {
    if (mainWindow) {
      mainWindow.show()
      mainWindow.focus()
    }
  })
}

function registerIpc() {
  ipcMain.handle('setup:run', async (_evt, opts) => {
    const result = await runSetup({
      useLocalLlm: opts && opts.useLocalLlm !== false,
      resume: Boolean(opts && opts.resume),
      onProgress: (p) => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('setup:progress', p)
        }
      },
    })
    if (result.needsReboot) {
      const wsl = require('./wsl')
      // Give UI a moment to show the message, then reboot.
      setTimeout(() => wsl.requestReboot(), 4000)
    }
    if (result.ok) {
      createAppWindow()
    }
    return result
  })

  ipcMain.handle('setup:get-state', async () => readState())

  ipcMain.handle('app:open-external', async (_e, url) => {
    // Only allow known official docs hosts — no arbitrary navigation.
    const allowed = [
      'https://docs.docker.com/',
      'https://learn.microsoft.com/',
      'https://ollama.com/',
    ]
    if (allowed.some((p) => String(url).startsWith(p))) {
      await shell.openExternal(url)
      return { ok: true }
    }
    return { ok: false, error: 'URL not allowed' }
  })
}

function createAppWindow() {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.loadURL(UI_ORIGIN)
    return
  }
  createWindow({ setupMode: false })
}

async function boot() {
  ensureDir(userDataRoot())
  const state = readState()
  keepStackOnQuit = Boolean(state.keepStackOnQuit)

  const resume = process.argv.includes('--resume-setup') || Boolean(state.pendingResume)
  registerIpc()
  createTray()

  if (!state.setupComplete || resume) {
    createWindow({ setupMode: true })
    if (resume) {
      // Auto-continue after reboot.
      setTimeout(() => {
        if (mainWindow && !mainWindow.isDestroyed()) {
          mainWindow.webContents.send('setup:auto-resume', { useLocalLlm: state.useLocalLlm !== false })
        }
      }, 1500)
    }
    return
  }

  createWindow({ setupMode: true })
  // Splash: start stack then switch to UI.
  const result = await startStackOnly((p) => {
    if (mainWindow && !mainWindow.isDestroyed()) {
      mainWindow.webContents.send('setup:progress', p)
    }
  })
  if (result.ok) {
    createAppWindow()
  } else if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('setup:progress', {
      step: 'error',
      message: result.error || 'Failed to start',
      percent: 0,
      error: result.error,
    })
  }
}

app.whenReady().then(boot)

app.on('window-all-closed', () => {
  // Stay in tray on Windows.
  if (process.platform !== 'win32') app.quit()
})

app.on('before-quit', () => {
  quitting = true
})
