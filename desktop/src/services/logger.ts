import fs from 'node:fs'
import path from 'node:path'
import { createWriteStream, type WriteStream } from 'node:fs'

export class FileLogger {
  private stream: WriteStream

  constructor(logsDir: string, name: string) {
    fs.mkdirSync(logsDir, { recursive: true })
    this.stream = createWriteStream(path.join(logsDir, `${name}.log`), { flags: 'a' })
  }

  info(message: string): void {
    this.write('INFO', message)
  }

  error(message: string): void {
    this.write('ERROR', message)
  }

  childStdout(chunk: Buffer | string): void {
    this.stream.write(chunk)
  }

  private write(level: string, message: string): void {
    const line = `[${new Date().toISOString()}] ${level} ${message}\n`
    this.stream.write(line)
    if (level === 'ERROR') console.error(message)
    else console.log(message)
  }

  close(): void {
    this.stream.end()
  }
}
