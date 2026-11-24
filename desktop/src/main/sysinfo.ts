import { execFile } from 'node:child_process'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { RamProfile } from './types'

const GiB = 1024 ** 3
const MiB = 1024 ** 2

export interface RamInfo {
  totalBytes: number
  availableBytes: number
  totalGiB: number
  availableMiB: number
  profile: RamProfile
  below8GB: boolean
}

/**
 * libuv's os.totalmem()/os.freemem() use GlobalMemoryStatusEx on Windows,
 * so `freemem()` is the *available* physical memory.
 */
export function ramInfo(): RamInfo {
  const total = os.totalmem()
  const avail = os.freemem()
  // 8 GB machines report ~7.7 GiB usable; 16 GB machines ~15.7 GiB.
  const profile: RamProfile = total >= 15 * GiB ? 'large' : 'standard'
  return {
    totalBytes: total,
    availableBytes: avail,
    totalGiB: total / GiB,
    availableMiB: Math.round(avail / MiB),
    profile,
    below8GB: total < 7.5 * GiB,
  }
}

function run(
  cmd: string,
  args: string[],
  timeoutMs = 15000,
): Promise<{ code: number | null; stdout: string; stderr: string }> {
  return new Promise((resolve) => {
    execFile(
      cmd,
      args,
      { windowsHide: true, timeout: timeoutMs, maxBuffer: 4 * 1024 * 1024 },
      (err, stdout, stderr) => {
        const errCode = err ? (err as { code?: number | string }).code : undefined
        const code: number | null = err ? (typeof errCode === 'number' ? errCode : 1) : 0
        resolve({ code, stdout: String(stdout ?? ''), stderr: String(stderr ?? '') })
      },
    )
  })
}

/**
 * True when the current process token is elevated (Run as administrator).
 * Uses the High Mandatory Level SID (S-1-16-12288) from `whoami /groups`.
 */
export async function isElevated(): Promise<boolean> {
  if (process.platform !== 'win32') return false
  const r = await run('whoami', ['/groups', '/fo', 'csv', '/nh'])
  if (r.stdout.includes('S-1-16-12288')) return true
  if (r.stdout.includes('S-1-16-16384')) return true // System integrity
  return false
}

export interface ProcessInfo {
  pid: number
  name: string
  exePath: string | null
}

/** Look up a process by PID (name + executable path). Returns null if it does not exist. */
export async function getProcessInfo(pid: number): Promise<ProcessInfo | null> {
  if (!Number.isInteger(pid) || pid <= 0) return null
  const script =
    `$p = Get-CimInstance Win32_Process -Filter 'ProcessId=${pid}' -ErrorAction SilentlyContinue; ` +
    `if ($p) { [Console]::Out.WriteLine(($p.Name + '|' + $p.ExecutablePath)) }`
  const r = await run(
    'powershell.exe',
    ['-NoProfile', '-NonInteractive', '-WindowStyle', 'Hidden', '-Command', script],
    20000,
  )
  const line = r.stdout.trim().split(/\r?\n/)[0] ?? ''
  if (!line) return null
  const idx = line.indexOf('|')
  const name = idx >= 0 ? line.slice(0, idx) : line
  const exe = idx >= 0 ? line.slice(idx + 1) : ''
  return { pid, name, exePath: exe || null }
}

export function isPidAlive(pid: number): boolean {
  if (!Number.isInteger(pid) || pid <= 0) return false
  try {
    process.kill(pid, 0)
    return true
  } catch (err) {
    // EPERM: exists but not ours to signal.
    return (err as NodeJS.ErrnoException).code === 'EPERM'
  }
}

/** Kill a process and its children (Windows tree kill). */
export function killTree(pid: number): Promise<void> {
  return new Promise((resolve) => {
    if (!isPidAlive(pid)) return resolve()
    execFile('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true }, () => resolve())
  })
}

export async function waitForPidExit(pid: number, timeoutMs: number): Promise<boolean> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (!isPidAlive(pid)) return true
    await new Promise((r) => setTimeout(r, 200))
  }
  return !isPidAlive(pid)
}

export function normalizePath(p: string): string {
  return path.resolve(p).replace(/\//g, '\\').toLowerCase()
}

export function isUnder(child: string | null, parent: string): boolean {
  if (!child) return false
  const c = normalizePath(child)
  const p = normalizePath(parent)
  return c === p || c.startsWith(p.endsWith('\\') ? p : p + '\\')
}

/** Free bytes available to the current user on the volume containing `p`. */
export async function freeDiskBytes(p: string): Promise<number> {
  // Walk up to an existing directory (statfs requires an existing path).
  let probe = path.resolve(p)
  while (!fs.existsSync(probe)) {
    const parent = path.dirname(probe)
    if (parent === probe) break
    probe = parent
  }
  const st = await fs.promises.statfs(probe)
  return Number(st.bavail) * Number(st.bsize)
}

export async function dirSizeBytes(dir: string): Promise<number> {
  let total = 0
  let entries: fs.Dirent[]
  try {
    entries = await fs.promises.readdir(dir, { withFileTypes: true })
  } catch {
    return 0
  }
  for (const e of entries) {
    const full = path.join(dir, e.name)
    try {
      if (e.isDirectory()) total += await dirSizeBytes(full)
      else if (e.isFile()) total += (await fs.promises.stat(full)).size
    } catch {
      /* file vanished or locked — ignore */
    }
  }
  return total
}

export function formatBytes(n: number): string {
  if (n >= GiB) return `${(n / GiB).toFixed(1)} GB`
  if (n >= MiB) return `${(n / MiB).toFixed(0)} MB`
  return `${Math.max(0, Math.round(n / 1024))} KB`
}

export { GiB, MiB, run as runCapture }
