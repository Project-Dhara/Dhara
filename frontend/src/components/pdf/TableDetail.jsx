'use client'

import { useEffect, useRef, useState } from 'react'
import { Check, Pencil } from 'lucide-react'
import Button from '../ui/Button'
import { isGarbled } from '../../lib/garbled'
import {
  adjustMergesAfterRowDelete,
  adjustMergesAfterRowInsert,
  applyNameToColumnMeta,
  cloneColumns,
  cloneEditorStructure,
  closeEditorWindow,
  columnDraftFromTable,
  columnHeaderPath,
  columnParentPath,
  displayTitle,
  invertActionFlash,
  isNumericColumn,
  materializeCellMerges,
  mergesFromSpans,
  movedBlockFlash,
  notifyTableEdited,
  padRowsToColumns,
  promoteMergeValuesBeforeRowDelete,
  reorderColumnRange,
  reorderRowRange,
  reshapeRows,
  resolveEditorBodySpans,
  setHeaderPathLevel,
  titleForEdit,
  unmergeAt,
  withParentPath,
} from '../../lib/pdfReviewHelpers'
import { ExtractedDataCell, ExtractedTableHead } from './ExtractedTableGrid'
import { ReferenceComparePanel } from './PdfReferenceViewer'
import { TableEditModal } from './TableEditModal'

/** Table title on the collapsed preview card (edit in the expanded detail). */
export function TableTitleDisplay({ table, className = '' }) {
  const title = displayTitle(table)
  if (title) {
    return (
      <div className={`min-w-0 truncate text-[14px] font-semibold leading-snug text-ink ${className}`}>
        {title}
      </div>
    )
  }
  return (
    <div className={`min-w-0 truncate text-[14px] font-semibold italic leading-snug text-ink-soft ${className}`}>
      No title — review
    </div>
  )
}

