import { ChildProcess, spawn, spawnSync } from 'node:child_process'
import * as fs from 'node:fs'
import { helperScript } from './paths'
import { log, RotatingFile } from './logger'
import { isPidAlive, killTree, waitForPidExit } from './sysinfo'

export interface SpawnOptions {
  name: string
  exe: string
  args: string[]
  cwd?: string
  env?: NodeJS.ProcessEnv
  logFile: string
  /** Rotate the log at spawn time when it is already larger than this. */
  maxLogBytes?: number
}

const DEFAULT_MAX_LOG = 20 * 1024 * 1024

/** Move an oversized log to `<file>.1` (replacing any older one) and start a fresh file. */
export function rotateIfLarge(file: string, maxBytes: number = DEFAULT_MAX_LOG): void {
  try {
    if (fs.existsSync(file) && fs.statSync(file).size > maxBytes) {
      fs.rmSync(`${file}.1`, { force: true })
      fs.renameSync(file, `${file}.1`)
    }
  } catch {
    /* best effort */
  }
}

/**
 * Copy an oversized *live* log to `<file>.1` and truncate it in place.
 * Used for running services whose stdout/stderr are redirected straight to the file
 * (they keep appending after truncation).
 */
export function trimLiveLog(file: string, maxBytes: number = DEFAULT_MAX_LOG): boolean {
  try {
    if (!fs.existsSync(file) || fs.statSync(file).size <= maxBytes) return false
    fs.copyFileSync(file, `${file}.1`)
    fs.truncateSync(file, 0)
    return true
  } catch {
    return false
  }
}

function b64Json(value: unknown): string {
  return Buffer.from(JSON.stringify(value), 'utf8').toString('base64')
}

/** True when the exe is a Windows GUI-subsystem binary that never allocates a console. */
function isWindowsGuiSubsystemExe(exe: string): boolean {
  return /pythonw\.exe$/i.test(exe)
}

/**
 * A long-lived child process.
 *
 * On Windows, console-subsystem binaries (e.g. postgres.exe) are started with CreateNoWindow
 * so detached services do not open terminal windows. GUI binaries (pythonw.exe) use Node's
 * detached spawn with log-file stdio — same keep-running-on-quit behaviour as before.
 */
export class ManagedProcess {
  readonly name: string
  readonly child: ChildProcess | null
  readonly pid: number | undefined
  private exitInfo: { code: number | null; signal: NodeJS.Signals | null } | null = null
  readonly exited: Promise<{ code: number | null; signal: NodeJS.Signals | null }>
  /** Set before an intentional stop so exit handlers can tell a crash from a stop. */
  stopping = false
  private pidWatchTimer: ReturnType<typeof setInterval> | null = null

  private constructor(
    opts: { name: string; logFile: string },
    child: ChildProcess | null,
    pid: number | undefined,
  ) {
    this.name = opts.name
    this.child = child
    this.pid = pid
    this.exited = new Promise((resolve) => {
      const finish = (code: number | null, signal: NodeJS.Signals | null) => {
        if (this.exitInfo) return
        this.exitInfo = { code, signal }
        if (this.pidWatchTimer) {
          clearInterval(this.pidWatchTimer)
          this.pidWatchTimer = null
        }
        try {
          fs.appendFileSync(
            opts.logFile,
            `\n[${new Date().toISOString()}] ${opts.name} exited code=${code} signal=${signal}\n`,
          )
        } catch {
          /* ignore */
        }
        log.info(`${opts.name} exited (code=${code}, signal=${signal})`)
        resolve({ code, signal })
      }

      if (child) {
        child.once('exit', (code, signal) => finish(code, signal))
        return
      }

      if (pid && pid > 0) {
        this.pidWatchTimer = setInterval(() => {
          if (!isPidAlive(pid)) finish(0, null)
        }, 1000)
        return
      }

      finish(1, null)
    })
  }

  static spawn(opts: SpawnOptions): ManagedProcess {
    rotateIfLarge(opts.logFile, opts.maxLogBytes)
    fs.appendFileSync(
      opts.logFile,
      `\n[${new Date().toISOString()}] starting ${opts.name}: ${opts.exe} ${opts.args.join(' ')}\n`,
    )

    if (process.platform === 'win32' && !isWindowsGuiSubsystemExe(opts.exe)) {
      return ManagedProcess.spawnWindowsNoWindow(opts)
    }
    return ManagedProcess.spawnNodeDetached(opts)
  }

