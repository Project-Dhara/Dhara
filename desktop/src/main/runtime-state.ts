import * as crypto from 'node:crypto'
import * as fs from 'node:fs'
import { ensureDir, files, userDataRoot } from './paths'

export interface BackupRecord {
  path: string
  kind: 'pg_dump' | 'pgdata-copy'
  at: string
  appVersion: string
  freeBytesAtBackup: number
}

/** Info about processes left running after “Keep running on quit”. */
export interface RunningRecord {
  appVersion: string
  startedAt: string
  pgPort: number
  apiPort: number
  pgPid?: number
  apiPid?: number
  workerPid?: number
}

/**
 * %LOCALAPPDATA%\Dhara\runtime.json
 * Holds per-install secrets and non-secret runtime facts.
 * It is NEVER copied into backups and never included in diagnostics (secrets are redacted).
 */
export interface RuntimeState {
  schemaVersion: 1
  // --- secrets ---
  jwtSecret?: string
  llmCredentialsKey?: string
  mcpAuthToken?: string
  dbPassword?: string
  // --- facts ---
  lastPorts?: { postgres: number; api: number }
  running?: RunningRecord | null
  /** Alembic revision(s) last applied successfully. */
  dataSchemaVersion?: string
  lastMigrateOk?: boolean
  lastMigrateAt?: string
  lastMigrateAppVersion?: string
  lastMigrateError?: string
  lastBackup?: BackupRecord
  pgvectorAvailable?: boolean
  ramProfileApplied?: string
  keepRunningOnQuit?: boolean
  updatedAt?: string
}

const SECRET_KEYS: (keyof RuntimeState)[] = [
  'jwtSecret',
  'llmCredentialsKey',
  'mcpAuthToken',
  'dbPassword',
]

export function readRuntime(): RuntimeState {
  ensureDir(userDataRoot())
  const p = files.runtimeJson()
  if (!fs.existsSync(p)) return { schemaVersion: 1 }
  try {
    const parsed = JSON.parse(fs.readFileSync(p, 'utf8')) as RuntimeState
    return { ...parsed, schemaVersion: 1 }
  } catch {
    // Keep the corrupt file for support, then start fresh state.
    try {
      fs.copyFileSync(p, `${p}.corrupt-${Date.now()}`)
    } catch {
      /* ignore */
    }
    return { schemaVersion: 1 }
  }
}

export function writeRuntime(patch: Partial<RuntimeState>): RuntimeState {
  const next: RuntimeState = {
    ...readRuntime(),
    ...patch,
    schemaVersion: 1,
    updatedAt: new Date().toISOString(),
  }
  const p = files.runtimeJson()
  const tmp = `${p}.tmp`
  fs.writeFileSync(tmp, JSON.stringify(next, null, 2), { encoding: 'utf8', mode: 0o600 })
  fs.renameSync(tmp, p)
  return next
}

function randomHex(bytes: number): string {
  return crypto.randomBytes(bytes).toString('hex')
}

/** Fernet-compatible key: urlsafe base64 of 32 random bytes. */
function newFernetKey(): string {
  return crypto.randomBytes(32).toString('base64').replace(/\+/g, '-').replace(/\//g, '_')
}

export interface Secrets {
  jwtSecret: string
  llmCredentialsKey: string
  mcpAuthToken: string
  dbPassword: string
}

/**
 * Ensure per-install secrets exist. `allowNewDbPassword` must be false when a pgdata
 * cluster already exists (a new password would not match the cluster).
 */
export function ensureSecrets(opts: { allowNewDbPassword: boolean }): {
  secrets: Secrets
  generatedDbPassword: boolean
} {
  const cur = readRuntime()
  const patch: Partial<RuntimeState> = {}
  if (!cur.jwtSecret) patch.jwtSecret = randomHex(32)
  if (!cur.llmCredentialsKey) patch.llmCredentialsKey = newFernetKey()
  if (!cur.mcpAuthToken) patch.mcpAuthToken = randomHex(32)

  let generatedDbPassword = false
  if (!cur.dbPassword && opts.allowNewDbPassword) {
    patch.dbPassword = randomHex(24)
    generatedDbPassword = true
  }
  const next = Object.keys(patch).length ? writeRuntime(patch) : cur
  if (!next.dbPassword) {
    throw new Error('dbPassword missing')
  }
  return {
    secrets: {
      jwtSecret: next.jwtSecret as string,
      llmCredentialsKey: next.llmCredentialsKey as string,
      mcpAuthToken: next.mcpAuthToken as string,
      dbPassword: next.dbPassword,
    },
    generatedDbPassword,
  }
}

/** runtime.json with secrets replaced by "<redacted>" (safe for diagnostics). */
export function redactedRuntime(): Record<string, unknown> {
  const cur = readRuntime() as unknown as Record<string, unknown>
  const out: Record<string, unknown> = { ...cur }
  for (const k of SECRET_KEYS) {
    if (out[k]) out[k as string] = '<redacted>'
  }
  return out
}
