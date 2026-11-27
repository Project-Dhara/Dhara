/** Classify/NCO draft across Settings detours (sessionStorage). */

export const CLASSIFY_DRAFT_KEY = 'dhara_classify_draft_v1'

function normIds(ids) {
  return (Array.isArray(ids) ? ids : [])
    .map((id) => String(id || '').trim())
    .filter(Boolean)
    .sort()
}

export function metadataIdsMatch(a, b) {
  const left = normIds(a)
  const right = normIds(b)
  if (left.length === 0 || right.length === 0) return false
  if (left.length !== right.length) return false
  return left.every((id, i) => id === right[i])
}

export function loadClassifyDraft() {
  try {
    const raw = sessionStorage.getItem(CLASSIFY_DRAFT_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    return parsed
  } catch {
    return null
  }
}

export function saveClassifyDraft(payload) {
  try {
    if (!payload || typeof payload !== 'object') return
    sessionStorage.setItem(CLASSIFY_DRAFT_KEY, JSON.stringify(payload))
  } catch {
    // best-effort
  }
}

export function clearClassifyDraft() {
  try {
    sessionStorage.removeItem(CLASSIFY_DRAFT_KEY)
  } catch {
    // best-effort
  }
}

/**
 * Overlay a matching draft onto server-applied state.
 * Returns null if draft missing or metadataIds do not match.
 */
export function overlayClassifyDraft(serverState, draft, metadataIds) {
  if (!draft || !metadataIdsMatch(draft.metadataIds, metadataIds)) return null
  return {
    selectedCol: draft.selectedCol ?? serverState.selectedCol,
    columnCodes: { ...(serverState.columnCodes || {}), ...(draft.columnCodes || {}) },
    ncoMatchesByCol: { ...(serverState.ncoMatchesByCol || {}), ...(draft.ncoMatchesByCol || {}) },
    lgdMatchesByCol: { ...(serverState.lgdMatchesByCol || {}), ...(draft.lgdMatchesByCol || {}) },
    harmRows: { ...(serverState.harmRows || {}), ...(draft.harmRows || {}) },
    harmDirty: { ...(serverState.harmDirty || {}), ...(draft.harmDirty || {}) },
    aliasVerified: { ...(serverState.aliasVerified || {}), ...(draft.aliasVerified || {}) },
    ruleState: { ...(serverState.ruleState || {}), ...(draft.ruleState || {}) },
    openRule: draft.openRule !== undefined ? draft.openRule : serverState.openRule,
  }
}
