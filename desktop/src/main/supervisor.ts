import { EventEmitter } from 'node:events'
import * as fs from 'node:fs'
import { app } from 'electron'
import { runPreMigrateBackup } from './backup'
import { buildBackendEnv } from './backend-env'
import { JobObject } from './job-object'
import { log } from './logger'
import { ManagedProcess, runToCompletion, trimLiveLog } from './managed-process'
import { dirs, files, requiredRuntimePaths, runtime } from './paths'
import { allocatePorts, LOOPBACK } from './ports'
import { ExistingPostgres, PostgresService } from './postgres'
import { ensureSecrets, readRuntime, RunningRecord, Secrets, writeRuntime } from './runtime-state'
import { getProcessInfo, isElevated, isPidAlive, isUnder, killTree, ramInfo, waitForPidExit } from './sysinfo'
import {
  DharaError,
  MSG,
  Ports,
  ProgressEvent,
  RamProfile,
  ServiceState,
  ServiceStatus,
  StepId,
} from './types'

const API_READY_TIMEOUT_MS = 240_000
const HEALTH_INTERVAL_MS = 20_000
const LOG_TRIM_INTERVAL_MS = 5 * 60_000
const MAX_RESTARTS = 5
const RESTART_WINDOW_MS = 10 * 60_000

export interface StartResult {
  ok: boolean
  error?: string
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

async function httpOk(url: string, timeoutMs = 4000): Promise<{ ok: boolean; status: number; body: string }> {
  try {
    const res = await fetch(url, { signal: AbortSignal.timeout(timeoutMs) })
    const body = await res.text().catch(() => '')
    return { ok: res.ok, status: res.status, body }
  } catch {
    return { ok: false, status: 0, body: '' }
  }
}

/**
 * Owns the whole native runtime:
 *   Postgres → (backup) → Alembic → API (uvicorn, static UI) → job worker
 * and keeps children inside a Windows Job Object so they die with Electron.
 */
export class ServiceSupervisor extends EventEmitter {
  readonly job = new JobObject()
  private readonly pg = new PostgresService(this.job)

  private api: ManagedProcess | null = null
  private worker: ManagedProcess | null = null
  private adoptedApiPid: number | null = null
  private adoptedWorkerPid: number | null = null

  private _state: ServiceState = 'stopped'
  private _ports: Ports | null = null
  private secrets: Secrets | null = null
  private profile: RamProfile = 'standard'
  private lastError: string | null = null
  private warnings: string[] = []
  private pgvectorOk = false
  private lastProgressKey = ''

  private starting: Promise<StartResult> | null = null
  private stopping: Promise<void> | null = null
  private healthTimer: NodeJS.Timeout | null = null
  private trimTimer: NodeJS.Timeout | null = null
  private restartTimer: NodeJS.Timeout | null = null
  private workerRestarts: number[] = []
  private apiRestarts: number[] = []
  private healthFailures = 0

  // ---------------------------------------------------------------- state

  get state(): ServiceState {
    return this._state
  }

  get ports(): Ports | null {
    return this._ports
  }

  /** `http://127.0.0.1:<apiPort>` once ports are known. */
  get origin(): string | null {
    return this._ports ? `http://${LOOPBACK}:${this._ports.api}` : null
  }

  get ramProfile(): RamProfile {
    return this.profile
  }

  get softWarnings(): string[] {
    return [...this.warnings]
  }

  status(): ServiceStatus {
    return {
      state: this._state,
      ports: this._ports,
      origin: this.origin,
      pids: {
        postgres: this.pg.pid,
        api: this.api?.pid ?? this.adoptedApiPid ?? undefined,
        worker: this.worker?.pid ?? this.adoptedWorkerPid ?? undefined,
      },
      workerRestarts: this.workerRestarts.length,
      lastError: this.lastError,
    }
  }

  private setState(s: ServiceState): void {
    if (this._state === s) return
    this._state = s
    log.info(`state -> ${s}`)
    this.emit('state', s)
  }

  private progress(step: StepId, message: string, percent: number, extra: Partial<ProgressEvent> = {}): void {
    const evt: ProgressEvent = {
      step,
      message,
      percent,
      warning: this.warnings.length ? this.warnings.join(' ') : undefined,
      ...extra,
    }
    const key = `${step}:${message}`
    if (key !== this.lastProgressKey) {
      this.lastProgressKey = key
      log.info(`[${step}] ${message}`)
    }
    this.emit('progress', evt)
  }