  /** Detached Node spawn with log-file stdio (pythonw / non-Windows). */
  private static spawnNodeDetached(opts: SpawnOptions): ManagedProcess {
    const fd = fs.openSync(opts.logFile, 'a')
    let child: ChildProcess
    try {
      child = spawn(opts.exe, opts.args, {
        cwd: opts.cwd,
        env: opts.env ?? process.env,
        windowsHide: true,
        // libuv puts every non-detached child in a kill-on-close job tied to Electron, which would
        // make “Keep services running on quit” impossible. Breaking away lets Dhara's own Job Object
        // (which can be detached on demand) own the lifetime instead.
        detached: true,
        stdio: ['ignore', fd, fd],
      })
    } finally {
      fs.closeSync(fd)
    }
    child.on('error', (err) => {
      try {
        fs.appendFileSync(opts.logFile, `\n[spawn error] ${err.message}\n`)
      } catch {
        /* ignore */
      }
      log.error(`${opts.name} spawn error`, err)
    })
    log.info(`${opts.name} started (pid ${child.pid})`)
    return new ManagedProcess(opts, child, child.pid)
  }

  /**
   * Start a Windows console-subsystem process with CreateNoWindow (no terminal).
   * Helper exits immediately; we track the child by PID. Logging must not rely on inherited
   * stdout — Postgres uses logging_collector; prefer pythonw for Python services.
   */
  private static spawnWindowsNoWindow(opts: SpawnOptions): ManagedProcess {
    const script = helperScript('start-no-window.ps1')
    const envForChild: Record<string, string> = {}
    const source = opts.env ?? process.env
    for (const [k, v] of Object.entries(source)) {
      if (typeof v === 'string') envForChild[k] = v
    }

    const result = spawnSync(
      'powershell.exe',
      [
        '-NoProfile',
        '-NonInteractive',
        '-WindowStyle',
        'Hidden',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        script,
        '-Exe',
        opts.exe,
        '-ArgsBase64',
        b64Json(opts.args),
        '-Cwd',
        opts.cwd || '',
        '-EnvBase64',
        b64Json(envForChild),
      ],
      {
        windowsHide: true,
        encoding: 'utf8',
        timeout: 30000,
      },
    )

    const combined = `${result.stdout || ''}\n${result.stderr || ''}`.trim()
    const okLine = combined
      .split(/\r?\n/)
      .map((l) => l.trim())
      .filter(Boolean)
      .reverse()
      .find((l) => l.startsWith('OK ') || l.startsWith('ERR '))

    if (!okLine || !okLine.startsWith('OK ')) {
      const msg = okLine || combined || `helper exit ${result.status}`
      try {
        fs.appendFileSync(opts.logFile, `\n[spawn error] ${msg}\n`)
      } catch {
        /* ignore */
      }
      log.error(`${opts.name} spawn error: ${msg}`)
      return new ManagedProcess(opts, null, undefined)
    }

    const childPid = Number(okLine.slice(3).trim())
    if (!Number.isInteger(childPid) || childPid <= 0) {
      log.error(`${opts.name} spawn error: bad pid line ${okLine}`)
      return new ManagedProcess(opts, null, undefined)
    }

    log.info(`${opts.name} started hidden (pid ${childPid})`)
    try {
      fs.appendFileSync(opts.logFile, `[hidden start] pid=${childPid}\n`)
    } catch {
      /* ignore */
    }
    return new ManagedProcess(opts, null, childPid)
  }

  get hasExited(): boolean {
    return this.exitInfo !== null
  }

  get exitCode(): number | null {
    return this.exitInfo?.code ?? null
  }

  /** Terminate the whole process tree (there is no graceful signal for console apps on Windows). */
  async kill(timeoutMs = 10000): Promise<void> {
    this.stopping = true
    if (this.pid && !this.hasExited) {
      await killTree(this.pid)
      await waitForPidExit(this.pid, timeoutMs)
    }
  }
}

/** Run a short-lived command, capturing combined output (also appended to a log file). */
export function runToCompletion(
  exe: string,
  args: string[],
  opts: {
    cwd?: string
    env?: NodeJS.ProcessEnv
    logFile?: string
    timeoutMs?: number
  } = {},
): Promise<{ code: number | null; output: string; timedOut: boolean }> {
  return new Promise((resolve) => {
    const sink = opts.logFile ? new RotatingFile(opts.logFile, 20 * 1024 * 1024) : null
    sink?.write(`\n[${new Date().toISOString()}] run: ${exe} ${args.join(' ')}\n`)
    const child = spawn(exe, args, {
      cwd: opts.cwd,
      env: opts.env ?? process.env,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let output = ''
    let timedOut = false
    const onData = (d: Buffer) => {
      if (output.length < 256 * 1024) output += d.toString()
      sink?.write(d)
    }
    child.stdout?.on('data', onData)
    child.stderr?.on('data', onData)
    const timer = opts.timeoutMs
      ? setTimeout(() => {
          timedOut = true
          if (child.pid) void killTree(child.pid)
        }, opts.timeoutMs)
      : null
    child.on('error', (err) => {
      output += `\n[spawn error] ${err.message}`
      sink?.write(`\n[spawn error] ${err.message}\n`)
    })
    child.on('close', (code) => {
      if (timer) clearTimeout(timer)
      sink?.write(`[exit ${code}]\n`)
      sink?.close()
      resolve({ code, output, timedOut })
    })
  })
}
