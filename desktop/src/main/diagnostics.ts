import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'
import { app } from 'electron'
import { log } from './logger'
import { ncoEmbeddingModelDir } from './backend-env'
import { dirs, files, userDataRoot } from './paths'
import { isElevated, formatBytes, freeDiskBytes, ramInfo } from './sysinfo'
import { readRuntime } from './runtime-state'
import { ServiceSupervisor } from './supervisor'

/**
 * Plain-text support blurb. Contains NO secrets (JWT secret, LLM key, MCP token, DB password
 * are never read here) and no user data — only versions, ports, flags and recent log problems.
 */
export async function buildDiagnostics(sup: ServiceSupervisor): Promise<string> {
  const st = sup.status()
  const ram = ramInfo()
  const rt = readRuntime()
  const elevated = await isElevated().catch(() => false)
  let free = 'unknown'
  try {
    free = formatBytes(await freeDiskBytes(userDataRoot()))
  } catch {
    /* ignore */
  }

  const lines: string[] = []
  const add = (s = '') => lines.push(s)

  add('=== Dhara diagnostics ===')
  add(`Generated: ${new Date().toISOString()}`)
  add(`App version: ${app.getVersion()}  (Electron ${process.versions.electron}, Node ${process.versions.node})`)
  add(`OS: ${os.type()} ${os.release()} (${os.version()}) ${os.arch()}`)
  add(`Elevated (admin): ${elevated ? 'YES — Postgres will not start' : 'no'}`)
  add(
    `RAM: total ${ram.totalGiB.toFixed(1)} GB, available ${ram.availableMiB} MB, profile ${ram.profile}` +
      (ram.below8GB ? ' (below recommended 8 GB)' : ''),
  )
  add(`Free disk (data volume): ${free}`)
  add()
  add('--- Services ---')
  add(`State: ${st.state}`)
  add(`Ports: postgres=${st.ports?.postgres ?? 'n/a'} api=${st.ports?.api ?? 'n/a'}`)
  add(`PIDs: postgres=${st.pids.postgres ?? '-'} api=${st.pids.api ?? '-'} worker=${st.pids.worker ?? '-'}`)
  add(`Worker restarts (last 10 min): ${st.workerRestarts}`)
  add(`Last error: ${st.lastError ?? 'none'}`)
  add(`postmaster.pid present: ${fs.existsSync(files.postmasterPid()) ? 'yes' : 'no'}`)
  add(`pgdata exists: ${fs.existsSync(dirs.pgdata()) ? 'yes' : 'no'}`)
  add()
  add('--- Data / upgrade ---')
  add(`Schema version applied: ${rt.dataSchemaVersion ?? 'unknown'}`)
  add(
    `Last migrate: ${rt.lastMigrateOk === undefined ? 'n/a' : rt.lastMigrateOk ? 'ok' : 'FAILED'}` +
      (rt.lastMigrateAt ? ` at ${rt.lastMigrateAt}` : '') +
      (rt.lastMigrateAppVersion ? ` (app ${rt.lastMigrateAppVersion})` : ''),
  )
  if (rt.lastMigrateError) add(`Last migrate error: ${rt.lastMigrateError.slice(-300)}`)
  if (rt.lastBackup) {
    add(
      `Latest backup: ${rt.lastBackup.kind} → ${rt.lastBackup.path} (${rt.lastBackup.at}, ` +
        `free disk then: ${formatBytes(rt.lastBackup.freeBytesAtBackup)})`,
    )
  } else {
    add('Latest backup: none')
  }
  add(`pgvector available: ${rt.pgvectorAvailable === undefined ? 'unknown' : rt.pgvectorAvailable}`)
  add(`Keep services running on quit: ${rt.keepRunningOnQuit ? 'yes' : 'no'}`)
  add(`Settings file present (runtime.json): ${fs.existsSync(files.runtimeJson()) ? 'yes' : 'no'}`)
  add()
  add('--- NCO embeddings ---')
  const ncoDir = ncoEmbeddingModelDir()
  add(`Model folder present: ${ncoDir ? 'yes' : 'no'}`)
  if (ncoDir) add(`Model folder: ${ncoDir}`)
  add(`HF_HUB_OFFLINE / TRANSFORMERS_OFFLINE: enforced on desktop (1)`)
  add(
    `Prebuilt index: ${
      ncoDir && fs.existsSync(path.join(ncoDir, 'nco_index.npz')) ? 'yes' : 'no'
    }`,
  )
  add('Retrieval mode: see last Suggest NCO response (semantic | keyword-only)')
  add()
  add('--- Recent warnings/errors (desktop.log) ---')
  const problems = log.recentProblems(40)
  if (problems.length) lines.push(...problems)
  else add('(none)')
  add()
  add(`Logs folder: ${dirs.logs()}`)
  return lines.join('\n')
}
