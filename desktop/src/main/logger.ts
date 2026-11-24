import * as fs from 'node:fs'
import { files } from './paths'

const DEFAULT_MAX_BYTES = 5 * 1024 * 1024
const KEEP_ROTATED = 2

/**
 * Append-only log file with simple size-based rotation
 * (name.log → name.log.1 → name.log.2) so long-lived installs do not fill the disk.
 */
export class RotatingFile {
  private stream: fs.WriteStream | null = null
  private bytes = 0

  constructor(
    private readonly filePath: string,
    private readonly maxBytes: number = DEFAULT_MAX_BYTES,
  ) {
    try {
      this.bytes = fs.statSync(filePath).size
    } catch {
      this.bytes = 0
    }
    if (this.bytes >= this.maxBytes) this.rotate()
  }

  write(data: string | Buffer): void {
    const len = typeof data === 'string' ? Buffer.byteLength(data) : data.length
    if (this.bytes + len > this.maxBytes) this.rotate()
    this.ensureStream().write(data)
    this.bytes += len
  }

  close(): void {
    this.stream?.end()
    this.stream = null
  }

  private ensureStream(): fs.WriteStream {
    if (!this.stream) {
      this.stream = fs.createWriteStream(this.filePath, { flags: 'a' })
      this.stream.on('error', () => {
        /* never crash the app because a log write failed */
      })
    }
    return this.stream
  }

  private rotate(): void {
    this.stream?.end()
    this.stream = null
    try {
      for (let i = KEEP_ROTATED; i >= 1; i--) {
        const from = i === 1 ? this.filePath : `${this.filePath}.${i - 1}`
        const to = `${this.filePath}.${i}`
        if (fs.existsSync(from)) {
          try {
            fs.rmSync(to, { force: true })
            fs.renameSync(from, to)
          } catch {
            /* best effort */
          }
        }
      }
    } catch {
      /* best effort */
    }
    this.bytes = 0
  }
}

type Level = 'INFO' | 'WARN' | 'ERROR'

class DesktopLogger {
  private file: RotatingFile | null = null

  private sink(): RotatingFile {
    if (!this.file) this.file = new RotatingFile(files.desktopLog())
    return this.file
  }

  private line(level: Level, msg: string): void {
    const text = `${new Date().toISOString()} ${level.padEnd(5)} ${msg}\n`
    try {
      this.sink().write(text)
    } catch {
      /* ignore */
    }
    if (level === 'ERROR') console.error(text.trimEnd())
    else console.log(text.trimEnd())
  }

  info(msg: string): void {
    this.line('INFO', msg)
  }

  warn(msg: string): void {
    this.line('WARN', msg)
  }

  error(msg: string, err?: unknown): void {
    const extra = err instanceof Error ? ` :: ${err.message}` : err ? ` :: ${String(err)}` : ''
    this.line('ERROR', msg + extra)
  }

  /** Last N WARN/ERROR lines (for diagnostics). */
  recentProblems(max = 30): string[] {
    try {
      const raw = fs.readFileSync(files.desktopLog(), 'utf8')
      const lines = raw.split(/\r?\n/).filter((l) => / (WARN|ERROR) /.test(l))
      return lines.slice(-max)
    } catch {
      return []
    }
  }

  close(): void {
    this.file?.close()
    this.file = null
  }
}

export const log = new DesktopLogger()
