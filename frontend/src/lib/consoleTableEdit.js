/**
 * Full-page table editor support for Excel / SQL console preview.
 * Reuses the PDF TableDetail / TableEditModal UI; tables live in session
 * storage (not a PDF job API).
 */
import { TABLE_EDIT_CHANNEL } from './pdfReviewHelpers'

export const CONSOLE_TABLE_EDIT_CHANNEL = 'dhara-console-table-edit'
export const CONSOLE_TABLE_DRAFT_PREFIX = 'dhara_console_table_edit_v1_'

export function consoleTableDraftKey(uid) {
  return `${CONSOLE_TABLE_DRAFT_PREFIX}${uid}`
}

/** Convert console (Excel/SQL) table → PDF editor shape. */
export function toEditorTable(table) {
  if (!table) return null
  const colNames = (table.columns || []).map((c) => (
    typeof c === 'string' ? c : String(c?.name || '').trim() || 'Column'
  ))
  const columns = colNames.map((name) => ({
    name,
    header_group: null,
    header_path: [name],
    role: 'unknown',
    concept: '',
    description: '',
    data_type: 'unknown',
    human_review_needed: false,
    human_review_reason: null,
  }))
  const rows = (table.rows || []).map((row) => {
    if (Array.isArray(row)) {
      const next = row.slice(0, colNames.length)
      while (next.length < colNames.length) next.push(null)
      return next
    }
    return colNames.map((name) => (row && Object.prototype.hasOwnProperty.call(row, name) ? row[name] : null))
  })
  return {
    ...table,
    table_id: table.table_id || table.id || table._uid,
    columns,
    rows,
    cell_merges: Array.isArray(table.cell_merges) ? table.cell_merges : [],
    cell_merges_explicit: Boolean(table.cell_merges_explicit),
  }
}

/** Map editor Save payload back onto a console table patch. */
export function applyEditorEditsToConsoleTable(table, edits) {
  const colNames = (edits?.columns || []).map((c) => {
    const name = typeof c === 'string' ? c : String(c?.name || '').trim()
    return name || 'Column'
  })
  const rows = (edits?.rows || []).map((row) => {
    const obj = {}
    colNames.forEach((name, i) => {
      obj[name] = Array.isArray(row) ? (row[i] ?? null) : (row?.[name] ?? null)
    })
    return obj
  })
  const patch = {
    columns: colNames,
    rows,
    row_count: rows.length,
  }
  if (edits?.title != null) {
    patch.title = edits.title
  }
  if (Array.isArray(edits?.cell_merges)) {
    patch.cell_merges = edits.cell_merges
    patch.cell_merges_explicit = Boolean(edits.cell_merges_explicit)
  }
  return { ...table, ...patch }
}

export function stashConsoleTableForEdit(table) {
  if (typeof window === 'undefined' || !table?._uid) return
  try {
    sessionStorage.setItem(consoleTableDraftKey(table._uid), JSON.stringify(table))
  } catch {
    /* storage full — editor page can still try console persist */
  }
}

export function loadStashedConsoleTable(uid) {
  if (typeof window === 'undefined' || !uid) return null
  try {
    const raw = sessionStorage.getItem(consoleTableDraftKey(uid))
    if (raw) return JSON.parse(raw)
  } catch {
    /* ignore */
  }
  return null
}

export function clearStashedConsoleTable(uid) {
  if (typeof window === 'undefined' || !uid) return
  try {
    sessionStorage.removeItem(consoleTableDraftKey(uid))
  } catch {
    /* ignore */
  }
}

export function openConsoleTableEditor(table) {
  if (!table?._uid || typeof window === 'undefined') return
  stashConsoleTableForEdit(table)
  const url = `/console/preview/edit/${encodeURIComponent(table._uid)}`
  window.open(url, '_blank')
}

export function notifyConsoleTableEdited(uid, edits) {
  const payload = { type: 'console-table-edited', uid, edits, t: Date.now() }
  try {
    const bc = new BroadcastChannel(CONSOLE_TABLE_EDIT_CHANNEL)
    bc.postMessage(payload)
    bc.close()
  } catch {
    /* BroadcastChannel unavailable */
  }
  try {
    localStorage.setItem(CONSOLE_TABLE_EDIT_CHANNEL, JSON.stringify(payload))
  } catch {
    /* ignore */
  }
}

export function closeConsoleEditorWindow() {
  if (typeof window === 'undefined') return
  try {
    window.close()
  } catch {
    /* ignore */
  }
  window.setTimeout(() => {
    if (!window.closed) {
      window.location.assign('/console')
    }
  }, 150)
}

/** Listen for editor-tab saves; returns unsubscribe. */
export function subscribeConsoleTableEdits(onEdit) {
  let bc
  try {
    bc = new BroadcastChannel(CONSOLE_TABLE_EDIT_CHANNEL)
    bc.onmessage = (ev) => {
      if (ev?.data?.type === 'console-table-edited') onEdit(ev.data)
    }
  } catch {
    bc = null
  }
  const onStorage = (ev) => {
    if (ev.key !== CONSOLE_TABLE_EDIT_CHANNEL || !ev.newValue) return
    try {
      const payload = JSON.parse(ev.newValue)
      if (payload?.type === 'console-table-edited') onEdit(payload)
    } catch {
      /* ignore */
    }
  }
  window.addEventListener('storage', onStorage)
  return () => {
    try { bc?.close() } catch { /* ignore */ }
    window.removeEventListener('storage', onStorage)
  }
}

// Re-export so callers can distinguish PDF vs console channels if needed.
export { TABLE_EDIT_CHANNEL }
