import { spawn, type ChildProcess, type SpawnOptions } from 'node:child_process'
import type { FileLogger } from './logger'

export type ManagedProcess = {
  name: string
  child: ChildProcess
  stop: (signal?: NodeJS.Signals) => Promise<void>
}

export function spawnLogged(
  name: string,
  command: string,
  args: string[],
  options: SpawnOptions,
  logger: FileLogger,
): ManagedProcess {
  const child = spawn(command, args, {
    ...options,
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })

  child.stdout?.on('data', (chunk) => logger.childStdout(chunk))
  child.stderr?.on('data', (chunk) => logger.childStdout(chunk))
  child.on('exit', (code, signal) => {
    logger.info(`${name} exited code=${code} signal=${signal}`)
  })

  return {
    name,
    child,
    stop: (signal: NodeJS.Signals = 'SIGTERM') =>
      new Promise((resolve) => {
        if (child.killed || child.exitCode !== null) {
          resolve()
          return
        }
        const timer = setTimeout(() => {
          if (child.exitCode === null) child.kill('SIGKILL')
        }, 8_000)
        child.once('exit', () => {
          clearTimeout(timer)
          resolve()
        })
        try {
          child.kill(signal)
        } catch {
          clearTimeout(timer)
          resolve()
        }
      }),
  }
}

export function runOnce(
  command: string,
  args: string[],
  options: SpawnOptions,
  logger: FileLogger,
  label: string,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      ...options,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    })
    child.stdout?.on('data', (chunk) => logger.childStdout(chunk))
    child.stderr?.on('data', (chunk) => logger.childStdout(chunk))
    child.on('error', reject)
    child.on('exit', (code) => {
      if (code === 0) resolve()
      else reject(new Error(`${label} failed with exit code ${code}`))
    })
  })
}
