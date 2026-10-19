import { withAuthHeaders } from './auth'

// Placeholders stewards sometimes leave instead of a real answer.
const EMPTY_KYDS_PLACEHOLDERS = new Set(['-', '—', '–', 'n/a', 'na', 'none', 'null', 'undefined'])

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

/** Fetch the caller's latest KYDS entry and report whether it is filled. */
export async function fetchMineKydsFilled() {
  try {
    const res = await fetch('/api/kyds/mine', withAuthHeaders())
    if (!res.ok) return false
    const data = await res.json()
    return isKydsFilled(data.entry?.responses)
  } catch {
    return false
  }
}
