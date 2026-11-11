import fs from 'node:fs'
import path from 'node:path'
import type { RuntimeConfig } from '../main/config'
import { databaseUrl } from '../main/config'
import type { DharaPaths } from '../main/paths'
import { waitForHttpOk } from './health'
import { FileLogger } from './logger'
import { runOnce, spawnLogged, type ManagedProcess } from './process'

export function pythonExe(paths: DharaPaths): string {
  const candidates = [
    path.join(paths.pythonHome, 'python.exe'),
    path.join(paths.pythonHome, 'Scripts', 'python.exe'),
    path.join(paths.backendRoot, '.venv', 'Scripts', 'python.exe'),
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) return c
  }
  throw new Error(
    `Bundled Python not found under ${paths.pythonHome}. Run desktop/scripts/prepare-backend.ps1 on Windows.`,
  )
}

export function backendEnv(
  paths: DharaPaths,
  cfg: RuntimeConfig,
  pgPort: number,
  backendPort: number,
): NodeJS.ProcessEnv {
  return {
    ...process.env,
    DATABASE_URL: databaseUrl(cfg, pgPort),
    ENABLE_GCS: 'false',
    STORAGE_BACKEND: 'local',
    STORAGE_LOCAL_PATH: paths.objectStore,
    JWT_SECRET: cfg.jwtSecret,
    ENABLE_SIGNUP: process.env.ENABLE_SIGNUP || 'true',
    DISABLE_REQUEST_TIME_DDL: 'true',
    // Match Compose: heavy jobs run in job_worker, not inside the API.
    DHARA_INLINE_JOBS: 'false',
    MALLOC_ARENA_MAX: '2',
    DHARA_WORKER_POLL_SECONDS: process.env.DHARA_WORKER_POLL_SECONDS || '1.5',
    UVICORN_LOOP: 'asyncio',
    PYTHONUTF8: '1',
    PYTHONIOENCODING: 'utf-8',
    PORT: String(backendPort),
  }
}

export async function runMigrations(
  paths: DharaPaths,
  cfg: RuntimeConfig,
  pgPort: number,
  backendPort: number,
  logger: FileLogger,
): Promise<void> {
  const py = pythonExe(paths)
  if (!fs.existsSync(paths.backendRoot)) {
    throw new Error(`Packaged backend missing at ${paths.backendRoot}`)
  }
  logger.info('Running alembic upgrade head')
  await runOnce(
    py,
    ['-m', 'alembic', 'upgrade', 'head'],
    {
      cwd: paths.backendRoot,
      env: backendEnv(paths, cfg, pgPort, backendPort),
    },
    logger,
    'alembic',
  )
}

export async function startBackend(
  paths: DharaPaths,
  cfg: RuntimeConfig,
  pgPort: number,
  backendPort: number,
  logger: FileLogger,
): Promise<ManagedProcess> {
  const py = pythonExe(paths)
  logger.info(`Starting uvicorn on 127.0.0.1:${backendPort}`)
  const managed = spawnLogged(
    'backend',
    py,
    [
      '-m',
      'uvicorn',
      'main:app',
      '--host',
      '127.0.0.1',
      '--port',
      String(backendPort),
      '--loop',
      'asyncio',
    ],
    {
      cwd: paths.backendRoot,
      env: backendEnv(paths, cfg, pgPort, backendPort),
    },
    logger,
  )

  await waitForHttpOk(`http://127.0.0.1:${backendPort}/api/ready`, 180_000)
  return managed
}
