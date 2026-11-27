import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { BrowserWindow, WebContents } from 'electron'
import { JobObject } from './job-object'
import {
  bundledOllamaManaged,
  bundledOllamaPresent,
  ensureOllamaRunning,
} from './ollama-process'
import { OLLAMA_ORIGIN, OLLAMA_OPENAI_BASE_URL, dirs } from './paths'
import { freeDiskBytes, GiB, ramInfo } from './sysinfo'
import { log } from './logger'

export const OLLAMA_DOWNLOAD_PAGE = 'https://ollama.com/download'
export const LOCAL_MODEL_ID = 'gemma3:1b'
export const MIN_OLLAMA_VERSION = '0.6.0'
export const PULL_BYTES_GUIDANCE = GiB // ~1 GiB free before pull
export const TEST_TIMEOUT_MS = 60_000
export const APPROX_DOWNLOAD_LABEL = '~800 MB'
export const RAM_WARN_AVAILABLE_MB = 1200

export interface OllamaDefaults {
  modelId: string
  baseUrl: string
  origin: string
  approxSizeLabel: string
  minVersion: string
}

export interface OllamaStatus {
  reachable: boolean
  baseUrl: string
  origin: string
  models: string[]
  modelPresent: boolean
  version: string
  versionOk: boolean
  versionWarning?: string
  diskOk: boolean
  freeBytes?: number
  diskPathHint?: string
  diskMessage?: string
  error?: string
  /** Bundled ollama.exe is present under resources/win-x64/ollama. */
  bundled: boolean
  /** Dhara spawned the current Ollama process. */
  managed: boolean
  defaults: OllamaDefaults
}

export type PullPhase = 'idle' | 'pulling' | 'success' | 'error' | 'cancelled'

export interface PullStatus {
  phase: PullPhase
  percent: number | null
  status: string
  error?: string
  startedAt?: number
  completed?: number
  total?: number
}

export interface TestConnectionResult {
  ok: boolean
  latencyMs: number
  availableRamMb?: number
  ramWarning?: string
  error?: string
}

const INTERRUPT_MSG =
  'Download interrupted. It is safe to retry — Ollama will resume.'

let pullAbort: AbortController | null = null
let pullState: PullStatus = { phase: 'idle', percent: null, status: '' }
let pullPromise: Promise<PullStatus> | null = null

function defaults(): OllamaDefaults {
  return {
    modelId: LOCAL_MODEL_ID,
    baseUrl: OLLAMA_OPENAI_BASE_URL,
    origin: OLLAMA_ORIGIN,
    approxSizeLabel: APPROX_DOWNLOAD_LABEL,
    minVersion: MIN_OLLAMA_VERSION,
  }
}

export function ollamaDefaults(): OllamaDefaults {
  return defaults()
}

/** Strip prerelease/build (`0.6.0-rc1` → `[0,6,0]`). Returns null if unparseable. */
export function parseOllamaVersion(raw: string): number[] | null {
  const trimmed = (raw || '').trim()
  if (!trimmed) return null
  const core = trimmed.split(/[-+]/)[0]?.trim()
  if (!core || !/^\d+(\.\d+)*$/.test(core)) return null
  const parts = core.split('.').map((p) => Number.parseInt(p, 10))
  if (parts.some((n) => !Number.isFinite(n))) return null
  return parts
}

export function isVersionAtLeast(raw: string, min: string): boolean | null {
  const a = parseOllamaVersion(raw)
  const b = parseOllamaVersion(min)
  if (!a || !b) return null
  const n = Math.max(a.length, b.length)
  for (let i = 0; i < n; i++) {
    const d = (a[i] ?? 0) - (b[i] ?? 0)
    if (d !== 0) return d > 0
  }
  return true
}

export function isLocalModelPresent(names: string[]): boolean {
  return names.some((n) => n.trim().toLowerCase() === LOCAL_MODEL_ID)
}

