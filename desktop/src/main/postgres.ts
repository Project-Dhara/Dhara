import * as fs from 'node:fs'
import * as path from 'node:path'
import { JobObject } from './job-object'
import { log } from './logger'
import { ManagedProcess, runToCompletion } from './managed-process'
import { dirs, files, runtime } from './paths'
import { LOOPBACK } from './ports'
import { getProcessInfo, isPidAlive, isUnder, killTree, waitForPidExit } from './sysinfo'
import { DharaError, MSG, RamProfile } from './types'

export const PG_USER = 'dhara'
export const PG_DATABASE = 'dhara'

const PROFILE_BEGIN = '# >>> dhara-desktop-profile (managed by Dhara — do not edit this block) >>>'
const PROFILE_END = '# <<< dhara-desktop-profile <<<'

export interface PgProfile {
  shared_buffers: string
  work_mem: string
  maintenance_work_mem: string
  max_connections: number
  effective_cache_size: string
  max_wal_size: string
  checkpoint_completion_target: string
  random_page_cost: string
}

/** 8 GB default desktop profile; modestly higher on 16 GB+ hosts. */
export function pgProfile(profile: RamProfile): PgProfile {
  if (profile === 'large') {
    return {
      shared_buffers: '256MB',
      work_mem: '8MB',
      maintenance_work_mem: '128MB',
      max_connections: 40,
      effective_cache_size: '2GB',
      max_wal_size: '512MB',
      checkpoint_completion_target: '0.9',
      random_page_cost: '1.1',
    }
  }
  return {
    shared_buffers: '128MB',
    work_mem: '4MB',
    maintenance_work_mem: '64MB',
    max_connections: 20,
    effective_cache_size: '512MB',
    max_wal_size: '256MB',
    checkpoint_completion_target: '0.9',
    random_page_cost: '1.1',
  }
}

export type ExistingPostgres =
  | { mode: 'none' }
  | { mode: 'adopt'; pid: number; port: number }

interface PidFile {
  pid: number
  dataDir: string | null
  port: number | null
}

function parsePidFile(): PidFile | null {
  const p = files.postmasterPid()
  if (!fs.existsSync(p)) return null
  try {
    const lines = fs.readFileSync(p, 'utf8').split(/\r?\n/)
    const pid = parseInt(lines[0] ?? '', 10)
    const port = parseInt(lines[3] ?? '', 10)
    return {
      pid: Number.isFinite(pid) ? pid : 0,
      dataDir: lines[1] ? lines[1].trim() : null,
      port: Number.isFinite(port) ? port : null,
    }
  } catch {
    return { pid: 0, dataDir: null, port: null }
  }
}

export class PostgresService {
  private proc: ManagedProcess | null = null
  private adoptedPid: number | null = null
  private password = ''
  private port = 0

  constructor(private readonly job: JobObject) {}

  get pid(): number | undefined {
    return this.proc?.pid ?? this.adoptedPid ?? undefined
  }

  get isRunning(): boolean {
    if (this.proc) return !this.proc.hasExited
    return this.adoptedPid !== null && isPidAlive(this.adoptedPid)
  }

  clusterExists(): boolean {
    return fs.existsSync(path.join(dirs.pgdata(), 'PG_VERSION'))
  }

  // ---------------------------------------------------------------- init

  async initCluster(password: string, profile: RamProfile): Promise<void> {
    const pgdata = dirs.pgdata()
    if (this.clusterExists()) return
    log.info('Initialising new Postgres cluster')
    fs.mkdirSync(pgdata, { recursive: true })
    const pwfile = path.join(dirs.tmp(), `pg-pw-${process.pid}.txt`)
    fs.writeFileSync(pwfile, password, { encoding: 'utf8', mode: 0o600 })
    try {
      const r = await runToCompletion(
        runtime.pgBin('initdb.exe'),
        [
          '-D', pgdata,
          '-U', PG_USER,
          '-E', 'UTF8',
          '--locale=C',
          '--auth-host=scram-sha-256',
          '--auth-local=scram-sha-256',
          `--pwfile=${pwfile}`,
        ],
        { logFile: files.postgresLog(), timeoutMs: 180000 },
      )
      if (r.code !== 0) {
        // Leave no half-initialised cluster behind.
        try {
          fs.rmSync(pgdata, { recursive: true, force: true })
        } catch {
          /* ignore */
        }
        throw new DharaError('PG_INITDB', MSG.database, `initdb exit ${r.code}: ${r.output.slice(-400)}`)
      }
    } finally {
      try {
        fs.rmSync(pwfile, { force: true })
      } catch {
        /* ignore */
      }
    }
    this.writeProfile(0, profile)
  }

