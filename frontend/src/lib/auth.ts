// Login token + identity, persisted in localStorage so a reload stays
// signed in. Every backend API call must carry this token -- the backend
// stores KYDS entries / datasets / metadata groups under whichever email
// the token verifies to, never a client-supplied value.
const TOKEN_KEY = 'dhara.authToken'
const USER_KEY = 'dhara.authUser'

export type StoredUser = { name: string; email: string; dept: string; role: string }

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

export function setSession(token: string, user: StoredUser) {
  try {
    localStorage.setItem(TOKEN_KEY, token)
    localStorage.setItem(USER_KEY, JSON.stringify(user))
  } catch {
    // ignore (e.g. localStorage disabled)
  }
}

export function clearSession() {
  try {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  } catch {
    // ignore
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
  const res = await fetch('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || 'Sign in failed')
  }
  return data // { token, email, name, dept }
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
  return data // { token, email, name, dept }
}
