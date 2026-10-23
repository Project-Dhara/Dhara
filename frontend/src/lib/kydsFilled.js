import { withAuthHeaders } from './auth'
import { notifyKydsChanged } from './kydsEvents'

// Placeholders stewards sometimes leave instead of a real answer.
const EMPTY_KYDS_PLACEHOLDERS = new Set(['-', '—', '–', 'n/a', 'na', 'none', 'null', 'undefined'])

/** Set when the steward saves KYDS in this browser tab/session. */
const KYDS_SAVED_SESSION_KEY = 'dhara_kyds_saved_v1'

function isMeaningfulKydsValue(value) {
  if (Array.isArray(value)) return value.length > 0
  const text = String(value ?? '').trim()
  if (!text) return false
  return !EMPTY_KYDS_PLACEHOLDERS.has(text.toLowerCase())
}

/** True when at least one KYDS response has a real (non-placeholder) value. */
export function isKydsFilled(responses) {
  if (!responses || typeof responses !== 'object') return false
  return Object.values(responses).some(isMeaningfulKydsValue)
}

/** Whether KYDS was saved during this browser session (survives refresh, not tab close). */
export function wasKydsSavedThisSession() {
  try {
    return sessionStorage.getItem(KYDS_SAVED_SESSION_KEY) === '1'
  } catch {
    return false
  }
}

export function markKydsSavedThisSession() {
  try {
    sessionStorage.setItem(KYDS_SAVED_SESSION_KEY, '1')
  } catch {
    // best-effort
  }
}

export function clearKydsSavedThisSession() {
  try {
    sessionStorage.removeItem(KYDS_SAVED_SESSION_KEY)
  } catch {
    // best-effort
  }
}

/** Fetch the caller's latest KYDS entry and report whether it is filled for this session. */
export async function fetchMineKydsFilled() {
  if (!wasKydsSavedThisSession()) return false
  try {
    const res = await fetch('/api/kyds/mine', withAuthHeaders())
    if (!res.ok) return false
    const data = await res.json()
    return isKydsFilled(data.entry?.responses)
  } catch {
    return false
  }
}

/**
 * Start a clean KYDS slate for a new console/upload session.
 * POSTs an empty entry so /api/kyds/mine no longer returns a prior upload's values
 * (display + Stage 4 metadata fill both read the latest row).
 */
export async function resetMineKyds() {
  clearKydsSavedThisSession()
  try {
    const res = await fetch('/api/kyds', withAuthHeaders({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ responses: {} }),
    }))
    if (res.ok) notifyKydsChanged()
    return res.ok
  } catch {
    return false
  }
}