  /**
   * Write/refresh the managed block at the end of postgresql.conf (later settings win).
   * `port` of 0 skips the port line (initdb time).
   */
  writeProfile(port: number, profile: RamProfile): void {
    const conf = path.join(dirs.pgdata(), 'postgresql.conf')
    let text = fs.existsSync(conf) ? fs.readFileSync(conf, 'utf8') : ''
    const b = text.indexOf(PROFILE_BEGIN)
    if (b >= 0) {
      const e = text.indexOf(PROFILE_END, b)
      text = text.slice(0, b) + (e >= 0 ? text.slice(e + PROFILE_END.length) : '')
    }
    text = text.replace(/\s+$/, '\n')
    const p = pgProfile(profile)
    const lines = [
      PROFILE_BEGIN,
      `# profile: ${profile}`,
      `listen_addresses = '${LOOPBACK}'`,
      ...(port > 0 ? [`port = ${port}`] : []),
      `shared_buffers = ${p.shared_buffers}`,
      `work_mem = ${p.work_mem}`,
      `maintenance_work_mem = ${p.maintenance_work_mem}`,
      `max_connections = ${p.max_connections}`,
      `effective_cache_size = ${p.effective_cache_size}`,
      `max_wal_size = ${p.max_wal_size}`,
      `checkpoint_completion_target = ${p.checkpoint_completion_target}`,
      `random_page_cost = ${p.random_page_cost}`,
      `password_encryption = 'scram-sha-256'`,
      // File logging so postgres can start with CreateNoWindow (no console to attach).
      `logging_collector = on`,
      `log_destination = 'stderr'`,
      `log_directory = '${dirs.logs().replace(/\\/g, '/')}'`,
      `log_filename = 'postgresql.log'`,
      `log_truncate_on_rotation = on`,
      `log_rotation_age = 1d`,
      `log_line_prefix = '%m [%p] '`,
      PROFILE_END,
      '',
    ]
    fs.writeFileSync(conf, text + '\n' + lines.join('\n'), 'utf8')
    log.info(`postgresql.conf profile written (${profile}, port ${port || 'unchanged'})`)
  }

  // ------------------------------------------------- stale pid recovery

  /**
   * Inspect postmaster.pid. Removes a stale lock file; adopts a live Dhara Postgres;
   * refuses (never deletes) when a live foreign process holds the data directory.
   */
  async resolveExisting(): Promise<ExistingPostgres> {
    const info = parsePidFile()
    if (!info) return { mode: 'none' }

    const pidFile = files.postmasterPid()
    const removeStale = (why: string) => {
      log.warn(`Removing stale postmaster.pid (${why})`)
      try {
        fs.rmSync(pidFile, { force: true })
      } catch (err) {
        throw new DharaError('PG_LOCKED', MSG.database, `could not delete stale postmaster.pid: ${String(err)}`)
      }
    }

    if (!info.pid || !isPidAlive(info.pid)) {
      removeStale(`pid ${info.pid} is not running`)
      return { mode: 'none' }
    }

    const proc = await getProcessInfo(info.pid)
    if (!proc) {
      removeStale(`pid ${info.pid} not found`)
      return { mode: 'none' }
    }
    if (proc.name.toLowerCase() !== 'postgres.exe') {
      removeStale(`pid ${info.pid} was reused by ${proc.name}`)
      return { mode: 'none' }
    }
    if (isUnder(proc.exePath, runtime.pgsqlRoot()) && info.port) {
      log.info(`Live Dhara Postgres found (pid ${info.pid}, port ${info.port}) — adopting`)
      return { mode: 'adopt', pid: info.pid, port: info.port }
    }
    // A postgres.exe from somewhere else is alive and referenced by our lock file.
    throw new DharaError(
      'PG_LOCKED',
      MSG.databaseLocked,
      `postmaster.pid points at live postgres.exe (${proc.exePath}) pid ${info.pid}`,
    )
  }

  // --------------------------------------------------------------- start

  private pgEnv(): NodeJS.ProcessEnv {
    return {
      ...process.env,
      PGPASSWORD: this.password,
      PGCONNECT_TIMEOUT: '10',
      PGCLIENTENCODING: 'UTF8',
    }
  }

  async start(
    port: number,
    password: string,
    profile: RamProfile,
    existing: ExistingPostgres,
  ): Promise<void> {
    this.port = port
    this.password = password

    if (existing.mode === 'adopt') {
      this.adoptedPid = existing.pid
      this.port = existing.port
      await this.job.assign(existing.pid, 'postgres (adopted)')
      await this.waitReady(60000)
      return
    }

    this.writeProfile(port, profile)
    const proc = ManagedProcess.spawn({
      name: 'postgres',
      exe: runtime.pgBin('postgres.exe'),
      args: ['-D', dirs.pgdata()],
      cwd: runtime.pgsqlRoot(),
      env: {
        ...process.env,
        // Never let a stray environment redirect the server.
        PGDATA: dirs.pgdata(),
      },
      logFile: files.postgresLog(),
    })
    this.proc = proc
    await this.job.assign(proc.pid, 'postgres')

    try {
      await this.waitReady(180000)
    } catch (err) {
      await this.stop().catch(() => undefined)
      throw err
    }
  }

