import type { RuntimeConfig } from '../main/config'
import type { DharaPaths } from '../main/paths'
import { backendEnv, pythonExe } from './backend'
import { FileLogger } from './logger'
import { spawnLogged, type ManagedProcess } from './process'

/**
 * Parity with docker-compose `worker` service:
 * `python -m app.workers.job_worker` with DHARA_INLINE_JOBS=false.
 */
export async function startWorker(
  paths: DharaPaths,
  cfg: RuntimeConfig,
  pgPort: number,
  backendPort: number,
  logger: FileLogger,
): Promise<ManagedProcess> {
  const py = pythonExe(paths)
  logger.info('Starting extraction job_worker')
  return spawnLogged(
    'worker',
    py,
    ['-m', 'app.workers.job_worker'],
    {
      cwd: paths.backendRoot,
      env: backendEnv(paths, cfg, pgPort, backendPort),
    },
    logger,
  )
}