function resolveOllamaModelsRoot(): { root: string; known: boolean } {
  const env = (process.env.OLLAMA_MODELS || '').trim()
  if (env) return { root: path.resolve(env), known: true }
  // Prefer Dhara-managed models dir when we ship Ollama (or after we have started it).
  if (bundledOllamaPresent() || bundledOllamaManaged()) {
    return { root: dirs.ollamaModels(), known: true }
  }
  const home = path.join(os.homedir(), '.ollama')
  if (fs.existsSync(home)) return { root: home, known: true }
  return { root: home, known: false }
}

async function diskCheck(): Promise<{
  diskOk: boolean
  freeBytes?: number
  diskPathHint?: string
  diskMessage?: string
}> {
  const { root, known } = resolveOllamaModelsRoot()
  const probe = known && fs.existsSync(root) ? root : path.parse(root).root || os.homedir()
  try {
    const freeBytes = await freeDiskBytes(probe)
    const diskOk = freeBytes >= PULL_BYTES_GUIDANCE
    const diskPathHint = known ? root : undefined
    const where = known
      ? 'on the drive where Ollama stores models'
      : 'on your system drive'
    const diskMessage = diskOk
      ? undefined
      : `Need about 1 GB free ${where} before downloading ${LOCAL_MODEL_ID}.`
    return { diskOk, freeBytes, diskPathHint, diskMessage }
  } catch (err) {
    log.warn(`ollama disk check failed: ${String(err)}`)
    return {
      diskOk: true, // don't hard-block if we can't measure
      diskMessage: `Could not check free disk space. Make sure you have about 1 GB free on your system drive before downloading.`,
    }
  }
}

async function fetchVersion(): Promise<{
  version: string
  versionOk: boolean
  versionWarning?: string
}> {
  try {
    const res = await fetch(`${OLLAMA_ORIGIN}/api/version`, { signal: AbortSignal.timeout(3000) })
    if (!res.ok) {
      return {
        version: 'unknown',
        versionOk: true,
        versionWarning: `Could not confirm Ollama version; ${MIN_OLLAMA_VERSION}+ is required for Gemma 3 1B.`,
      }
    }
    const json = (await res.json()) as { version?: string }
    const raw = typeof json.version === 'string' ? json.version.trim() : ''
    if (!raw || parseOllamaVersion(raw) === null) {
      return {
        version: 'unknown',
        versionOk: true,
        versionWarning: `Could not confirm Ollama version; ${MIN_OLLAMA_VERSION}+ is required for Gemma 3 1B.`,
      }
    }
    const atLeast = isVersionAtLeast(raw, MIN_OLLAMA_VERSION)
    if (atLeast === false) {
      return {
        version: raw,
        versionOk: false,
        versionWarning: `Please update Ollama to ${MIN_OLLAMA_VERSION} or newer to use Gemma 3 1B (found ${raw}).`,
      }
    }
    return { version: raw, versionOk: true }
  } catch {
    return {
      version: 'unknown',
      versionOk: true,
      versionWarning: `Could not confirm Ollama version; ${MIN_OLLAMA_VERSION}+ is required for Gemma 3 1B.`,
    }
  }
}

/**
 * Status for the Settings “use a local model” opt-in.
 * When `ensure` is true (default for IPC), start bundled Ollama if nothing is listening.
 */