  async waitReady(timeoutMs: number): Promise<void> {
    const start = Date.now()
    while (Date.now() - start < timeoutMs) {
      if (this.proc?.hasExited) {
        throw new DharaError(
          'PG_START',
          MSG.database,
          `postgres exited during startup (code ${this.proc.exitCode})`,
        )
      }
      const r = await runToCompletion(
        runtime.pgBin('pg_isready.exe'),
        ['-h', LOOPBACK, '-p', String(this.port), '-U', PG_USER, '-d', 'postgres'],
        { timeoutMs: 8000 },
      )
      if (r.code === 0) return
      await new Promise((res) => setTimeout(res, 500))
    }
    throw new DharaError('PG_START', MSG.database, `postgres not ready after ${Math.round(timeoutMs / 1000)}s`)
  }

  // -------------------------------------------------------- SQL helpers

  /** Run SQL with the bundled psql.exe. Returns trimmed stdout (tuples only, unaligned). */
  async query(sql: string, database: string = PG_DATABASE): Promise<{ ok: boolean; out: string }> {
    const r = await runToCompletion(
      runtime.pgBin('psql.exe'),
      [
        '-h', LOOPBACK,
        '-p', String(this.port),
        '-U', PG_USER,
        '-d', database,
        '-X', '-q', '-t', '-A',
        '-v', 'ON_ERROR_STOP=1',
        '-c', sql,
      ],
      { env: this.pgEnv(), timeoutMs: 60000 },
    )
    return { ok: r.code === 0, out: r.output.trim() }
  }

  async ensureDatabase(): Promise<void> {
    const exists = await this.query(
      `SELECT 1 FROM pg_database WHERE datname='${PG_DATABASE}'`,
      'postgres',
    )
    if (!exists.ok) {
      throw new DharaError('PG_QUERY', MSG.database, `cannot query postgres: ${exists.out.slice(-300)}`)
    }
    if (exists.out.trim() !== '1') {
      const created = await this.query(
        `CREATE DATABASE ${PG_DATABASE} OWNER ${PG_USER} ENCODING 'UTF8' TEMPLATE template0`,
        'postgres',
      )
      if (!created.ok) {
        throw new DharaError('PG_QUERY', MSG.database, `CREATE DATABASE failed: ${created.out.slice(-300)}`)
      }
      log.info(`Created database ${PG_DATABASE}`)
    }
  }

  /** Best-effort extensions. Returns whether pgvector is usable. */
  async ensureExtensions(): Promise<boolean> {
    await this.query('CREATE EXTENSION IF NOT EXISTS pgcrypto').then((r) => {
      if (!r.ok) log.warn(`pgcrypto extension unavailable: ${r.out.slice(-200)}`)
    })
    const avail = await this.query(`SELECT count(*) FROM pg_available_extensions WHERE name='vector'`)
    if (!avail.ok || avail.out.trim() === '0') {
      log.warn('pgvector is not installed in the bundled Postgres — semantic features are disabled')
      return false
    }
    const r = await this.query('CREATE EXTENSION IF NOT EXISTS vector')
    if (!r.ok) {
      log.warn(`CREATE EXTENSION vector failed: ${r.out.slice(-200)}`)
      return false
    }
    return true
  }

  // ---------------------------------------------------------------- stop

  async stop(): Promise<void> {
    const pid = this.pid
    if (!pid) return
    if (this.proc) this.proc.stopping = true
    log.info(`Stopping postgres (pid ${pid})`)
    if (isPidAlive(pid)) {
      await runToCompletion(
        runtime.pgBin('pg_ctl.exe'),
        ['stop', '-D', dirs.pgdata(), '-m', 'fast', '-w', '-t', '30'],
        { logFile: files.postgresLog(), timeoutMs: 45000 },
      )
      const gone = await waitForPidExit(pid, 15000)
      if (!gone) {
        log.warn('postgres did not stop gracefully — killing process tree')
        await killTree(pid)
        await waitForPidExit(pid, 10000)
      }
    }
    await this.proc?.kill(2000).catch(() => undefined)
    this.proc = null
    this.adoptedPid = null
  }

  get currentPort(): number {
    return this.port
  }

  hasUnexpectedExit(): boolean {
    return !!this.proc && this.proc.hasExited && !this.proc.stopping
  }

  /** Resolves when the owned Postgres process exits (never for adopted instances). */
  onExit(cb: (code: number | null) => void): void {
    if (!this.proc) return
    const p = this.proc
    void p.exited.then(({ code }) => {
      if (!p.stopping) cb(code)
    })
  }
}
