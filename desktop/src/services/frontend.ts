import fs from 'node:fs'
import path from 'node:path'
import type { DharaPaths } from '../main/paths'
import { waitForHttpOk } from './health'
import { FileLogger } from './logger'
import { spawnLogged, type ManagedProcess } from './process'

function nodeExe(paths: DharaPaths): string {
  const candidates = [
    path.join(paths.nodeHome, 'node.exe'),
    path.join(paths.frontendRoot, 'node.exe'),
  ]
  for (const c of candidates) {
    if (fs.existsSync(c)) return c
  }
  return process.platform === 'win32' ? 'node.exe' : 'node'
}

export async function startFrontend(
  paths: DharaPaths,
  backendPort: number,
  uiPort: number,
  logger: FileLogger,
): Promise<ManagedProcess> {
  if (!fs.existsSync(paths.frontendRoot)) {
    throw new Error(`Packaged frontend missing at ${paths.frontendRoot}`)
  }
  const node = nodeExe(paths)
  const nextCli = path.join(paths.frontendRoot, 'node_modules', 'next', 'dist', 'bin', 'next')
  if (!fs.existsSync(nextCli)) {
    throw new Error(
      `next binary missing at ${nextCli}. Run desktop/scripts/prepare-frontend.ps1 before packaging.`,
    )
  }

  logger.info(`Starting Next.js on 127.0.0.1:${uiPort} (BACKEND_ORIGIN → :${backendPort})`)
  const managed = spawnLogged(
    'frontend',
    node,
    [nextCli, 'start', '--hostname', '127.0.0.1', '--port', String(uiPort)],
    {
      cwd: paths.frontendRoot,
      env: {
        ...process.env,
        BACKEND_ORIGIN: `http://127.0.0.1:${backendPort}`,
        PORT: String(uiPort),
        NODE_ENV: 'production',
      },
    },
    logger,
  )

  await waitForHttpOk(`http://127.0.0.1:${uiPort}/api/ready`, 180_000)
  return managed
}
