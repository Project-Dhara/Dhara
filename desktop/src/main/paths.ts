import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { app } from 'electron'

export const APP_DIR_NAME = 'Dhara'

export const PREFERRED_PG_PORT = 55432
export const PREFERRED_API_PORT = 18000
export const OLLAMA_ORIGIN = 'http://127.0.0.1:11434'
export const OLLAMA_OPENAI_BASE_URL = 'http://127.0.0.1:11434/v1'

export function ensureDir(dir: string): string {
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

/** %LOCALAPPDATA%\Dhara — all mutable state lives here (never under the install dir). */
export function userDataRoot(): string {
  const local = process.env.LOCALAPPDATA || path.join(os.homedir(), 'AppData', 'Local')
  return path.join(local, APP_DIR_NAME)
}

export const dirs = {
  root: () => ensureDir(userDataRoot()),
  /** Chromium/Electron profile (safeStorage master key lives here, so it must be stable). */
  electron: () => ensureDir(path.join(userDataRoot(), 'electron')),
  pgdata: () => path.join(userDataRoot(), 'pgdata'),
  logs: () => ensureDir(path.join(userDataRoot(), 'logs')),
  backups: () => ensureDir(path.join(userDataRoot(), 'backups')),
  /** Object store, upload archives, PDF extraction output. */
  data: () => ensureDir(path.join(userDataRoot(), 'data')),
  objectStore: () => ensureDir(path.join(userDataRoot(), 'data', 'object_store')),
  tmp: () => ensureDir(path.join(userDataRoot(), 'tmp')),
}

export const files = {
  runtimeJson: () => path.join(userDataRoot(), 'runtime.json'),
  authBlob: () => path.join(userDataRoot(), 'auth.bin'),
  desktopLog: () => path.join(dirs.logs(), 'desktop.log'),
  postgresLog: () => path.join(dirs.logs(), 'postgres.log'),
  apiLog: () => path.join(dirs.logs(), 'api.log'),
  workerLog: () => path.join(dirs.logs(), 'worker.log'),
  postmasterPid: () => path.join(dirs.pgdata(), 'postmaster.pid'),
}

/**
 * Root that contains `win-x64/` and `helpers/`.
 * Packaged: process.resourcesPath (extraResources). Dev: desktop/resources.
 */
export function resourcesRoot(): string {
  if (process.env.DHARA_RESOURCES_ROOT) return process.env.DHARA_RESOURCES_ROOT
  if (app.isPackaged) return process.resourcesPath
  return path.join(__dirname, '..', '..', 'resources')
}

export function runtimeRoot(): string {
  return path.join(resourcesRoot(), 'win-x64')
}

export function helperScript(name: string): string {
  const packaged = path.join(resourcesRoot(), 'helpers', name)
  if (fs.existsSync(packaged)) return packaged
  // Dev fallback (resources/helpers lives beside win-x64 already, kept for clarity).
  return path.join(__dirname, '..', '..', 'resources', 'helpers', name)
}

export const runtime = {
  pgsqlRoot: () => path.join(runtimeRoot(), 'pgsql'),
  pgBin: (exe: string) => path.join(runtimeRoot(), 'pgsql', 'bin', exe),
  pythonDir: () => path.join(runtimeRoot(), 'python'),
  /**
   * Prefer pythonw.exe on Windows (GUI subsystem — no console window).
   * Falls back to python.exe when pythonw is missing.
   */
  pythonExe: () => {
    const dir = path.join(runtimeRoot(), 'python')
    const pythonw = path.join(dir, 'pythonw.exe')
    if (process.platform === 'win32' && fs.existsSync(pythonw)) return pythonw
    return path.join(dir, 'python.exe')
  },
  backendDir: () => path.join(runtimeRoot(), 'backend'),
  frontendDir: () => path.join(runtimeRoot(), 'frontend'),
}

/** Assets next to the compiled main process (dist/renderer). */
export function rendererFile(name: string): string {
  return path.join(__dirname, '..', 'renderer', name)
}

export function iconPath(): string {
  const inRenderer = rendererFile('logo.png')
  if (fs.existsSync(inRenderer)) return inRenderer
  return path.join(__dirname, '..', '..', 'resources', 'logo.png')
}

export function requiredRuntimePaths(): string[] {
  return [
    runtime.pgBin('postgres.exe'),
    runtime.pgBin('initdb.exe'),
    runtime.pgBin('pg_ctl.exe'),
    runtime.pgBin('pg_dump.exe'),
    runtime.pgBin('pg_restore.exe'),
    runtime.pgBin('psql.exe'),
    runtime.pgBin('pg_isready.exe'),
    runtime.pythonExe(),
    path.join(runtime.backendDir(), 'main.py'),
    path.join(runtime.backendDir(), 'alembic.ini'),
    path.join(runtime.frontendDir(), 'index.html'),
  ]
}