  // ---------------------------------------------------------------- start

  start(): Promise<StartResult> {
    if (this.starting) return this.starting
    if (this._state === 'running') return Promise.resolve({ ok: true })
    this.starting = this.runStart()
      .catch((err: unknown) => this.failStart(err))
      .finally(() => {
        this.starting = null
      })
    return this.starting
  }

  private async failStart(err: unknown): Promise<StartResult> {
    const userMessage =
      err instanceof DharaError ? err.userMessage : 'Dhara could not start. Use “Open logs folder” and contact support.'
    log.error(`Startup failed: ${err instanceof Error ? err.message : String(err)}`)
    this.lastError = userMessage
    // Do not leave half-started children (and pgdata locks) behind.
    await this.teardown({ keepRecord: false }).catch((e) => log.warn(`teardown after failure: ${String(e)}`))
    this.setState('error')
    this.progress('error', userMessage, 0, { error: userMessage })
    return { ok: false, error: userMessage }
  }

  private async runStart(): Promise<StartResult> {
    if (this._state === 'error') await this.teardown({ keepRecord: false })
    this.lastError = null
    this.warnings = []
    this.setState('starting')

    // ---- preflight --------------------------------------------------------
    this.progress('preflight', 'Checking your PC…', 3)
    const missing = requiredRuntimePaths().filter((p) => !fs.existsSync(p))
    if (missing.length) {
      throw new DharaError('RUNTIME_MISSING', MSG.runtimeMissing, `missing: ${missing.join('; ')}`)
    }
    if (await isElevated()) {
      throw new DharaError('ELEVATED', MSG.elevated)
    }
    const ram = ramInfo()
    this.profile = ram.profile
    if (ram.below8GB) {
      const w = `This PC has ${ram.totalGiB.toFixed(1)} GB of memory. Dhara recommends at least 8 GB; large files may be slow.`
      this.warnings.push(w)
      log.warn(w)
    }
    log.info(
      `RAM total=${ram.totalGiB.toFixed(1)}GiB available=${ram.availableMiB}MiB profile=${this.profile}`,
    )
    void this.job.start() // compile the helper in parallel with the next steps

    // ---- detect leftovers (stale pid / services kept running) -------------
    this.progress('adopt', 'Looking for an earlier session…', 8)
    let existingPg: ExistingPostgres = await this.pg.resolveExisting()
    const record = readRuntime().running ?? null
    let adoptApi = false
    if (record) {
      adoptApi = await this.canAdopt(record, existingPg)
      if (!adoptApi) {
        await this.stopOrphans(record)
        if (existingPg.mode === 'adopt' && record.appVersion !== app.getVersion()) {
          // Different build: do not reuse its database process.
          await this.stopAdoptedPostgres(existingPg.pid)
          existingPg = await this.pg.resolveExisting()
        }
      }
    }

    // ---- ports -------------------------------------------------------------
    this.progress('ports', 'Reserving local ports…', 12)
    this._ports = await allocatePorts({
      postgres: existingPg.mode === 'adopt' ? existingPg.port : undefined,
      api: adoptApi && record ? record.apiPort : undefined,
    })
    writeRuntime({ lastPorts: this._ports })
    log.info(`ports: postgres=${this._ports.postgres} api=${this._ports.api}`)

    // ---- secrets -----------------------------------------------------------
    this.progress('secrets', 'Preparing local settings…', 16)
    const clusterExists = this.pg.clusterExists()
    if (clusterExists && !readRuntime().dbPassword) {
      throw new DharaError('SECRETS_MISSING', MSG.secretsMissing)
    }
    const { secrets } = ensureSecrets({ allowNewDbPassword: !clusterExists })
    this.secrets = secrets
    const freshCluster = !clusterExists

    // ---- postgres ----------------------------------------------------------
    if (freshCluster) {
      this.progress('postgres-init', 'Creating your local database (first run)…', 22)
      await this.pg.initCluster(secrets.dbPassword, this.profile)
    }
    // Make sure the Job Object exists before Postgres spawns its own children.
    await this.job.start()
    this.progress('postgres-start', 'Starting database…', 32)
    await this.pg.start(this._ports.postgres, secrets.dbPassword, this.profile, existingPg)
    this.pg.onExit((code) => this.onPostgresExit(code))
    await this.pg.ensureDatabase()
    this.pgvectorOk = await this.pg.ensureExtensions()
    writeRuntime({ pgvectorAvailable: this.pgvectorOk, ramProfileApplied: this.profile })

    // ---- migrate (with backup gate) ---------------------------------------
    if (!adoptApi) {
      await this.migrateWithBackup()
    }

    // ---- API ---------------------------------------------------------------
    if (adoptApi && record?.apiPid) {
      this.progress('api', 'Reconnecting to Dhara…', 80)
      this.adoptedApiPid = record.apiPid
      await this.job.assign(record.apiPid, 'api (adopted)')
    } else {
      this.progress('api', 'Starting Dhara…', 70)
      await this.spawnApi()
      await this.waitForApiReady()
    }

    // ---- worker ------------------------------------------------------------
    this.progress('worker', 'Starting background worker…', 92)
    if (adoptApi && record?.workerPid && isPidAlive(record.workerPid)) {
      this.adoptedWorkerPid = record.workerPid
      await this.job.assign(record.workerPid, 'worker (adopted)')
    } else {
      await this.spawnWorker()
    }

    this.persistRunning()
    this.startTimers()
    this.setState('running')
    this.progress('ready', 'Dhara is ready', 100)
    return { ok: true }
  }

