const CONSOLE_RETURN_PATH_KEY = 'dhara_console_return_path'

export function rememberConsoleReturnPath(pathname: string) {
  try {
    if (pathname.startsWith('/console/') && pathname !== '/console') {
      sessionStorage.setItem(CONSOLE_RETURN_PATH_KEY, pathname)
    }
  } catch {
    // best-effort
  }
}

export function getConsoleReturnPath(): string | null {
  try {
    return sessionStorage.getItem(CONSOLE_RETURN_PATH_KEY)
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