export async function ollamaStatus(
  opts: { ensure?: boolean; job?: JobObject | null } = {},
): Promise<OllamaStatus> {
  const ensure = opts.ensure !== false
  const bundled = bundledOllamaPresent()
  const base: OllamaStatus = {
    reachable: false,
    baseUrl: OLLAMA_OPENAI_BASE_URL,
    origin: OLLAMA_ORIGIN,
    models: [],
    modelPresent: false,
    version: 'unknown',
    versionOk: true,
    diskOk: true,
    bundled,
    managed: bundledOllamaManaged(),
    defaults: defaults(),
  }

  if (ensure) {
    const started = await ensureOllamaRunning(opts.job)
    base.bundled = started.bundled
    base.managed = started.managed
    if (!started.reachable) {
      const disk = await diskCheck()
      return {
        ...base,
        diskOk: disk.diskOk,
        freeBytes: disk.freeBytes,
        diskPathHint: disk.diskPathHint,
        diskMessage: disk.diskMessage,
        error: started.error || 'Ollama is not reachable.',
      }
    }
  }

  try {
    const res = await fetch(`${OLLAMA_ORIGIN}/api/tags`, { signal: AbortSignal.timeout(3000) })
    if (!res.ok) {
      return { ...base, error: `HTTP ${res.status}` }
    }
    const json = (await res.json()) as { models?: Array<{ name?: string }> }
    const models = (json.models ?? []).map((m) => m.name ?? '').filter(Boolean)
    const ver = await fetchVersion()
    const disk = await diskCheck()
    return {
      ...base,
      reachable: true,
      managed: bundledOllamaManaged(),
      models,
      modelPresent: isLocalModelPresent(models),
      version: ver.version,
      versionOk: ver.versionOk,
      versionWarning: ver.versionWarning,
      diskOk: disk.diskOk,
      freeBytes: disk.freeBytes,
      diskPathHint: disk.diskPathHint,
      diskMessage: disk.diskMessage,
    }
  } catch (err) {
    return {
      ...base,
      error: err instanceof Error ? err.message : String(err),
    }
  }
}

function setPullState(next: PullStatus): void {
  pullState = next
}

export function getPullStatus(): PullStatus {
  return { ...pullState }
}

function broadcastProgress(payload: PullStatus & { event?: string }): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (win.isDestroyed()) continue
    try {
      win.webContents.send('ollama:pull-progress', payload)
    } catch {
      /* ignore */
    }
  }
}

/**
 * Abort any in-flight pull without awaiting the stream (safe for app quit).
 */
export function abortPullFireAndForget(): void {
  if (pullAbort) {
    try {
      pullAbort.abort()
    } catch {
      /* ignore */
    }
    pullAbort = null
  }
  if (pullState.phase === 'pulling') {
    setPullState({
      phase: 'cancelled',
      percent: pullState.percent,
      status: 'cancelled',
      error: 'Cancelled',
      startedAt: pullState.startedAt,
    })
    broadcastProgress(getPullStatus())
  }
  pullPromise = null
}

export function cancelPull(): PullStatus {
  abortPullFireAndForget()
  return getPullStatus()
}

async function runPull(_sender: WebContents | null): Promise<PullStatus> {
  const controller = new AbortController()
  pullAbort = controller
  const startedAt = Date.now()
  setPullState({ phase: 'pulling', percent: null, status: 'starting', startedAt })
  broadcastProgress(getPullStatus())

  try {
    const res = await fetch(`${OLLAMA_ORIGIN}/api/pull`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: LOCAL_MODEL_ID, stream: true }),
      signal: controller.signal,
    })
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      throw new Error(body || `HTTP ${res.status}`)
    }
    if (!res.body) throw new Error('Empty pull response body')

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let lastPercent: number | null = null
    let lastStatus = 'pulling'

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split(/\r?\n/)
      buffer = lines.pop() ?? ''
      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed) continue
        let evt: {
          status?: string
          completed?: number
          total?: number
          error?: string
        }
        try {
          evt = JSON.parse(trimmed) as typeof evt
        } catch {
          continue
        }
        if (evt.error) throw new Error(evt.error)
        lastStatus = evt.status || lastStatus
        let percent: number | null = lastPercent
        if (
          typeof evt.total === 'number' &&
          evt.total > 0 &&
          typeof evt.completed === 'number'
        ) {
          percent = Math.min(100, Math.round((evt.completed / evt.total) * 100))
          lastPercent = percent
        }
        setPullState({
          phase: 'pulling',
          percent,
          status: lastStatus,
          startedAt,
          completed: evt.completed,
          total: evt.total,
        })
        broadcastProgress(getPullStatus())
        if (evt.status === 'success') {
          setPullState({
            phase: 'success',
            percent: 100,
            status: 'success',
            startedAt,
          })
          broadcastProgress(getPullStatus())
          return getPullStatus()
        }
      }
    }

    // Stream ended without explicit success — treat as success if no error
    setPullState({
      phase: 'success',
      percent: lastPercent ?? 100,
      status: 'success',
      startedAt,
    })
    broadcastProgress(getPullStatus())
    return getPullStatus()
  } catch (err) {
    const aborted = controller.signal.aborted
    const msg = aborted
      ? 'Cancelled'
      : err instanceof Error
        ? err.message
        : String(err)
    const friendly = aborted ? msg : INTERRUPT_MSG
    setPullState({
      phase: aborted ? 'cancelled' : 'error',
      percent: pullState.percent,
      status: aborted ? 'cancelled' : 'error',
      error: aborted ? msg : `${friendly} (${msg})`,
      startedAt,
    })
    broadcastProgress(getPullStatus())
    return getPullStatus()
  } finally {
    if (pullAbort === controller) pullAbort = null
    pullPromise = null
  }
}