  private async canAdopt(record: RunningRecord, pg: ExistingPostgres): Promise<boolean> {
    if (record.appVersion !== app.getVersion()) return false
    if (pg.mode !== 'adopt' || pg.port !== record.pgPort) return false
    if (!record.apiPid || !isPidAlive(record.apiPid)) return false
    const info = await getProcessInfo(record.apiPid)
    if (!info || !isUnder(info.exePath, runtime.pythonDir())) return false
    const live = await httpOk(`http://${LOOPBACK}:${record.apiPort}/api/live`)
    if (!live.ok) return false
    log.info(`Adopting running services from an earlier session (api pid ${record.apiPid})`)
    return true
  }

  /** Kill leftover API/worker processes from an earlier session — only if they are verifiably Dhara's. */
  private async stopOrphans(record: RunningRecord): Promise<void> {
    for (const [label, pid] of [
      ['api', record.apiPid],
      ['worker', record.workerPid],
    ] as const) {
      if (!pid || !isPidAlive(pid)) continue
      const info = await getProcessInfo(pid)
      if (info && isUnder(info.exePath, runtime.pythonDir())) {
        log.warn(`Stopping leftover ${label} from an earlier session (pid ${pid})`)
        await killTree(pid)
        await waitForPidExit(pid, 8000)
      }
    }
    writeRuntime({ running: null })
  }

  private async stopAdoptedPostgres(pid: number): Promise<void> {
    log.warn(`Stopping Postgres from an earlier build (pid ${pid})`)
    await runToCompletion(
      runtime.pgBin('pg_ctl.exe'),
      ['stop', '-D', dirs.pgdata(), '-m', 'fast', '-w', '-t', '30'],
      { timeoutMs: 45000 },
    )
    if (!(await waitForPidExit(pid, 10000))) await killTree(pid)
  }

  // ------------------------------------------------------------- migrate

  private async alembic(args: string[], role: 'migrate' = 'migrate'): Promise<{ code: number | null; output: string }> {
    if (!this.secrets || !this._ports) throw new Error('supervisor not initialised')
    const env = buildBackendEnv(role, this._ports, this.secrets, this.profile)
    return runToCompletion(runtime.pythonExe(), ['-m', 'alembic', ...args], {
      cwd: runtime.backendDir(),
      env,
      logFile: files.apiLog(),
      timeoutMs: 30 * 60 * 1000,
    })
  }

  private async shippedHeads(): Promise<string | null> {
    const r = await this.alembic(['heads'])
    if (r.code !== 0) return null
    const revs = [...r.output.matchAll(/^([A-Za-z0-9_]+)\s+\(head\)/gm)].map((m) => m[1] as string)
    return revs.length ? revs.sort().join(',') : null
  }

