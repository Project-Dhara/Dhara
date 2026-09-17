const CONSOLE_RETURN_PATH_KEY = 'dhara_console_return_path'

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

export function clearConsoleSession() {
  try {
    sessionStorage.removeItem('dhara_console_state_v1')
  } catch {
    // best-effort
  }
  clearConsoleReturnPath()
  clearAllPdfPipelineState()
}

/** Leave a PDF (or finished) job and open a fresh Files screen. */
export function goToConsoleFiles(router: { push: (href: string) => void }) {
  clearConsoleSession()
  rememberConsoleReturnPath('/console')
  router.push('/console')
}
