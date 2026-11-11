import type { RuntimeConfig } from '../main/config'
import type { DharaPaths } from '../main/paths'
import { startBackend, runMigrations } from './backend'
import { startFrontend } from './frontend'
import { allocatePort } from './health'
import { FileLogger } from './logger'
import { startPostgres, stopPostgres } from './postgres'
import type { ManagedProcess } from './process'
import { startWorker } from './worker'

export type SupervisorStatus = {
  phase: string
  uiUrl?: string
  backendPort?: number
  pgPort?: number
  error?: string
}

export type StatusListener = (status: SupervisorStatus) => void

export class ServiceSupervisor {
  private postgres: ManagedProcess | null = null
  private backend: ManagedProcess | null = null
  private worker: ManagedProcess | null = null
  private frontend: ManagedProcess | null = null
  private logger: FileLogger
  private started = false

  readonly ports = {
    pg: 0,
    backend: 0,
    ui: 0,
  }

  constructor(
    private paths: DharaPaths,
    private cfg: RuntimeConfig,
    private onStatus: StatusListener = () => undefined,
  ) {
    this.logger = new FileLogger(paths.logs, 'desktop')
  }

  async start(): Promise<{ uiUrl: string }> {
    if (this.started) {
      return { uiUrl: `http://127.0.0.1:${this.ports.ui}` }
    }

    try {
      this.emit('Allocating ports')
      this.ports.pg = await allocatePort(this.cfg.preferredPgPort)
      this.ports.backend = await allocatePort(this.cfg.preferredBackendPort)
      this.ports.ui = await allocatePort(this.cfg.preferredUiPort)

      this.emit('Starting PostgreSQL')
      this.postgres = await startPostgres(this.paths, this.cfg, this.ports.pg, this.logger)

      this.emit('Applying database migrations')
      await runMigrations(this.paths, this.cfg, this.ports.pg, this.ports.backend, this.logger)

      this.emit('Starting API')
      this.backend = await startBackend(
        this.paths,
        this.cfg,
        this.ports.pg,
        this.ports.backend,
        this.logger,
      )

      this.emit('Starting job worker')
      this.worker = await startWorker(
        this.paths,
        this.cfg,
        this.ports.pg,
        this.ports.backend,
        this.logger,
      )

      this.emit('Starting UI')
      this.frontend = await startFrontend(
        this.paths,
        this.ports.backend,
        this.ports.ui,
        this.logger,
      )

      this.started = true
      const uiUrl = `http://127.0.0.1:${this.ports.ui}`
      this.onStatus({
        phase: 'Ready',
        uiUrl,
        backendPort: this.ports.backend,
        pgPort: this.ports.pg,
      })
      this.logger.info(`Dhara desktop ready at ${uiUrl}`)
      return { uiUrl }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      this.logger.error(message)
      this.onStatus({ phase: 'Failed', error: message })
      await this.stop()
      throw err
    }
  }

  async stop(): Promise<void> {
    this.logger.info('Stopping services')
    if (this.frontend) {
      await this.frontend.stop()
      this.frontend = null
    }
    if (this.worker) {
      await this.worker.stop()
      this.worker = null
    }
    if (this.backend) {
      await this.backend.stop()
      this.backend = null
    }
    await stopPostgres(this.postgres, this.paths, this.logger)
    this.postgres = null
    this.started = false
    this.logger.close()
  }

  private emit(phase: string): void {
    this.logger.info(phase)
    this.onStatus({
      phase,
      backendPort: this.ports.backend || undefined,
      pgPort: this.ports.pg || undefined,
    })
  }
}