  private async databaseRevision(): Promise<{ revision: string | null; hasUserTables: boolean }> {
    const tbl = await this.pg.query(
      `SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name <> 'alembic_version'`,
    )
    const hasUserTables = tbl.ok && parseInt(tbl.out, 10) > 0
    const reg = await this.pg.query(`SELECT to_regclass('public.alembic_version') IS NOT NULL`)
    let revision: string | null = null
    if (reg.ok && reg.out.trim() === 't') {
      const rev = await this.pg.query('SELECT version_num FROM alembic_version')
      if (rev.ok && rev.out) {
        revision = rev.out
          .split(/\r?\n/)
          .map((s) => s.trim())
          .filter(Boolean)
          .sort()
          .join(',')
      }
    }
    return { revision, hasUserTables }
  }

  private async migrateWithBackup(): Promise<void> {
    if (!this.secrets || !this._ports) throw new Error('supervisor not initialised')
    const appVersion = app.getVersion()
    const secrets = this.secrets
    const ports = this._ports

    this.progress('migrate', 'Checking your data version…', 45)
    const head = await this.shippedHeads()
    const db = await this.databaseRevision()
    log.info(`schema: db=${db.revision ?? '(none)'} shipped=${head ?? '(unknown)'} existingData=${db.hasUserTables}`)

    if (head && db.revision === head) {
      writeRuntime({ dataSchemaVersion: head })
      return // same revision already applied: no backup, no migrate
    }

    // The schema migrations create pgvector objects; they cannot complete without it.
    if (!this.pgvectorOk) {
      throw new DharaError('PGVECTOR', MSG.pgvectorMissing, 'pgvector not available in bundled Postgres')
    }

    // Anything that already holds data gets a backup first. A fresh, empty database does not.
    if (db.hasUserTables || db.revision) {
      try {
        this.progress('backup', 'Backing up your data before updating…', 50)
        const record = await runPreMigrateBackup({
          appVersion,
          port: ports.postgres,
          password: secrets.dbPassword,
          stopPostgres: () => this.pg.stop(),
          startPostgres: async () => {
            await this.pg.start(ports.postgres, secrets.dbPassword, this.profile, { mode: 'none' })
            this.pg.onExit((code) => this.onPostgresExit(code))
          },
          onProgress: (m) => this.progress('backup', m, 52),
        })
        writeRuntime({ lastBackup: record })
      } catch (err) {
        writeRuntime({ lastMigrateOk: false, lastMigrateError: err instanceof Error ? err.message : String(err) })
        if (err instanceof DharaError) throw err
        throw new DharaError('BACKUP', MSG.backupFailed, String(err))
      }
    }

    this.progress('migrate', 'Updating your data…', 60)
    const r = await this.alembic(['upgrade', 'head'])
    if (r.code !== 0) {
      writeRuntime({
        lastMigrateOk: false,
        lastMigrateAt: new Date().toISOString(),
        lastMigrateAppVersion: appVersion,
        lastMigrateError: r.output.slice(-600),
      })
      throw new DharaError('MIGRATE', MSG.migrateFailed, `alembic exit ${r.code}: ${r.output.slice(-400)}`)
    }
    writeRuntime({
      dataSchemaVersion: head ?? undefined,
      lastMigrateOk: true,
      lastMigrateAt: new Date().toISOString(),
      lastMigrateAppVersion: appVersion,
      lastMigrateError: undefined,
    })
  }

  // ---------------------------------------------------------- API/worker

  private async spawnApi(): Promise<void> {
    if (!this.secrets || !this._ports) throw new Error('supervisor not initialised')
    const env = buildBackendEnv('api', this._ports, this.secrets, this.profile)
    const proc = ManagedProcess.spawn({
      name: 'api',
      exe: runtime.pythonExe(),
      args: [
        '-m', 'uvicorn', 'main:app',
        '--host', LOOPBACK,
        '--port', String(this._ports.api),
        '--log-level', 'info',
        '--no-access-log',
        '--no-server-header',
        '--timeout-keep-alive', '75',
      ],
      cwd: runtime.backendDir(),
      env,
      logFile: files.apiLog(),
    })
    this.api = proc
    await this.job.assign(proc.pid, 'api')
    void proc.exited.then(({ code }) => {
      if (!proc.stopping) this.onApiExit(code)
    })
  }