/**
 * Start (or join) a pull of gemma3:1b. Idempotent while pulling.
 */
export async function pullStart(
  sender: WebContents | null,
  opts: { job?: JobObject | null } = {},
): Promise<PullStatus> {
  if (pullState.phase === 'pulling' && pullPromise) {
    return getPullStatus()
  }

  const st = await ollamaStatus({ ensure: true, job: opts.job })
  if (!st.reachable) {
    setPullState({
      phase: 'error',
      percent: null,
      status: 'error',
      error:
        st.error ||
        (st.bundled
          ? 'Bundled Ollama failed to start. See logs, then try again.'
          : 'Ollama is not reachable. Install and start Ollama, then try again.'),
    })
    return getPullStatus()
  }
  if (!st.versionOk) {
    setPullState({
      phase: 'error',
      percent: null,
      status: 'error',
      error: st.versionWarning || `Please update Ollama to ${MIN_OLLAMA_VERSION} or newer.`,
    })
    return getPullStatus()
  }
  if (!st.diskOk) {
    setPullState({
      phase: 'error',
      percent: null,
      status: 'error',
      error: st.diskMessage || 'Not enough free disk space to download the model.',
    })
    return getPullStatus()
  }
  if (st.modelPresent) {
    setPullState({
      phase: 'success',
      percent: 100,
      status: 'success',
    })
    return getPullStatus()
  }

  pullPromise = runPull(sender)
  // Return current status immediately; UI follows progress events.
  // Await is kept so invoke resolves when done (callers may await).
  return pullPromise
}

export async function testLocalModel(
  opts: { job?: JobObject | null } = {},
): Promise<TestConnectionResult> {
  const ensured = await ensureOllamaRunning(opts.job)
  if (!ensured.reachable) {
    return {
      ok: false,
      latencyMs: 0,
      error:
        ensured.error ||
        (ensured.bundled
          ? 'Bundled Ollama failed to start.'
          : 'Ollama is not reachable.'),
    }
  }
  const started = Date.now()
  try {
    const res = await fetch(`${OLLAMA_ORIGIN}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: LOCAL_MODEL_ID,
        messages: [{ role: 'user', content: 'ping' }],
        stream: false,
        keep_alive: '1m',
      }),
      signal: AbortSignal.timeout(TEST_TIMEOUT_MS),
    })
    const latencyMs = Date.now() - started
    if (!res.ok) {
      const body = await res.text().catch(() => '')
      return {
        ok: false,
        latencyMs,
        error: body || `HTTP ${res.status}`,
      }
    }
    const ram = ramInfo()
    const availableRamMb = ram.availableMiB
    const ramWarning =
      availableRamMb < RAM_WARN_AVAILABLE_MB
        ? `Available RAM is about ${availableRamMb} MB after loading the model. Large PDF jobs may be refused until the model unloads (often within a few minutes).`
        : undefined
    return { ok: true, latencyMs, availableRamMb, ramWarning }
  } catch (err) {
    const latencyMs = Date.now() - started
    const msg = err instanceof Error ? err.message : String(err)
    const timedOut = /timeout|aborted/i.test(msg)
    return {
      ok: false,
      latencyMs,
      error: timedOut
        ? 'Timed out while loading the model. On CPU this can take over a minute — try again, or free some RAM first.'
        : msg,
    }
  }
}