// Extracted-data preview + full-page structure editor. Numeric columns
// (integer / decimal / percentage) stay read-only in the grid; rename /
// reorder / add / delete / merge are edited with PDF + original snapshots.
export function TableDetail({
  table,
  jobId,
  onSave,
  onTitleLive,
  onTitleCommit,
  editorOnly = false,
  editorCloseHref = null,
  editorFooterHint = null,
}) {
  const [originalSnapshot] = useState(() => ({
    columns: cloneColumns(table.columns || []),
    rows: padRowsToColumns(table.rows || [], (table.columns || []).length),
  }))

  const [draft, setDraft] = useState(() => ({
    title: titleForEdit(table),
    columns: columnDraftFromTable(table.columns || []),
    rows: padRowsToColumns(table.rows || [], (table.columns || []).length),
    cellMerges: Array.isArray(table.cell_merges) ? table.cell_merges.map((m) => ({ ...m })) : [],
    mergesExplicit: Boolean(table.cell_merges_explicit)
      || (Array.isArray(table.cell_merges) && table.cell_merges.length > 0),
  }))
  const [saved, setSaved] = useState(false)
  const [savingEditor, setSavingEditor] = useState(false)
  // Full undo/redo history of editor structure changes (+ last-action red/green flash)
  const [actionFlash, setActionFlash] = useState(null)
  const [undoStack, setUndoStack] = useState([]) // [{ structure, flash }, ...] oldest → newest
  const [redoStack, setRedoStack] = useState([])
  const draftRef = useRef(draft)
  const actionFlashRef = useRef(null)
  const undoStackRef = useRef([])
  const redoStackRef = useRef([])
  draftRef.current = draft
  actionFlashRef.current = actionFlash
  undoStackRef.current = undoStack
  redoStackRef.current = redoStack

  const columnCount = (draft.columns || []).length
  const displayColumns = draft.columns

  useEffect(() => {
    setDraft((prev) => ({ ...prev, title: titleForEdit(table) }))
  }, [table.title])

  // Keep local draft in sync when the table is updated from the full-page editor tab.
  useEffect(() => {
    if (editorOnly) return undefined
    setDraft((prev) => ({
      ...prev,
      columns: columnDraftFromTable(table.columns || []),
      rows: padRowsToColumns(table.rows || [], (table.columns || []).length),
      cellMerges: Array.isArray(table.cell_merges) ? table.cell_merges.map((m) => ({ ...m })) : [],
      mergesExplicit: Boolean(table.cell_merges_explicit)
        || (Array.isArray(table.cell_merges) && table.cell_merges.length > 0),
    }))
  }, [editorOnly, table.table_id, table.columns, table.rows, table.cell_merges, table.cell_merges_explicit])

  const openFullPageEditor = () => {
    const url = `/console/review/${encodeURIComponent(jobId)}/edit/${encodeURIComponent(table.table_id)}`
    // Keep opener so the tab can close itself after Save & close.
    window.open(url, '_blank')
  }

  const markDirty = () => setSaved(false)

  const HISTORY_LIMIT = 100

  const applyEditorChange = (updater, flash = null) => {
    markDirty()
    const prev = draftRef.current
    const next = typeof updater === 'function' ? updater(prev) : updater
    if (next === prev) return
    const nextUndo = [
      ...undoStackRef.current,
      { structure: cloneEditorStructure(prev), flash },
    ].slice(-HISTORY_LIMIT)
    undoStackRef.current = nextUndo
    redoStackRef.current = []
    setUndoStack(nextUndo)
    setRedoStack([])
    draftRef.current = next
    setDraft(next)
    actionFlashRef.current = flash
    setActionFlash(flash)
  }

  const undoEditorChange = () => {
    const stack = undoStackRef.current
    if (!stack.length) return
    markDirty()
    const entry = stack[stack.length - 1]
    const current = draftRef.current
    const restored = {
      ...current,
      columns: entry.structure.columns,
      rows: entry.structure.rows,
      cellMerges: entry.structure.cellMerges,
      mergesExplicit: Boolean(entry.structure.mergesExplicit),
    }
    const undoneFlash = actionFlashRef.current
    const nextUndo = stack.slice(0, -1)
    const nextRedo = [
      ...redoStackRef.current,
      { structure: cloneEditorStructure(current), flash: undoneFlash },
    ].slice(-HISTORY_LIMIT)
    undoStackRef.current = nextUndo
    redoStackRef.current = nextRedo
    setUndoStack(nextUndo)
    setRedoStack(nextRedo)
    draftRef.current = restored
    setDraft(restored)
    const nextFlash = invertActionFlash(undoneFlash) || invertActionFlash(entry.flash)
    actionFlashRef.current = nextFlash
    setActionFlash(nextFlash)
  }

  const redoEditorChange = () => {
    const stack = redoStackRef.current
    if (!stack.length) return
    markDirty()
    const entry = stack[stack.length - 1]
    const current = draftRef.current
    const restored = {
      ...current,
      columns: entry.structure.columns,
      rows: entry.structure.rows,
      cellMerges: entry.structure.cellMerges,
      mergesExplicit: Boolean(entry.structure.mergesExplicit),
    }
    const nextRedo = stack.slice(0, -1)
    const nextUndo = [
      ...undoStackRef.current,
      { structure: cloneEditorStructure(current), flash: entry.flash },
    ].slice(-HISTORY_LIMIT)
    undoStackRef.current = nextUndo
    redoStackRef.current = nextRedo
    setUndoStack(nextUndo)
    setRedoStack(nextRedo)
    draftRef.current = restored
    setDraft(restored)
    actionFlashRef.current = entry.flash
    setActionFlash(entry.flash)
  }

  const setCell = (rowIdx, colIdx, value) => {
    markDirty()
    setDraft((prev) => {
      const ncols = prev.columns.length
      return {
      ...prev,
      rows: prev.rows.map((row, r) => {
        if (r !== rowIdx) return row
          const next = padRowsToColumns([row], ncols)[0]
        next[colIdx] = value
        return next
      }),
      }
    })
  }

  const renameColumn = (idx, name) => {
    markDirty()
    setDraft((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => (i === idx ? applyNameToColumnMeta(c, name) : c)),
    }))
  }
  const changeGroup = (idx, group) => {
    applyEditorChange((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => {
        if (i !== idx) return c
        const header_group = group || null
        const leaf = c.name || columnHeaderPath(c).slice(-1)[0] || 'Column'
        const header_path = header_group ? [header_group, leaf] : [leaf]
        return { ...c, header_group, header_path }
      }),
    }), { axis: 'cols', from: null, to: { start: idx, end: idx } })
  }
  const joinNeighborGroup = (idx, dir) => {
    applyEditorChange((prev) => {
      const n = idx + dir
      if (n < 0 || n >= prev.columns.length) return prev
      const parents = columnParentPath(prev.columns[n])
      if (!parents.length) return prev
      return {
        ...prev,
        columns: prev.columns.map((c, i) => {
          if (i !== idx) return c
          const leaf = c.name || columnHeaderPath(c).slice(-1)[0] || 'Column'
          const header_path = [...parents, leaf]
          return {
            ...c,
            header_path,
            header_group: parents[parents.length - 1] || null,
          }
        }),
      }
    }, { axis: 'cols', from: { start: idx + dir, end: idx + dir }, to: { start: idx, end: idx } })
  }
  const applyHeaderPathLevel = (start, colSpan, levelIdx, label) => {
    markDirty()
    setDraft((prev) => ({
      ...prev,
      columns: setHeaderPathLevel(prev.columns, start, colSpan, levelIdx, label),
    }))
  }
  const mergeCells = (rect) => {
    const { r0, r1, c0, c1 } = rect
    applyEditorChange((prev) => {
      const rowSpan = r1 - r0 + 1
      const colSpan = c1 - c0 + 1
      if (rowSpan <= 1 && colSpan <= 1) return prev
      // First manual merge: lock in any auto-inferred spans so they don't disappear.
      let nextMerges = prev.mergesExplicit || (prev.cellMerges || []).length > 0
        ? (prev.cellMerges || []).map((m) => ({ ...m }))
        : mergesFromSpans(resolveEditorBodySpans(prev.rows, prev.columns, prev.cellMerges, false))
      nextMerges = nextMerges.filter((m) => {
        const mrs = Math.max(1, Number(m.rowSpan) || 1)
        const mcs = Math.max(1, Number(m.colSpan) || 1)
        const overlap = !(m.r + mrs - 1 < r0 || m.r > r1 || m.c + mcs - 1 < c0 || m.c > c1)
        return !overlap
      })
      nextMerges.push({ r: r0, c: c0, rowSpan, colSpan })
      const rows = prev.rows.map((row, r) => {
        if (r < r0 || r > r1) return row
        const next = [...row]
        for (let c = c0; c <= c1; c += 1) {
          if (r === r0 && c === c0) continue
          next[c] = null
        }
        return next
      })
      return { ...prev, rows, cellMerges: nextMerges, mergesExplicit: true }
    }, {
      axis: 'cells',
      from: { r0, r1, c0, c1 },
      to: { r0, r1, c0, c1 },
    })
  }
  const unmergeCells = (r, c) => {
    const preview = unmergeAt(
      draftRef.current.rows,
      draftRef.current.columns,
      draftRef.current.cellMerges,
      draftRef.current.mergesExplicit,
      r,
      c,
    )
    if (!preview) return
    applyEditorChange((prev) => {
      const result = unmergeAt(prev.rows, prev.columns, prev.cellMerges, prev.mergesExplicit, r, c)
      if (!result) return prev
      return {
        ...prev,
        cellMerges: result.cellMerges,
        mergesExplicit: result.mergesExplicit,
      }
    }, preview.flash)
  }
  const moveColumn = (from, to) => {
    if (to < 0 || to >= columnCount || from === to) return
    const insertAt = to > from ? to + 1 : to
    applyEditorChange((prev) => {
      const next = reorderColumnRange(prev.columns, prev.rows, prev.cellMerges, from, 1, insertAt)
      if (next.columns === prev.columns) return prev
      return { ...prev, ...next }
    }, movedBlockFlash('cols', from, 1, insertAt))
  }
  const moveColumnRange = (from, count, insertAt) => {
    if (count < 1) return
    applyEditorChange((prev) => {
      const next = reorderColumnRange(prev.columns, prev.rows, prev.cellMerges, from, count, insertAt)
      if (next.columns === prev.columns) return prev
      return { ...prev, ...next }
    }, movedBlockFlash('cols', from, count, insertAt))
  }
  const mergeHeaderGroups = (start, end, label) => {
    const text = String(label || '').trim() || 'Group'
    applyEditorChange((prev) => ({
      ...prev,
      columns: prev.columns.map((c, i) => {
        if (i < start || i > end) return c
        return withParentPath(c, [text])
      }),
    }), { axis: 'cols', from: null, to: { start, end } })
  }
  const deleteHeaderGroup = (start, colSpan, levelIdx) => {
    applyEditorChange((prev) => {
      const end = start + Math.max(1, colSpan) - 1
      const depth = Math.max(1, ...prev.columns.map((c) => columnHeaderPath(c).length))
      return {
        ...prev,
        columns: prev.columns.map((col, i) => {
          if (i < start || i > end) return col
          const current = columnHeaderPath(col)
          const leaf = current[current.length - 1] || col.name || `Column ${i + 1}`
          const padded = Array.from({ length: depth }, () => '')
          const offset = Math.max(0, depth - current.length)
          current.forEach((p, j) => { padded[offset + j] = p })
          const idx = Math.min(levelIdx, depth - 2)
          if (idx < 0) return withParentPath(col, [])
          padded[idx] = ''
          let startIdx = 0
          while (startIdx < depth - 1 && !String(padded[startIdx] || '').trim()) startIdx += 1
          const path = padded.slice(startIdx).map((p, pi, arr) => {
            const s = String(p || '').trim()
            if (s) return s
            return pi === arr.length - 1 ? leaf : null
          }).filter((p) => p != null)
          const parents = path.slice(0, -1)
          return withParentPath({ ...col, name: path[path.length - 1] || leaf }, parents)
        }),
      }
    }, { axis: 'cols', from: { start, end: start + Math.max(1, colSpan) - 1 }, to: null })
  }
  const addHeaderGroup = (start, end, label) => {
    const text = String(label || '').trim() || 'New group'
    applyEditorChange((prev) => {
      if (start >= prev.columns.length || end < start) {
        const name = `Column ${prev.columns.length + 1}`
        const newCol = {
          name,
          header_group: text,
          header_path: [text, name],
          role: 'unknown',
          concept: '',
          description: '',
          data_type: 'unknown',
          human_review_needed: false,
          human_review_reason: null,
        }
        const cols = [...prev.columns, newCol]
        const order = prev.columns.map((_, i) => i)
        order.push(null)
        return {
          ...prev,
          columns: cols,
          rows: reshapeRows(prev.rows, order),
        }
      }
      return {
        ...prev,
        columns: prev.columns.map((c, i) => {
          if (i < start || i > end) return c
          return withParentPath(c, [text])
        }),
      }
    }, {
      axis: 'cols',
      from: null,
      to: start >= (draftRef.current.columns?.length || 0) || end < start
        ? { start: draftRef.current.columns?.length || 0, end: draftRef.current.columns?.length || 0 }
        : { start, end },
    })
  }
  const deleteColumns = (start, end) => {
    applyEditorChange((prev) => {
      const lo = Math.min(start, end)
      const hi = Math.max(start, end)
      if (hi - lo + 1 >= prev.columns.length) return prev
      const cols = prev.columns.filter((_, i) => i < lo || i > hi)
      const order = prev.columns.map((_, i) => i).filter((i) => i < lo || i > hi)
      const removed = hi - lo + 1
      const cellMerges = (prev.cellMerges || [])
        .map((m) => {
          const mEnd = m.c + Math.max(1, m.colSpan || 1) - 1
          if (mEnd < lo) return m
          if (m.c > hi) return { ...m, c: m.c - removed }
          return null
        })
        .filter(Boolean)
      return { ...prev, columns: cols, rows: reshapeRows(prev.rows, order), cellMerges }
    }, { axis: 'cols', from: { start: Math.min(start, end), end: Math.max(start, end) }, to: null })
  }
  const deleteColumn = (idx) => {
    deleteColumns(idx, idx)
  }
  const insertColumn = (atIdx, inheritFromIdx = null) => {
    applyEditorChange((prev) => {
      const idx = Math.max(0, Math.min(atIdx, prev.columns.length))
      const name = `Column ${prev.columns.length + 1}`
      let newCol = {
        name,
        header_group: null,
        header_path: [name],
        role: 'unknown',
        concept: '',
        description: '',
        data_type: 'unknown',
        human_review_needed: false,
        human_review_reason: null,
      }
      const inheritIdx = inheritFromIdx == null
        ? null
        : Math.max(0, Math.min(inheritFromIdx, prev.columns.length - 1))
      if (inheritIdx != null && prev.columns[inheritIdx]) {
        newCol = withParentPath(newCol, columnParentPath(prev.columns[inheritIdx]))
      }
      const cols = [...prev.columns]
      cols.splice(idx, 0, newCol)
      const order = []
      for (let i = 0; i < prev.columns.length; i++) {
        if (i === idx) order.push(null)
        order.push(i)
      }
      if (idx >= prev.columns.length) order.push(null)
      const cellMerges = (prev.cellMerges || []).map((m) => {
        if (m.c >= idx) return { ...m, c: m.c + 1 }
        const end = m.c + Math.max(1, m.colSpan || 1) - 1
        if (idx > m.c && idx <= end) return { ...m, colSpan: (m.colSpan || 1) + 1 }
        return m
      })
      return { ...prev, columns: cols, rows: reshapeRows(prev.rows, order), cellMerges }
    }, {
      axis: 'cols',
      from: null,
      to: { start: Math.max(0, Math.min(atIdx, draftRef.current.columns?.length || 0)), end: Math.max(0, Math.min(atIdx, draftRef.current.columns?.length || 0)) },
    })
  }
  const insertRow = (atIdx) => {
    applyEditorChange((prev) => {
      const idx = Math.max(0, Math.min(atIdx, prev.rows.length))
      const empty = Array.from({ length: prev.columns.length }, () => null)
      const merges = materializeCellMerges(prev.rows, prev.columns, prev.cellMerges, prev.mergesExplicit)
      const rows = [...prev.rows]
      rows.splice(idx, 0, empty)
      // Clear cells that fall inside an expanded vertical merge so rowspan stays clean.
      const cellMerges = adjustMergesAfterRowInsert(merges, idx)
      for (const m of cellMerges) {
        const rs = Math.max(1, Number(m.rowSpan) || 1)
        const cs = Math.max(1, Number(m.colSpan) || 1)
        if (!(idx > m.r && idx < m.r + rs)) continue
        const row = rows[idx]
        if (!row) continue
        for (let dc = 0; dc < cs; dc += 1) {
          const c = m.c + dc
          if (c >= 0 && c < row.length) row[c] = null
        }
      }
      return { ...prev, rows, cellMerges, mergesExplicit: true }
    }, {
      axis: 'rows',
      from: null,
      to: { start: Math.max(0, Math.min(atIdx, draftRef.current.rows?.length || 0)), end: Math.max(0, Math.min(atIdx, draftRef.current.rows?.length || 0)) },
    })
  }
  const deleteRow = (idx) => {
    applyEditorChange((prev) => {
      if (prev.rows.length <= 1) return prev
      const merges = materializeCellMerges(prev.rows, prev.columns, prev.cellMerges, prev.mergesExplicit)
      const promoted = promoteMergeValuesBeforeRowDelete(prev.rows, merges, idx)
      const rows = promoted.filter((_, i) => i !== idx)
      const cellMerges = adjustMergesAfterRowDelete(merges, idx)
      return { ...prev, rows, cellMerges, mergesExplicit: true }
    }, { axis: 'rows', from: { start: idx, end: idx }, to: null })
  }
  const moveRowRange = (from, count, insertAt) => {
    if (count < 1) return
    applyEditorChange((prev) => {
      const next = reorderRowRange(prev.rows, prev.cellMerges, from, count, insertAt)
      if (next.rows === prev.rows) return prev
      return { ...prev, ...next }
    }, movedBlockFlash('rows', from, count, insertAt))
  }

  const previewRows = draft.rows || []
  const previewCap = 5
  const previewLimit = Math.min(previewCap, previewRows.length)
  const visiblePreviewRows = previewRows.slice(0, previewLimit)
  // Card shows only the first rows; clip explicit merges so rowspan/colspan stay in-bounds.
  const previewMerges = draft.mergesExplicit || (draft.cellMerges || []).length > 0
    ? (draft.cellMerges || [])
      .map((m) => {
        const r = Number(m.r) || 0
        const c = Number(m.c) || 0
        if (r >= previewLimit) return null
        const rowSpan = Math.min(Math.max(1, Number(m.rowSpan) || 1), previewLimit - r)
        const colSpan = Math.max(1, Number(m.colSpan) || 1)
        if (rowSpan <= 1 && colSpan <= 1) return null
        return { r, c, rowSpan, colSpan }
      })
      .filter(Boolean)
    : []
  const previewCellSpans = resolveEditorBodySpans(
    visiblePreviewRows,
    displayColumns,
    previewMerges,
    Boolean(draft.mergesExplicit),
  )
  const hiddenCount = Math.max(0, previewRows.length - previewLimit)
  const garbledCellCount = (draft.rows || []).flat().filter((v) => isGarbled(v)).length
  const anyCellGarbled = garbledCellCount > 0
  const lockedCols = displayColumns.map((col, i) => isNumericColumn(col, i, previewRows))
  const sourceRowsAligned = padRowsToColumns(
    (originalSnapshot.rows || []).map((row) => row),
    columnCount,
  )

  const baselineCols = columnDraftFromTable(originalSnapshot.columns)
  const rowsDirty = JSON.stringify(draft.rows) !== JSON.stringify(
    padRowsToColumns(originalSnapshot.rows || [], baselineCols.length),
  )
  const colStructureSig = (cols) => JSON.stringify(
    (cols || []).map((c) => ({
      name: c.name || '',
      header_group: c.header_group || '',
      header_path: Array.isArray(c.header_path) ? c.header_path : null,
      role: c.role,
      concept: c.concept || '',
      description: c.description || '',
    })),
  )
  const colsDirty = colStructureSig(draft.columns) !== colStructureSig(baselineCols)
  // Also dirty vs currently saved table (after prior save in session).
  const vsTableColsDirty = colStructureSig(draft.columns) !== colStructureSig(table.columns || [])
  const vsTableRowsDirty = JSON.stringify(draft.rows) !== JSON.stringify(
    padRowsToColumns(table.rows || [], (table.columns || []).length),
  )
  const titleDirty = (draft.title || '').trim() !== titleForEdit(table)
  const structureDirty = colsDirty || vsTableColsDirty || rowsDirty || vsTableRowsDirty
    || JSON.stringify(draft.cellMerges || []) !== JSON.stringify(table.cell_merges || [])
    || Boolean(draft.mergesExplicit) !== Boolean(
      table.cell_merges_explicit || (Array.isArray(table.cell_merges) && table.cell_merges.length > 0)
    )
  const canSave = (table.human_review_needed || structureDirty || titleDirty) && !saved

  const handleSave = () => {
    const columns = draft.columns.map((c) => ({
      ...c,
      name: (c.name || '').trim() || 'Column',
      header_group: c.header_group || null,
      header_path: Array.isArray(c.header_path) && c.header_path.length
        ? c.header_path
        : (c.header_group ? [c.header_group, c.name] : [c.name]),
      human_review_needed: false,
      human_review_reason: null,
    }))
    const title = draft.title.trim() || null
    onSave({
      title,
      classification: table.classification || {},
      columns,
      rows: padRowsToColumns(draft.rows, columns.length),
      cell_merges: draft.cellMerges || [],
      cell_merges_explicit: Boolean(draft.mergesExplicit),
      human_review_needed: false,
      human_review_reason: null,
      bbox: table.bbox || null,
    })
    setSaved(true)
  }

  const buildEditorPayload = () => {
    const columns = draft.columns.map((c) => ({
      ...c,
      name: (c.name || '').trim() || 'Column',
      header_group: c.header_group || null,
      header_path: Array.isArray(c.header_path) && c.header_path.length
        ? c.header_path
        : (c.header_group ? [c.header_group, c.name] : [c.name]),
      human_review_needed: false,
      human_review_reason: null,
    }))
    return {
      title: (draft.title || '').trim() || table.title || null,
      columns,
      rows: padRowsToColumns(draft.rows, columns.length),
      cell_merges: draft.cellMerges || [],
      cell_merges_explicit: Boolean(draft.mergesExplicit),
      human_review_needed: false,
      human_review_reason: null,
      bbox: table.bbox || null,
      classification: table.classification || {},
    }
  }

  const persistEditorAndClose = async () => {
    const edits = buildEditorPayload()
    setSavingEditor(true)
    try {
      await onSave?.(edits)
      if (jobId) {
        notifyTableEdited(jobId, table.table_id, edits)
        closeEditorWindow(jobId)
      } else if (editorCloseHref) {
        try {
          window.close()
        } catch {
          /* ignore */
        }
        window.setTimeout(() => {
          if (!window.closed) window.location.assign(editorCloseHref)
        }, 150)
      } else {
        closeEditorWindow(jobId)
      }
    } catch (e) {
      window.alert(e?.message || 'Could not save table edits')
    } finally {
      setSavingEditor(false)
    }
  }

  const modalTable = { ...table, columns: displayColumns }
  const editorProps = {
    table: modalTable,
    jobId,
    rows: previewRows,
    columns: displayColumns,
    sourceRows: sourceRowsAligned,
    originalSnapshot,
    cellMerges: draft.cellMerges || [],
    mergesExplicit: Boolean(draft.mergesExplicit),
    onChangeCell: setCell,
    onRenameColumn: renameColumn,
    onChangeGroup: changeGroup,
    onJoinNeighborGroup: joinNeighborGroup,
    onSetHeaderPathLevel: applyHeaderPathLevel,
    onInsertColumn: insertColumn,
    onDeleteColumn: deleteColumn,
    onMoveColumn: moveColumn,
    onMoveColumnRange: moveColumnRange,
    onInsertRow: insertRow,
    onDeleteRow: deleteRow,
    onMoveRowRange: moveRowRange,
    onMergeCells: mergeCells,
    onUnmergeCells: unmergeCells,
    onAddHeaderGroup: addHeaderGroup,
    onMergeHeaderGroups: mergeHeaderGroups,
    onDeleteHeaderGroup: deleteHeaderGroup,
    onDeleteColumns: deleteColumns,
    actionFlash,
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    undoCount: undoStack.length,
    redoCount: redoStack.length,
    onUndo: undoEditorChange,
    onRedo: redoEditorChange,
  }

  if (editorOnly) {
  return (
      <TableEditModal
        {...editorProps}
        variant="page"
        doneLabel={savingEditor ? 'Saving…' : 'Save & close'}
        footerHint={
          editorFooterHint
          || (jobId
            ? 'Saves to the review job, then closes this tab. The review page updates automatically.'
            : 'Saves back to the preview page, then closes this tab.')
        }
        onClose={() => {
          if (jobId) closeEditorWindow(jobId)
          else if (editorCloseHref) {
            try { window.close() } catch { /* ignore */ }
            window.setTimeout(() => {
              if (!window.closed) window.location.assign(editorCloseHref)
            }, 150)
          } else {
            closeEditorWindow(jobId)
          }
        }}
        onDone={persistEditorAndClose}
      />
    )
  }

  return (
    <div className="flex flex-col gap-3 border-t border-line px-3.5 pb-3.5 pt-3">
      <label className="flex flex-col gap-1">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-teal">Table title</span>
        <input
          type="text"
          className="rounded-md border border-line bg-white px-2.5 py-1.5 text-[13.5px] font-semibold text-ink outline-none focus:border-teal"
          value={draft.title}
          placeholder="Add a table title"
          onChange={(e) => {
            const nextTitle = e.target.value
            markDirty()
            setDraft((prev) => ({ ...prev, title: nextTitle }))
            onTitleLive?.(nextTitle.trim() || null)
          }}
          onBlur={() => {
            onTitleCommit?.(draft.title.trim() || null)
          }}
        />
      </label>

      {table.description && <p className="text-[13px] text-ink-soft">{table.description}</p>}

      {jobId && table.table_id && (
        <ReferenceComparePanel
          jobId={jobId}
          tableId={table.table_id}
          originalSnapshot={originalSnapshot}
        />
      )}

      {table.uncertain_cells?.length > 0 && (
        <>
          <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">Extraction uncertainties</div>
          <ul className="list-disc pl-5 text-[13px] text-ink">
            {table.uncertain_cells.map((note, i) => <li key={i}>{note}</li>)}
          </ul>
        </>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="text-[11px] font-bold uppercase tracking-wide text-green">
          Extracted data ({previewRows.length} rows · {columnCount} columns
          {anyCellGarbled ? ` — ${garbledCellCount} cell(s) need review` : ''})
        </div>
        <Button type="button" variant="primary" size="sm" onClick={openFullPageEditor}>
          <Pencil className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden />
          View/Edit table
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[600px] table-fixed border-collapse text-[13px]">
          <ExtractedTableHead columns={displayColumns} lockedCols={lockedCols} />
          <tbody>
            {visiblePreviewRows.map((row, r) => (
              <tr key={r}>
                {Array.from({ length: columnCount }, (_, c) => {
                  const span = previewCellSpans[r]?.[c]
                  if (span == null) return null
                  const v = row[c] ?? null
                  const col = displayColumns[c]
                  const merged = span.rowSpan > 1 || span.colSpan > 1
                  return (
                    <td
                      key={c}
                      rowSpan={span.rowSpan > 1 ? span.rowSpan : undefined}
                      colSpan={span.colSpan > 1 ? span.colSpan : undefined}
                      className={`max-w-0 break-words [overflow-wrap:anywhere] border border-line px-2.5 py-1.5 align-top ${merged ? 'align-middle' : ''}`}
                    >
                      <ExtractedDataCell
                        value={v}
                        sourceValue={sourceRowsAligned[r]?.[c]}
                        col={col}
                        locked
                        fitWidth
                        onChange={() => {}}
                      />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
        {hiddenCount > 0 && (
          <div className="mt-2 text-center text-[12px] text-ink-soft">
            +{hiddenCount} more rows — open Edit table (new tab) to see and change all rows
          </div>
        )}
      </div>

      {canSave && (
        <Button variant="primary" className="self-start" onClick={handleSave}>
          {table.human_review_needed ? 'Save review & mark resolved' : 'Save changes'}
        </Button>
      )}
      {saved && (
        <div className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[#3d7a3d]">
          <Check className="h-4 w-4" strokeWidth={2.25} aria-hidden />
          Saved — changes kept for this table.
        </div>
      )}
    </div>
  )
}