  private async spawnWorker(): Promise<void> {
    if (!this.secrets || !this._ports) throw new Error('supervisor not initialised')
    const env = buildBackendEnv('worker', this._ports, this.secrets, this.profile)
    const proc = ManagedProcess.spawn({
      name: 'worker',
      exe: runtime.pythonExe(),
      args: ['-m', 'app.workers.job_worker'],
      cwd: runtime.backendDir(),
      env,
      logFile: files.workerLog(),
    })
    this.worker = proc
    await this.job.assign(proc.pid, 'worker')
    void proc.exited.then(({ code }) => {
      if (!proc.stopping) this.onWorkerExit(code)
    })
  }

  private async waitForApiReady(): Promise<void> {
    const ports = this._ports as Ports
    const url = `http://${LOOPBACK}:${ports.api}/api/ready`
    const start = Date.now()
    let n = 0
    while (Date.now() - start < API_READY_TIMEOUT_MS) {
      if (this.api?.hasExited) {
        throw new DharaError('API_EXIT', MSG.api, `api exited during startup (code ${this.api.exitCode})`)
      }
      const r = await httpOk(url, 5000)
      if (r.ok) {
        try {
          const json = JSON.parse(r.body) as { status?: string }
          if (!json.status || json.status === 'ready') return
        } catch {
          return
        }
      }
      n += 1
      this.progress('api', 'Starting Dhara…', Math.min(90, 70 + n))
      await sleep(1000)
    }
    throw new DharaError('API_TIMEOUT', MSG.api, `api not ready after ${API_READY_TIMEOUT_MS / 1000}s`)
  }

  // ---------------------------------------------------------- exit hooks

  private pruneWindow(times: number[]): number[] {
    const cutoff = Date.now() - RESTART_WINDOW_MS
    return times.filter((t) => t > cutoff)
  }

  private onWorkerExit(code: number | null): void {
    if (this._state !== 'running') return
    this.worker = null
    this.workerRestarts = this.pruneWindow(this.workerRestarts)
    this.workerRestarts.push(Date.now())
    if (this.workerRestarts.length > MAX_RESTARTS) {
      this.lastError = 'The background worker keeps stopping. See worker.log.'
      log.error(`worker crashed ${this.workerRestarts.length}× in 10 min — giving up (last code ${code})`)
      this.emit('service-failed', 'worker')
      return
    }
    const delay = Math.min(30_000, 1000 * 2 ** (this.workerRestarts.length - 1))
    log.warn(`worker exited unexpectedly (code ${code}) — restarting in ${delay}ms (API stays up)`)
    this.restartTimer = setTimeout(() => {
      if (this._state === 'running' && !this.worker) {
        this.spawnWorker()
          .then(() => this.persistRunning())
          .catch((e) => log.error('worker restart failed', e))
      }
    }, delay)
  }

  private onApiExit(code: number | null): void {
    if (this._state !== 'running') return
    this.api = null
    this.apiRestarts = this.pruneWindow(this.apiRestarts)
    this.apiRestarts.push(Date.now())
    if (this.apiRestarts.length > 3) {
      this.lastError = MSG.api
      log.error(`api crashed repeatedly (last code ${code}) — giving up`)
      this.setState('error')
      this.emit('service-failed', 'api')
      return
    }
    log.warn(`api exited unexpectedly (code ${code}) — restarting`)
    this.spawnApi()
      .then(() => this.waitForApiReady())
      .then(() => this.persistRunning())
      .catch((e) => {
        log.error('api restart failed', e)
        this.lastError = MSG.api
        this.setState('error')
        this.emit('service-failed', 'api')
      })
  }

  private onPostgresExit(code: number | null): void {
    if (this._state !== 'running' && this._state !== 'starting') return
    log.error(`postgres exited unexpectedly (code ${code})`)
    if (this._state === 'starting') return // startup path reports it
    this.lastError = MSG.database
    this.setState('error')
    this.emit('service-failed', 'postgres')
    void this.teardown({ keepRecord: false })
  }

