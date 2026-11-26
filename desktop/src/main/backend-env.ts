import * as fs from 'node:fs'
import * as path from 'node:path'
import { dirs, runtime, runtimeRoot } from './paths'
import { LOOPBACK } from './ports'
import { PG_DATABASE, PG_USER } from './postgres'
import { Secrets } from './runtime-state'
import { Ports, RamProfile } from './types'

interface Tuning {
  pdfCpuWorkers: number
  pdfCpuWorkersMax: number
  pdfBatchFileConcurrency: number
  pdfOpenaiWorkers: number
  apiPool: number
  apiOverflow: number
  workerPool: number
  workerOverflow: number
  torchThreads: number
}

/** Processing caps: conservative on 8 GB, higher on 16 GB+. */
function tuning(profile: RamProfile): Tuning {
  if (profile === 'large') {
    return {
      pdfCpuWorkers: 2,
      pdfCpuWorkersMax: 4,
      pdfBatchFileConcurrency: 2,
      pdfOpenaiWorkers: 4,
      apiPool: 8,
      apiOverflow: 8,
      workerPool: 4,
      workerOverflow: 4,
      torchThreads: 4,
    }
  }
  return {
    pdfCpuWorkers: 1,
    pdfCpuWorkersMax: 2,
    pdfBatchFileConcurrency: 1,
    pdfOpenaiWorkers: 1,
    // max_connections=20 on the 8 GB profile: API ≤10 + worker ≤5 + dump/migrate + reserved.
    apiPool: 5,
    apiOverflow: 5,
    workerPool: 3,
    workerOverflow: 2,
    // Keep encoding from starving Postgres / API on 8 GB hosts.
    torchThreads: 2,
  }
}

export function databaseUrl(password: string, pgPort: number): string {
  return `postgresql://${PG_USER}:${encodeURIComponent(password)}@${LOOPBACK}:${pgPort}/${PG_DATABASE}`
}

export type Role = 'api' | 'worker' | 'migrate'

/** Absolute folder for bundled EmbeddingGemma weights (empty when -SkipEmbeddings). */
export function ncoEmbeddingModelDir(): string {
  const skipMarker = path.join(runtimeRoot(), 'models', '.skip-embeddings')
  if (fs.existsSync(skipMarker)) return ''
  const dir = path.join(runtimeRoot(), 'models', 'embeddinggemma-300m')
  if (!fs.existsSync(path.join(dir, 'config.json'))) return ''
  return dir
}

/**
 * Environment for the bundled Python processes (API, worker, Alembic).
 * Deliberately: no DHARA_INLINE_JOBS (jobs run in the separate worker) and no MALLOC_ARENA_MAX
 * (a glibc setting — meaningless on Windows).
 */
