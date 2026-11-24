import * as fs from 'node:fs'
import * as path from 'node:path'
import { log } from './logger'
import { runToCompletion } from './managed-process'
import { dirs, files, runtime } from './paths'
import { LOOPBACK } from './ports'
import { PG_DATABASE, PG_USER } from './postgres'
import { BackupRecord } from './runtime-state'
import { dirSizeBytes, formatBytes, freeDiskBytes, GiB } from './sysinfo'
import { DharaError, MSG } from './types'

/** Keep the newest N pre-migrate backups (dump files and pgdata copies combined). */
export const BACKUPS_TO_KEEP = 3
const MIN_FREE_BYTES = 2 * GiB
const FREE_FACTOR = 1.5

function stamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

export interface DiskCheck {
  ok: boolean
  neededBytes: number
  freeBytes: number
  pgdataBytes: number
}

/**
 * Need ≥ 1.5 × current pgdata size, and never less than 2 GB free on the volume
 * that holds %LOCALAPPDATA%\Dhara.
 */
export async function checkDiskForBackup(): Promise<DiskCheck> {
  const pgdataBytes = await dirSizeBytes(dirs.pgdata())
  const neededBytes = Math.max(Math.ceil(pgdataBytes * FREE_FACTOR), MIN_FREE_BYTES)
  const freeBytes = await freeDiskBytes(dirs.backups())
  return { ok: freeBytes >= neededBytes, neededBytes, freeBytes, pgdataBytes }
}

export interface BackupDeps {
  appVersion: string
  port: number
  password: string
  /** Stop postgres (for the cold pgdata copy fallback). */
  stopPostgres: () => Promise<void>
  /** Start postgres again after a cold copy. */
  startPostgres: () => Promise<void>
  onProgress?: (message: string) => void
}

async function tryPgDump(deps: BackupDeps, target: string): Promise<boolean> {
  // Version-matched pg_dump.exe from the same bundled pgsql\bin as the running server —
  // never whatever happens to be on PATH.
  const r = await runToCompletion(
    runtime.pgBin('pg_dump.exe'),
    [
      '-h', LOOPBACK,
      '-p', String(deps.port),
      '-U', PG_USER,
      '-d', PG_DATABASE,
      '-Fc',
      '--no-password',
      '-f', target,
    ],
    {
      env: { ...process.env, PGPASSWORD: deps.password, PGCONNECT_TIMEOUT: '15' },
      logFile: files.postgresLog(),
      timeoutMs: 60 * 60 * 1000,
    },
  )
  if (r.code !== 0) {
    log.warn(`pg_dump failed (exit ${r.code}): ${r.output.slice(-400)}`)
    return false
  }
  let size = 0
  try {
    size = fs.statSync(target).size
  } catch {
    /* missing */
  }
  if (size <= 0) {
    log.warn('pg_dump produced an empty file')
    return false
  }
  // Sanity-check that the archive is readable.
  const v = await runToCompletion(runtime.pgBin('pg_restore.exe'), ['--list', target], {
    timeoutMs: 120000,
  })
  if (v.code !== 0) {
    log.warn(`pg_restore --list failed on dump: ${v.output.slice(-300)}`)
    return false
  }
  return true
}

async function coldCopy(deps: BackupDeps, target: string): Promise<void> {
  deps.onProgress?.('Copying your database files (this can take a while)…')
  await deps.stopPostgres()
  let copyError: unknown = null
  try {
    await fs.promises.cp(dirs.pgdata(), target, {
      recursive: true,
      filter: (src) => path.basename(src).toLowerCase() !== 'postmaster.pid',
    })
    const [a, b] = await Promise.all([dirSizeBytes(dirs.pgdata()), dirSizeBytes(target)])
    // postmaster.pid is tiny; allow small drift from WAL/stat files.
    if (b + 1024 * 1024 < a) {
      throw new Error(`copy incomplete (${formatBytes(b)} of ${formatBytes(a)})`)
    }
  } catch (err) {
    copyError = err
    try {
      fs.rmSync(target, { recursive: true, force: true })
    } catch {
      /* ignore */
    }
  }
  try {
    await deps.startPostgres()
  } catch (err) {
    log.error('Postgres failed to restart after cold backup', err)
    throw err
  }
  if (copyError) {
    throw new DharaError('BACKUP', MSG.backupFailed, `pgdata copy failed: ${String(copyError)}`)
  }
}

/** Keep only the newest BACKUPS_TO_KEEP pre-migrate backups. */
export function pruneBackups(keep: number = BACKUPS_TO_KEEP): void {
  const root = dirs.backups()
  const entries = fs
    .readdirSync(root, { withFileTypes: true })
    .filter(
      (e) =>
        (e.isFile() && e.name.startsWith('pre-migrate-') && e.name.endsWith('.dump')) ||
        (e.isDirectory() && e.name.startsWith('pgdata-pre-migrate-')),
    )
    .map((e) => {
      const full = path.join(root, e.name)
      return { full, mtime: fs.statSync(full).mtimeMs }
    })
    .sort((a, b) => b.mtime - a.mtime)
  for (const old of entries.slice(keep)) {
    try {
      fs.rmSync(old.full, { recursive: true, force: true })
      log.info(`Pruned old backup ${old.full}`)
    } catch (err) {
      log.warn(`Could not prune ${old.full}: ${String(err)}`)
    }
  }
}

/**
 * Pre-migrate backup. Order: disk check → bundled pg_dump → cold pgdata copy fallback.
 * Throws DharaError (and the caller must NOT migrate) on any failure.
 * runtime.json is never copied into the backups folder.
 */
export async function runPreMigrateBackup(deps: BackupDeps): Promise<BackupRecord> {
  const disk = await checkDiskForBackup()
  log.info(
    `Backup disk check: pgdata=${formatBytes(disk.pgdataBytes)} needed=${formatBytes(disk.neededBytes)} free=${formatBytes(disk.freeBytes)}`,
  )
  if (!disk.ok) {
    throw new DharaError(
      'DISK',
      MSG.disk,
      `free ${formatBytes(disk.freeBytes)} < needed ${formatBytes(disk.neededBytes)}`,
    )
  }

  const ts = stamp()
  const dumpPath = path.join(dirs.backups(), `pre-migrate-${deps.appVersion}-${ts}.dump`)
  deps.onProgress?.('Backing up your data before updating…')
  if (await tryPgDump(deps, dumpPath)) {
    pruneBackups()
    log.info(`Backup written: ${dumpPath}`)
    return {
      path: dumpPath,
      kind: 'pg_dump',
      at: new Date().toISOString(),
      appVersion: deps.appVersion,
      freeBytesAtBackup: disk.freeBytes,
    }
  }
  try {
    fs.rmSync(dumpPath, { force: true })
  } catch {
    /* ignore */
  }

  const copyPath = path.join(dirs.backups(), `pgdata-pre-migrate-${deps.appVersion}-${ts}`)
  log.warn('Falling back to cold pgdata copy')
  await coldCopy(deps, copyPath)
  pruneBackups()
  log.info(`Backup written: ${copyPath}`)
  return {
    path: copyPath,
    kind: 'pgdata-copy',
    at: new Date().toISOString(),
    appVersion: deps.appVersion,
    freeBytesAtBackup: disk.freeBytes,
  }
}
