import * as fs from 'node:fs'
import { JobObject } from './job-object'
import { log } from './logger'
import { ManagedProcess } from './managed-process'
import { OLLAMA_ORIGIN, dirs, files, runtime } from './paths'

const READY_TIMEOUT_MS = 60_000
const READY_POLL_MS = 400

let proc: ManagedProcess | null = null
let starting: Promise<EnsureOllamaResult> | null = null
/** True only when Dhara spawned the current Ollama process (not a system install). */
let weOwnProcess = false

export interface EnsureOllamaResult {
  ok: boolean
  reachable: boolean
  bundled: boolean
  managed: boolean
  error?: string
}

export function bundledOllamaPresent(): boolean {
  try {
    return fs.existsSync(runtime.ollamaExe())
  } catch {
    return false
  }
}

async function pingTags(timeoutMs = 2500): Promise<boolean> {
  try {
    const res = await fetch(`${OLLAMA_ORIGIN}/api/tags`, {
      signal: AbortSignal.timeout(timeoutMs),
    })
    return res.ok
  } catch {
    return false
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms))
}

/**
 * Prefer an already-running Ollama on 11434. Otherwise start the bundled
 * `ollama serve` (models under %LOCALAPPDATA%\Dhara\ollama) and assign it to
 * the Job Object when provided.
 */
export async function ensureOllamaRunning(job?: JobObject | null): Promise<EnsureOllamaResult> {
  if (starting) return starting
  starting = (async () => {
    const bundled = bundledOllamaPresent()
    if (await pingTags()) {
      return {
        ok: true,
        reachable: true,
        bundled,
        managed: weOwnProcess,
      }
    }

    if (!bundled) {
      return {
        ok: false,
        reachable: false,
        bundled: false,
        managed: false,
        error: 'Bundled Ollama is not installed. Install Ollama separately or rebuild with fetch-ollama.',
      }
    }

    if (proc && !proc.hasExited && proc.pid) {
      const ready = await waitUntilReady(READY_TIMEOUT_MS)
      if (ready) {
        return { ok: true, reachable: true, bundled: true, managed: true }
      }
      return {
        ok: false,
        reachable: false,
        bundled: true,
        managed: true,
        error: 'Bundled Ollama is starting but not responding yet.',
      }
    }

    const modelsDir = dirs.ollamaModels()
    const exe = runtime.ollamaExe()
    const cwd = runtime.ollamaDir()
    log.info(`starting bundled ollama serve (${exe})`)

    proc = ManagedProcess.spawn({
      name: 'ollama',
      exe,
      args: ['serve'],
      cwd,
      env: {
        ...process.env,
        OLLAMA_HOST: '127.0.0.1:11434',
        OLLAMA_MODELS: modelsDir,
        // Prefer our models dir over a user ~/.ollama from a prior system install.
        OLLAMA_HOME: modelsDir,
      },
      logFile: files.ollamaLog(),
    })
    weOwnProcess = true

    if (job && proc.pid) {
      try {
        await job.assign(proc.pid, 'ollama')
      } catch (err) {
        log.warn(`could not assign ollama to Job Object: ${String(err)}`)
      }
    }

    const ready = await waitUntilReady(READY_TIMEOUT_MS)
    if (!ready) {
      const code = proc.hasExited ? proc.exitCode : null
      return {
        ok: false,
        reachable: false,
        bundled: true,
        managed: true,
        error:
          code != null
            ? `Bundled Ollama exited during startup (code ${code}). See ollama.log.`
            : 'Bundled Ollama did not become ready in time. See ollama.log.',
      }
    }
    return { ok: true, reachable: true, bundled: true, managed: true }
  })().finally(() => {
    starting = null
  })

  return starting
}

async function waitUntilReady(timeoutMs: number): Promise<boolean> {
  const start = Date.now()
  while (Date.now() - start < timeoutMs) {
    if (proc?.hasExited) return false
    if (await pingTags(1500)) return true
    await sleep(READY_POLL_MS)
  }
  return pingTags(2000)
}

/** Stop only a Dhara-spawned Ollama. Never kill a pre-existing system Ollama. */
export async function stopBundledOllama(): Promise<void> {
  if (!weOwnProcess || !proc) {
    proc = null
    weOwnProcess = false
    return
  }
  const owned = proc
  proc = null
  weOwnProcess = false
  try {
    await owned.kill(8000)
  } catch (err) {
    log.warn(`stopBundledOllama: ${String(err)}`)
  }
}

export function bundledOllamaManaged(): boolean {
  return weOwnProcess && Boolean(proc && !proc.hasExited)
}
