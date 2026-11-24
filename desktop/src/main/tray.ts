import { Menu, Tray, nativeImage } from 'electron'
import { iconPath } from './paths'
import { ServiceState } from './types'

export interface TrayActions {
  open: () => void
  startServices: () => void
  stopServices: () => void
  setKeepRunning: (keep: boolean) => void
  openLogs: () => void
  copyDiagnostics: () => void
  quit: () => void
}

const STATE_LABEL: Record<ServiceState, string> = {
  stopped: 'Services: stopped',
  starting: 'Services: starting…',
  running: 'Services: running',
  stopping: 'Services: stopping…',
  error: 'Services: needs attention',
}

export class DharaTray {
  private tray: Tray | null = null
  private state: ServiceState = 'stopped'
  private keepRunning = false

  constructor(private readonly actions: TrayActions) {}

  create(initialKeepRunning: boolean): void {
    this.keepRunning = initialKeepRunning
    const img = nativeImage.createFromPath(iconPath())
    this.tray = new Tray(img.isEmpty() ? nativeImage.createEmpty() : img.resize({ width: 16, height: 16 }))
    this.tray.setToolTip('Dhara')
    this.tray.on('click', () => this.actions.open())
    this.tray.on('double-click', () => this.actions.open())
    this.refresh()
  }

  update(state: ServiceState): void {
    this.state = state
    this.refresh()
  }

  setKeepRunning(keep: boolean): void {
    this.keepRunning = keep
    this.refresh()
  }

  balloon(title: string, content: string): void {
    this.tray?.displayBalloon({ title, content, iconType: 'warning' })
  }

  private refresh(): void {
    if (!this.tray) return
    const s = this.state
    const menu = Menu.buildFromTemplate([
      { label: 'Open Dhara', click: () => this.actions.open() },
      { type: 'separator' },
      { label: STATE_LABEL[s], enabled: false },
      {
        label: 'Start services',
        enabled: s === 'stopped' || s === 'error',
        click: () => this.actions.startServices(),
      },
      {
        label: 'Stop services',
        enabled: s === 'running' || s === 'error',
        click: () => this.actions.stopServices(),
      },
      { type: 'separator' },
      {
        label: 'Keep services running on quit',
        type: 'checkbox',
        checked: this.keepRunning,
        click: (item) => {
          this.keepRunning = item.checked
          this.actions.setKeepRunning(item.checked)
        },
      },
      { type: 'separator' },
      { label: 'Open logs folder', click: () => this.actions.openLogs() },
      { label: 'Copy diagnostics', click: () => this.actions.copyDiagnostics() },
      { type: 'separator' },
      { label: 'Quit Dhara', click: () => this.actions.quit() },
    ])
    this.tray.setContextMenu(menu)
    this.tray.setToolTip(`Dhara — ${STATE_LABEL[s].replace('Services: ', '')}`)
  }

  destroy(): void {
    this.tray?.destroy()
    this.tray = null
  }
}