export function buildBackendEnv(
  role: Role,
  ports: Ports,
  secrets: Secrets,
  profile: RamProfile,
): NodeJS.ProcessEnv {
  const t = tuning(profile)
  const origin = `http://${LOOPBACK}:${ports.api}`
  const base: NodeJS.ProcessEnv = { ...process.env }

  // Strip anything that must not leak from the parent environment.
  for (const k of [
    'DHARA_INLINE_JOBS',
    'MALLOC_ARENA_MAX',
    'PYTHONHOME',
    'PYTHONPATH',
    'VIRTUAL_ENV',
    'LLM_BASE_URL',
    'LLM_MODEL',
    'ANTHROPIC_API_KEY',
    'OPENAI_API_KEY',
  ]) {
    delete base[k]
  }

  const poolSize = role === 'worker' ? t.workerPool : t.apiPool
  const overflow = role === 'worker' ? t.workerOverflow : t.apiOverflow
  const modelDir = ncoEmbeddingModelDir()
  // Only the job worker loads EmbeddingGemma; API stays lean (NCO match is enqueued).
  const workerModel = role === 'worker' ? modelDir : ''

  const env: NodeJS.ProcessEnv = {
    ...base,
    PYTHONPATH: runtime.backendDir(),
    PYTHONUTF8: '1',
    PYTHONUNBUFFERED: '1',
    // Install dir is read-only for many users; precompiled .pyc files ship in the bundle.
    PYTHONDONTWRITEBYTECODE: '1',
    TEMP: dirs.tmp(),
    TMP: dirs.tmp(),

    DHARA_DESKTOP: '1',
    DHARA_BACKEND_DIR: runtime.backendDir(),
    DHARA_DATA_DIR: dirs.data(),

    DATABASE_URL: databaseUrl(secrets.dbPassword, ports.postgres),
    DATABASE_POOL_SIZE: String(poolSize),
    DATABASE_MAX_OVERFLOW: String(overflow),
    DISABLE_REQUEST_TIME_DDL: 'true',

    JWT_SECRET: secrets.jwtSecret,
    LLM_CREDENTIALS_KEY: secrets.llmCredentialsKey,
    ENABLE_SIGNUP: 'true',
    ENABLE_GCS: 'false',
    STORAGE_BACKEND: 'local',
    STORAGE_LOCAL_PATH: dirs.objectStore(),
    UPLOAD_ARCHIVE_PATH: dirs.data(),

    // Cloud / API-key LLM is the default; Ollama is an explicit Settings opt-in.
    LLM_BASE_URL: '',
    LLM_MODEL: '',

    // Bundled EmbeddingGemma — no first-run Hub download. Empty on API / SkipEmbeddings.
    NCO_EMBEDDING_MODEL: workerModel,
    NCO_EMBEDDING_FAMILY: workerModel ? 'embeddinggemma' : '',
    NCO_EMBEDDING_REVISION: workerModel ? '57c266a740f537b4dc058e1b0cda161fd15afa75' : '',
    HF_HUB_OFFLINE: '1',
    TRANSFORMERS_OFFLINE: '1',
    HF_DATASETS_OFFLINE: '1',
    OMP_NUM_THREADS: String(t.torchThreads),
    MKL_NUM_THREADS: String(t.torchThreads),
    TORCH_NUM_THREADS: String(t.torchThreads),
    // Gemma needs more headroom than BGE-small; fall back to keyword-only if tight.
    NCO_EMBEDDING_MIN_RAM_MB: profile === 'large' ? '900' : '1200',
    NCO_EMBEDDING_IDLE_SEC: '480',

    PDF_CPU_WORKERS: String(t.pdfCpuWorkers),
    PDF_CPU_WORKERS_MAX: String(t.pdfCpuWorkersMax),
    PDF_BATCH_FILE_CONCURRENCY: String(t.pdfBatchFileConcurrency),
    PDF_OPENAI_WORKERS: String(t.pdfOpenaiWorkers),
    DHARA_MIN_AVAILABLE_RAM_MB: '1200',
    DHARA_WORKER_POLL_SECONDS: '1.5',
    DHARA_JOB_WORKERS: '1',
    DHARA_RAM_PROFILE: profile,
  }

  if (role === 'api') {
    Object.assign(env, {
      // Localhost hardening — API serves the static UI, /api and /mcp on one loopback port.
      DHARA_LISTEN_HOST: LOOPBACK,
      PORT: String(ports.api),
      DHARA_STATIC_UI_ROOT: runtime.frontendDir(),
      DHARA_ALLOWED_HOSTS: [
        LOOPBACK,
        'localhost',
        `${LOOPBACK}:${ports.api}`,
        `localhost:${ports.api}`,
      ].join(','),
      DHARA_CORS_ORIGINS: [origin, `http://localhost:${ports.api}`].join(','),
      // MCP is never open on desktop: per-install bearer token only.
      MCP_HTTP_AUTH: 'token',
      MCP_AUTH_TOKEN: secrets.mcpAuthToken,
    })
  } else {
    // Worker/migrate processes do not serve HTTP; they still read the same MCP settings.
    Object.assign(env, {
      MCP_HTTP_AUTH: 'token',
      MCP_AUTH_TOKEN: secrets.mcpAuthToken,
    })
  }

  // Make sure these are truly absent for every role.
  delete env.DHARA_INLINE_JOBS
  delete env.MALLOC_ARENA_MAX
  return env
}
