import { resetMineKyds } from './kydsFilled'

const CONSOLE_RETURN_PATH_KEY = 'dhara_console_return_path'
const APPEND_FILES_KEY = 'dhara_console_append_files_v1'

/** Full-page table editors — never treat these as the Console landing target. */
function isConsoleEditorPath(pathname: string) {
  return pathname.includes('/edit/')
}

/**
 * Keep the latest Console location so AppShell → Console restores the same
 * place (Excel/SQL `/console` step flow, or a PDF processing/review/grouping
 * deep link). Visiting `/console` itself must overwrite any older PDF job
 * path — otherwise sidebar return jumps back to a stale preview.
 */
export function rememberConsoleReturnPath(pathname: string) {
  try {
    if (!pathname.startsWith('/console')) return
    if (isConsoleEditorPath(pathname)) return
    sessionStorage.setItem(CONSOLE_RETURN_PATH_KEY, pathname)
  } catch {
    // best-effort
  }
}

export function getConsoleReturnPath(): string | null {
  try {
    const path = sessionStorage.getItem(CONSOLE_RETURN_PATH_KEY)
    if (!path || !path.startsWith('/console')) return null
    if (isConsoleEditorPath(path)) return '/console'
    return path
  } catch {
    return null
  }
}

export function clearConsoleReturnPath() {
  try {
    sessionStorage.removeItem(CONSOLE_RETURN_PATH_KEY)
  } catch {
    // best-effort
  }
}

/** Clear every PDF pipeline snapshot (one key per jobId). */
export function clearAllPdfPipelineState() {
  try {
    const keys: string[] = []
    for (let i = 0; i < sessionStorage.length; i += 1) {
      const key = sessionStorage.key(i)
      if (key && key.startsWith('dhara_pdf_pipeline_v1_')) keys.push(key)
    }
    keys.forEach((key) => sessionStorage.removeItem(key))
  } catch {
    // best-effort
  }
}

export type AppendFilesMode = {
  jobId: string
  existingFilenames: string[]
  returnPath?: string | null
}

export function clearAppendFilesMode() {
  try {
    sessionStorage.removeItem(APPEND_FILES_KEY)
  } catch {
    // best-effort
  }
}

export function clearConsoleSession() {
  try {
    sessionStorage.removeItem('dhara_console_state_v1')
  } catch {
    // best-effort
  }
  clearConsoleReturnPath()
  clearAllPdfPipelineState()
  clearAppendFilesMode()
}

/** Leave a PDF (or finished) job and open a fresh Files screen. */
export function goToConsoleFiles(router: { push: (href: string) => void }) {
  clearConsoleSession()
  // Drop any prior upload's KYDS so Preview/Files don't show a stale dataset name.
  void resetMineKyds()
  rememberConsoleReturnPath('/console')
  router.push('/console')
}

/** Drop cached grouping so new tables are picked up after an append extract. */
function invalidatePdfGroupingCache(jobId: string) {
  try {
    const key = `dhara_pdf_pipeline_v1_${jobId}`
    const raw = sessionStorage.getItem(key)
    if (!raw) return
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return
    delete parsed.matchResult
    delete parsed.autoSnapshot
    parsed.manualGrouping = false
    sessionStorage.setItem(key, JSON.stringify(parsed))
  } catch {
    // best-effort
  }
}

/** Keep the current job and open Files in "add more" mode (no session wipe). */
export function beginAppendFilesMode(
  router: { push: (href: string) => void },
  opts: AppendFilesMode,
) {
  try {
    sessionStorage.setItem(APPEND_FILES_KEY, JSON.stringify({
      jobId: opts.jobId,
      existingFilenames: sanitizeExistingFilenames(opts.existingFilenames || []),
      returnPath: opts.returnPath || null,
    }))
  } catch {
    // best-effort
  }
  if (opts.jobId) invalidatePdfGroupingCache(opts.jobId)
  // Clear Excel/SQL console snapshot so Files opens at step 1; keep PDF pipeline.
  try {
    sessionStorage.removeItem('dhara_console_state_v1')
  } catch {
    // best-effort
  }
  rememberConsoleReturnPath('/console')
  router.push('/console')
}

function sanitizeExistingFilenames(list: unknown): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  for (const raw of Array.isArray(list) ? list : []) {
    const s = String(raw || '').trim()
    if (!s) continue
    // Drop batch summary labels left over from earlier appends.
    if (/^\d+\s+files?$/i.test(s)) continue
    if (/;\s*\+/.test(s) || (s.includes(';') && /\+\S/.test(s))) continue
    if (seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

export function getAppendFilesMode(): AppendFilesMode | null {
  try {
    const raw = sessionStorage.getItem(APPEND_FILES_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.jobId) return null
    return {
      jobId: String(parsed.jobId),
      existingFilenames: sanitizeExistingFilenames(parsed.existingFilenames),
      returnPath: parsed.returnPath ? String(parsed.returnPath) : null,
    }
  } catch {
    return null
  }
}

/** Highest stage reached for a PDF job (session). Defaults to Preview (2). */
export function pdfPipelineMaxStepReached(jobId: string | null | undefined): number {
  if (!jobId) return 0
  try {
    const raw = sessionStorage.getItem(`dhara_pdf_pipeline_v1_${jobId}`)
    if (raw) {
      const parsed = JSON.parse(raw)
      const n = Number(parsed?.maxStepReached)
      if (Number.isFinite(n) && n >= 1) return n
    }
  } catch {
    // best-effort
  }
  // Append mode is entered from review/grouping — Preview is always valid.
  return 2
}

/**
 * Leave "add more files" and open a PDF pipeline stage for the same job.
 * Stage 2 → review; 3+ → grouping (later steps live on that page).
 */
export function leaveAppendFilesToPdfStep(
  router: { push: (href: string) => void },
  opts: { jobId: string; targetStep?: number; returnPath?: string | null },
) {
  clearAppendFilesMode()
  const jobId = opts.jobId
  const target = opts.targetStep
  if (target == null || target <= 1) {
    router.push(opts.returnPath || `/console/review/${jobId}`)
    return
  }
  if (target === 2) {
    router.push(`/console/review/${jobId}`)
    return
  }
  router.push(`/console/grouping/${jobId}`)
}
