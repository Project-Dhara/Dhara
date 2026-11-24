import { ChildProcessWithoutNullStreams, spawn } from 'node:child_process'
import * as fs from 'node:fs'
import { helperScript } from './paths'
import { log } from './logger'

type Pending = { resolve: (line: string) => void }

/**
 * Windows Job Object with JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE.
 *
 * Implemented by a tiny PowerShell host process (resources/helpers/job-host.ps1) that owns the job
 * handle. Electron keeps the host's stdin open; if Electron exits or is force-killed, stdin closes,
 * the host exits, and Windows terminates every process assigned to the job. This avoids shipping a
 * native addon.
 */
export class JobObject {
  private proc: ChildProcessWithoutNullStreams | null = null
  private ready: Promise<boolean> | null = null
  private buffer = ''
  private waiters: Pending[] = []
  private detached = false

  /** Start the host (idempotent). Resolves true when the Job Object is usable. */
  start(): Promise<boolean> {
    if (this.ready) return this.ready
    this.ready = new Promise<boolean>((resolve) => {
      if (process.platform !== 'win32') return resolve(false)
      const script = helperScript('job-host.ps1')
      if (!fs.existsSync(script)) {
        log.warn(`Job Object host script not found: ${script}`)
        return resolve(false)
      }
      let settled = false
      const settle = (ok: boolean) => {
        if (!settled) {
          settled = true
          resolve(ok)
        }
      }
      try {
        this.proc = spawn(
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
          ],
          { windowsHide: true, stdio: ['pipe', 'pipe', 'pipe'] },
        )
      } catch (err) {
        log.warn(`Could not start Job Object host: ${String(err)}`)
        return settle(false)
      }

      this.proc.stdout.setEncoding('utf8')
      this.proc.stdout.on('data', (chunk: string) => {
        this.buffer += chunk
        let nl: number
        while ((nl = this.buffer.indexOf('\n')) >= 0) {
          const line = this.buffer.slice(0, nl).trim()
          this.buffer = this.buffer.slice(nl + 1)
          if (!line) continue
          if (line === 'READY') {
            log.info('Job Object host ready (kill-on-close enabled)')
            settle(true)
          } else if (line.startsWith('FATAL')) {
            log.warn(`Job Object host failed: ${line}`)
            settle(false)
          } else {
            const w = this.waiters.shift()
            if (w) w.resolve(line)
          }
        }
      })
      this.proc.stderr.on('data', (d: Buffer) => log.warn(`job-host stderr: ${d.toString().trim()}`))
      this.proc.stdin.on('error', () => {
        /* host died; handled by exit */
      })
      this.proc.on('exit', (code) => {
        log.info(`Job Object host exited (code ${code})`)
        this.proc = null
        for (const w of this.waiters.splice(0)) w.resolve('ERR 0 host-exited')
        settle(false)
      })
      this.proc.on('error', (err) => {
        log.warn(`Job Object host error: ${err.message}`)
        settle(false)
      })
      // Add-Type compilation can take a few seconds on first use / slow disks.
      setTimeout(() => settle(false), 30000)
    })
    return this.ready
  }

  private send(cmd: string, timeoutMs = 10000): Promise<string> {
    return new Promise((resolve) => {
      if (!this.proc || !this.proc.stdin.writable) return resolve('ERR 0 no-host')
      const waiter: Pending = { resolve }
      this.waiters.push(waiter)
      this.proc.stdin.write(cmd + '\n')
      setTimeout(() => {
        const i = this.waiters.indexOf(waiter)
        if (i >= 0) {
          this.waiters.splice(i, 1)
          resolve('ERR 0 timeout')
        }
      }, timeoutMs)
    })
  }

  /** Assign a running process to the job. Returns false (and logs) if it could not be assigned. */
  async assign(pid: number | undefined, label: string): Promise<boolean> {
    if (!pid) return false
    const ok = await this.start()
    if (!ok) return false
    const reply = await this.send(`ADD ${pid}`)
    if (reply.startsWith('OK')) {
      log.info(`Job Object: assigned ${label} (pid ${pid})`)
      return true
    }
    log.warn(`Job Object: could not assign ${label} (pid ${pid}): ${reply}`)
    return false
  }

  /** Clear kill-on-close so children survive Electron exiting (“Keep running on quit”). */
  async detach(): Promise<void> {
    if (!(await this.start())) return
    const reply = await this.send('DETACH')
    this.detached = reply.startsWith('OK')
    log.info(`Job Object: detach -> ${reply}`)
  }

  async attach(): Promise<void> {
    if (!(await this.start())) return
    const reply = await this.send('ATTACH')
    if (reply.startsWith('OK')) this.detached = false
  }

  get isDetached(): boolean {
    return this.detached
  }

  /** Close the host. Unless detached, every process in the job is killed by Windows. */
  close(): void {
    const p = this.proc
    if (!p) return
    try {
      p.stdin.end('EXIT\n')
    } catch {
      /* ignore */
    }
  }
}