  /** Restart only the worker (does not touch the API or Postgres). */
  async restartWorker(): Promise<void> {
    if (this._state !== 'running') return
    if (this.worker) await this.worker.kill()
    if (this.adoptedWorkerPid) {
      await killTree(this.adoptedWorkerPid)
      this.adoptedWorkerPid = null
    }
    this.worker = null
    await this.spawnWorker()
    this.persistRunning()
  }

  // -------------------------------------------------------------- timers

  private startTimers(): void {
    this.stopTimers()
    this.healthFailures = 0
    this.healthTimer = setInterval(() => void this.healthCheck(), HEALTH_INTERVAL_MS)
    this.trimTimer = setInterval(() => {
      for (const f of [files.apiLog(), files.workerLog(), files.postgresLog()]) trimLiveLog(f)
    }, LOG_TRIM_INTERVAL_MS)
  }

  private stopTimers(): void {
    if (this.healthTimer) clearInterval(this.healthTimer)
    if (this.trimTimer) clearInterval(this.trimTimer)
    if (this.restartTimer) clearTimeout(this.restartTimer)
    this.healthTimer = this.trimTimer = this.restartTimer = null
  }

  private async healthCheck(): Promise<void> {
    if (this._state !== 'running' || !this._ports) return
    const r = await httpOk(`http://${LOOPBACK}:${this._ports.api}/api/live`, 5000)
    if (r.ok) {
      this.healthFailures = 0
    } else {
      this.healthFailures += 1
      if (this.healthFailures === 3) log.warn('API health check failing (3 in a row)')
    }
    // Adopted processes have no exit event — watch their pids.
    if (this.adoptedApiPid && !isPidAlive(this.adoptedApiPid)) {
      this.adoptedApiPid = null
      this.lastError = MSG.api
      this.setState('error')
      this.emit('service-failed', 'api')
    }
    if (this.adoptedWorkerPid && !isPidAlive(this.adoptedWorkerPid)) {
      this.adoptedWorkerPid = null
      this.spawnWorker().then(() => this.persistRunning()).catch((e) => log.error('worker respawn failed', e))
    }
  }

  // ---------------------------------------------------------------- stop

  private persistRunning(): void {
    if (!this._ports) return
    writeRuntime({
      running: {
        appVersion: app.getVersion(),
        startedAt: new Date().toISOString(),
        pgPort: this._ports.postgres,
        apiPort: this._ports.api,
        pgPid: this.pg.pid,
        apiPid: this.api?.pid ?? this.adoptedApiPid ?? undefined,
        workerPid: this.worker?.pid ?? this.adoptedWorkerPid ?? undefined,
      },
    })
  }

  /** Orderly stop: worker → API → Postgres (pg_ctl stop). */
  stop(): Promise<void> {
    if (this.stopping) return this.stopping
    this.stopping = (async () => {
      if (this.starting) await this.starting.catch(() => undefined)
      if (this._state === 'stopped') return
      this.setState('stopping')
      this.progress('stopping', 'Stopping Dhara…', 50)
      await this.teardown({ keepRecord: false })
      this.setState('stopped')
      this.progress('stopped', 'Dhara services are stopped', 100)
    })().finally(() => {
      this.stopping = null
    })
    return this.stopping
  }

  private async teardown(_opts: { keepRecord: boolean }): Promise<void> {
    this.stopTimers()
    if (this.worker) await this.worker.kill().catch(() => undefined)
    if (this.adoptedWorkerPid) await killTree(this.adoptedWorkerPid)
    this.worker = null
    this.adoptedWorkerPid = null

    if (this.api) await this.api.kill().catch(() => undefined)
    if (this.adoptedApiPid) await killTree(this.adoptedApiPid)
    this.api = null
    this.adoptedApiPid = null

    await this.pg.stop().catch((e) => log.warn(`postgres stop: ${String(e)}`))
    writeRuntime({ running: null })
  }

  /**
   * “Keep running on quit”: let Postgres/API/worker outlive Electron.
   * Clears kill-on-close on the Job Object; the next launch adopts the running services.
   */
  async detachForQuit(): Promise<void> {
    this.stopTimers()
    this.persistRunning()
    await this.job.detach()
    log.info('Services detached — they keep running after Electron exits')
  }

  /** Close the Job Object (kills anything still inside it unless detached). */
  closeJob(): void {
    this.job.close()
  }

  get isBusy(): boolean {
    return this.starting !== null || this.stopping !== null
  }
}
