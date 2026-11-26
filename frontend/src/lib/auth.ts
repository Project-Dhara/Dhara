// Login token + identity. On desktop, persist via Electron safeStorage so a
// port fallback does not log the user out (localStorage is origin-scoped).
// Web/Docker keep localStorage. Backend JWT remains the real auth check.

const TOKEN_KEY = 'dhara.authToken'
const USER_KEY = 'dhara.authUser'

export type StoredUser = { name: string; email: string; dept: string; role: string }

type DesktopAuthApi = {
  getAuth?: () => Promise<{ token?: string; user?: StoredUser } | null>
  setAuth?: (payload: { token: string; user: StoredUser }) => Promise<void>
  clearAuth?: () => Promise<void>
}

function desktopAuth(): DesktopAuthApi | null {
  try {
    const api = (window as unknown as { dharaDesktop?: DesktopAuthApi }).dharaDesktop
    return api || null
  } catch {
    return null
  }
}

// name@organization.domain
export const EMAIL_RE = /^[^\s@]+@[^\s@.]+(\.[^\s@.]+)+$/

export function isValidOrgEmail(email: string) {
  return EMAIL_RE.test((email || '').trim())
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function getStoredUser(): StoredUser | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

/** Hydrate localStorage from Electron storage (call once at app boot on desktop). */
export async function hydrateAuthFromDesktop(): Promise<void> {
  const api = desktopAuth()
  if (!api?.getAuth) return
  try {
    const stored = await api.getAuth()
    if (stored?.token && stored?.user) {
      localStorage.setItem(TOKEN_KEY, stored.token)
      localStorage.setItem(USER_KEY, JSON.stringify(stored.user))
    }
  } catch {
    // ignore
  }
}

export function setSession(token: string, user: StoredUser) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    // ignore (e.g. localStorage disabled)
  }
  const api = desktopAuth()
  if (api?.setAuth) {
    void api.setAuth({ token, user }).catch(() => {})
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  } catch {
    // ignore
  }
  const api = desktopAuth()
  if (api?.clearAuth) {
    void api.clearAuth().catch(() => {})
  }
}

// Merge the bearer token into a fetch() init object's headers.
export function withAuthHeaders(init: RequestInit = {}): RequestInit {
  const token = getToken()
  if (!token) return init
  return { ...init, headers: { ...(init.headers || {}), Authorization: `Bearer ${token}` } }
}

// POST /api/login. Throws with a human-readable message on failure.
export async function login(email: string, password: string) {
  let res: Response
  try {
    res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
      signal: AbortSignal.timeout(20_000),
    })
  } catch {
    throw new Error('The server is not responding. Wait a moment and try again.')
  }
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || 'Sign in failed')
  }
  return data // { token, email, name, dept, role, user_id, organisation_id }
}

// POST /api/signup (dev only -- see backend ENABLE_SIGNUP). Throws with a
// human-readable message on failure.
export async function signup(email: string, password: string, name: string, dept: string) {
  const res = await fetch('/api/signup', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, name, dept }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || 'Sign up failed')
  }
  return data // { token, email, name, dept, role, user_id, organisation_id }
}
