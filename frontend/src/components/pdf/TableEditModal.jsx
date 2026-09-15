'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import {
  Columns2, Combine, Eye, GripVertical, Pencil, Plus, Redo2, Trash2, Undo2, X,
} from 'lucide-react'
import Button from '../ui/Button'
import {
  bindPaneWheelZoom,
  buildEditorHeaderRows,
  columnParentPath,
  displayTitle,
  findBodySpanOrigin,
  findMergeCovering,
  flashCovers,
  listExistingHeaderGroups,
  resolveEditorBodySpans,
  selectionRect,
} from '../../lib/pdfReviewHelpers'
import { AutoGrowTextarea, EditorToolBtn, ExtractedDataCell } from './ExtractedTableGrid'
import { EditorZoomControls, PdfTableSnapshot } from './PdfReferenceViewer'

/**
 * Full spreadsheet editor: edit cells/headers, resize columns,
 * drag-drop reorder, add/delete/merge groups and columns, merge/unmerge cells.
 * variant="modal" (default) portals a dialog; variant="page" fills the window.
 */
export function TableEditModal({
  table,
  jobId,
  rows,
  columns,
  sourceRows,
  originalSnapshot,
  cellMerges,
  mergesExplicit = false,
  variant = 'modal',
  onChangeCell,
  onRenameColumn,
  onChangeGroup,
  onJoinNeighborGroup,
  onSetHeaderPathLevel,
  onInsertColumn,
  onDeleteColumn,
  onMoveColumn,
  onMoveColumnRange,
  onInsertRow,
  onDeleteRow,
  onMoveRowRange,
  onMergeCells,
  onUnmergeCells,
  onAddHeaderGroup,
  onMergeHeaderGroups,
  onDeleteHeaderGroup,
  onDeleteColumns,
  actionFlash = null,
  canUndo = false,
  canRedo = false,
  undoCount = 0,
  redoCount = 0,
  onUndo,
  onRedo,
  onClose,
  onDone,
  doneLabel = 'Done editing',
  footerHint = 'Edits stay in this draft until you click Save on the table card.',
}) {
  const columnCount = (columns || []).length
  const [mounted, setMounted] = useState(false)
  const [colWidths, setColWidths] = useState(() => {
    const n = Math.max((columns || []).length, 1)
    return Array.from({ length: n }, () => Math.max(72, Math.floor(900 / n)))
  })
  const [sel, setSel] = useState(null)
  const [hdrSel, setHdrSel] = useState(null) // { start, end, levelIdx }
  const [dropHint, setDropHint] = useState(null) // { index, mode }
  const [comparePdf, setComparePdf] = useState(false)
  const [showCompareTip, setShowCompareTip] = useState(variant === 'page')
  const [interactionMode, setInteractionMode] = useState('edit') // 'edit' | 'view'
  const canEdit = interactionMode === 'edit'
  const [splitPct, setSplitPct] = useState(42)
  const [pdfZoom, setPdfZoom] = useState(1)
  const [tableZoom, setTableZoom] = useState(1)
  const resizeRef = useRef(null)
  const splitDragRef = useRef(null)
  const workspaceRef = useRef(null)
  const pdfPaneRef = useRef(null)
  const tablePaneRef = useRef(null)
  const dndRef = useRef(null)
  const headerMeta = buildEditorHeaderRows(columns)
  const existingGroups = listExistingHeaderGroups(columns)
  const bodySpans = resolveEditorBodySpans(rows, columns, cellMerges, mergesExplicit)
  const rect = selectionRect(sel)

  useEffect(() => {
    setColWidths((prev) => {
      const n = Math.max((columns || []).length, 1)
      if (prev.length === n) return prev
      if (prev.length < n) {
        return [...prev, ...Array.from({ length: n - prev.length }, () => 100)]
      }
      return prev.slice(0, n)
    })
  }, [columns?.length])

  useEffect(() => {
    setMounted(true)
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
      const mod = e.metaKey || e.ctrlKey
      if (!mod) return
      if (!canEdit) return
      const key = e.key.toLowerCase()
      if (key === 'z' && !e.shiftKey) {
        e.preventDefault()
        if (canUndo) onUndo?.()
        return
      }
      if (key === 'y' || (key === 'z' && e.shiftKey)) {
        e.preventDefault()
        if (canRedo) onRedo?.()
      }
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    if (variant === 'modal') document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      if (variant === 'modal') document.body.style.overflow = prev
    }
  }, [onClose, canUndo, canRedo, onUndo, onRedo, variant, canEdit])

  useEffect(() => {
    if (!showCompareTip) return undefined
    const t = window.setTimeout(() => setShowCompareTip(false), 8000)
    return () => window.clearTimeout(t)
  }, [showCompareTip])

  useEffect(() => {
    const onMove = (e) => {
      const d = resizeRef.current
      if (!d) return
      const dx = e.clientX - d.startX
      const next = Math.max(56, d.startW + dx)
      setColWidths((ws) => ws.map((w, i) => (i === d.idx ? next : w)))
    }
    const onUp = () => { resizeRef.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  useEffect(() => {
    const onMove = (e) => {
      const drag = splitDragRef.current
      if (!drag) return
      const el = workspaceRef.current
      if (!el) return
      const box = el.getBoundingClientRect()
      if (drag.axis === 'x') {
        const pct = ((e.clientX - box.left) / Math.max(1, box.width)) * 100
        setSplitPct(Math.min(75, Math.max(22, pct)))
      } else {
        const pct = ((e.clientY - box.top) / Math.max(1, box.height)) * 100
        setSplitPct(Math.min(70, Math.max(20, pct)))
      }
    }
    const onUp = () => {
      if (!splitDragRef.current) return
      splitDragRef.current = null
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
    }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])

  useEffect(() => {
    const cleanPdf = bindPaneWheelZoom(pdfPaneRef.current, setPdfZoom)
    const cleanTable = bindPaneWheelZoom(tablePaneRef.current, setTableZoom)
    return () => {
      cleanPdf()
      cleanTable()
    }
  }, [comparePdf, mounted])

  if (!mounted) return null

  const startResize = (idx, e) => {
    e.preventDefault()
    e.stopPropagation()
    resizeRef.current = { idx, startX: e.clientX, startW: colWidths[idx] || 100 }
  }

  const selectCell = (r, c, extend) => {
    setHdrSel(null)
    setSel((prev) => {
      if (extend && prev) return { ...prev, r1: r, c1: c }
      return { r0: r, c0: c, r1: r, c1: c }
    })
  }

  const selectHeaderRange = (start, end, levelIdx, extend) => {
    setSel(null)
    setHdrSel((prev) => {
      if (extend && prev) {
        return {
          start: Math.min(prev.start, start, end),
          end: Math.max(prev.end, start, end),
          levelIdx: prev.levelIdx,
        }
      }
      return { start, end, levelIdx }
    })
  }

  const canMerge = Boolean(rect && (rect.r1 > rect.r0 || rect.c1 > rect.c0))
  const spanAtSelection = rect ? findBodySpanOrigin(bodySpans, rect.r0, rect.c0) : null
  const canUnmerge = Boolean(
    rect
    && (
      findMergeCovering(cellMerges, rect.r0, rect.c0)
      || (
        spanAtSelection
        && ((spanAtSelection.span.rowSpan || 1) > 1 || (spanAtSelection.span.colSpan || 1) > 1)
      )
    )
  )
  const selectedColStart = hdrSel
    ? hdrSel.start
    : (rect ? Math.min(rect.c0, rect.c1) : null)
  const selectedColEnd = hdrSel
    ? hdrSel.end
    : (rect ? Math.max(rect.c0, rect.c1) : null)
  const hasColSelection = selectedColStart != null && selectedColEnd != null
  const canMergeGroups = hasColSelection && selectedColEnd > selectedColStart
  const canDeleteGroup = Boolean(hdrSel && hdrSel.levelIdx < headerMeta.depth - 1)
  const canDeleteColumns = hasColSelection && columnCount > 1
    && (selectedColEnd - selectedColStart + 1) < columnCount

  const clearDnd = () => {
    dndRef.current = null
    setDropHint(null)
  }

  const beginDrag = (kind, start, end, e) => {
    if (!canEdit) {
      e.preventDefault()
      return
    }
    dndRef.current = { kind, start, end }
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', `${kind}:${start}-${end}`)
    try {
      e.dataTransfer.setDragImage(e.currentTarget.closest('th') || e.currentTarget, 12, 12)
    } catch {
      /* ignore */
    }
  }

  const edgeForEvent = (e, el) => {
    const box = el.getBoundingClientRect()
    const x = e.clientX - box.left
    if (x < box.width * 0.28) return 'before'
    if (x > box.width * 0.72) return 'after'
    return 'into'
  }

  const onHeaderDragOver = (e, start, end, isGroup) => {
    e.preventDefault()
    if (dndRef.current?.kind === 'row') return
    e.dataTransfer.dropEffect = 'move'
    const src = dndRef.current
    if (!src || (src.kind !== 'column' && src.kind !== 'group')) return
    const mode = isGroup ? edgeForEvent(e, e.currentTarget) : (
      e.clientX - e.currentTarget.getBoundingClientRect().left
        < e.currentTarget.getBoundingClientRect().width / 2 ? 'before' : 'after'
    )
    if (src.start === start && src.end === end && mode === 'into') {
      setDropHint(null)
      return
    }
    setDropHint({ type: 'col', index: start, end, mode, isGroup: Boolean(isGroup) })
  }

  const onRowDragOver = (e, r) => {
    e.preventDefault()
    if (dndRef.current?.kind !== 'row') return
    e.dataTransfer.dropEffect = 'move'
    const box = e.currentTarget.getBoundingClientRect()
    const mode = e.clientY - box.top < box.height / 2 ? 'before' : 'after'
    const src = dndRef.current
    if (src && r >= src.start && r <= src.end) {
      setDropHint(null)
      return
    }
    setDropHint({ type: 'row', index: r, mode })
  }

  const applyDrop = (targetStart, targetEnd, isGroup) => {
    const src = dndRef.current
    const hint = dropHint
    clearDnd()
    if (!src || src.kind === 'row') return
    const mode = hint?.mode || 'after'
    const count = src.end - src.start + 1

    if (mode === 'into' && isGroup) {
      const sample = columns[targetStart]
      const parents = columnParentPath(sample)
      const label = parents.slice(-1)[0] || columns[targetStart]?.header_group || 'Group'
      // Already inside this span — just adopt the group label.
      if (src.start >= targetStart && src.end <= targetEnd) {
        onMergeHeaderGroups?.(src.start, src.end, label)
        return
      }
      let insertAt
      if (src.start > targetEnd) insertAt = targetStart
      else insertAt = targetEnd + 1
      let newStart = src.start
      if (insertAt <= src.start) newStart = insertAt
      else if (insertAt > src.end) newStart = insertAt - count
      else return
      onMoveColumnRange?.(src.start, count, insertAt)
      onMergeHeaderGroups?.(newStart, newStart + count - 1, label)
      return
    }

    const insertAt = mode === 'before' ? targetStart : targetEnd + 1
    onMoveColumnRange?.(src.start, count, insertAt)
  }

  const applyRowDrop = (targetRow) => {
    const src = dndRef.current
    const hint = dropHint
    clearDnd()
    if (!src || src.kind !== 'row') return
    const mode = hint?.type === 'row' ? hint.mode : 'after'
    const count = src.end - src.start + 1
    const insertAt = mode === 'before' ? targetRow : targetRow + 1
    onMoveRowRange?.(src.start, count, insertAt)
  }

  const tableWidth = colWidths.reduce((a, b) => a + b, 72)

  const dropClass = (start) => {
    if (!dropHint || dropHint.type !== 'col' || dropHint.index !== start) return ''
    if (dropHint.mode === 'before') return 'shadow-[inset_3px_0_0_0_#F5C518]'
    if (dropHint.mode === 'after') return 'shadow-[inset_-3px_0_0_0_#F5C518]'
    if (dropHint.mode === 'into') return 'ring-2 ring-inset ring-yellow bg-teal-deep/40'
    return ''
  }

  const rowDropClass = (r) => {
    if (!dropHint || dropHint.type !== 'row' || dropHint.index !== r) return ''
    if (dropHint.mode === 'before') return 'shadow-[inset_0_3px_0_0_#F5C518]'
    if (dropHint.mode === 'after') return 'shadow-[inset_0_-3px_0_0_#F5C518]'
    return ''
  }

  const hdrSelected = (start, end) => (
    hdrSel
    && start >= hdrSel.start
    && end <= hdrSel.end
  )

  const colFlashClass = (c) => {
    if (!actionFlash || actionFlash.axis !== 'cols') return ''
    if (flashCovers(actionFlash.to, c)) return 'bg-[#d4edda]/90 ring-2 ring-inset ring-[#2f9e44]'
    if (flashCovers(actionFlash.from, c)) return 'bg-[#f8d7da]/90 ring-2 ring-inset ring-[#c92a2a]'
    return ''
  }

  const rowFlashClass = (r) => {
    if (!actionFlash || actionFlash.axis !== 'rows') return ''
    if (flashCovers(actionFlash.to, r)) return 'bg-[#d4edda]/70 ring-2 ring-inset ring-[#2f9e44]'
    if (flashCovers(actionFlash.from, r)) return 'bg-[#f8d7da]/70 ring-2 ring-inset ring-[#c92a2a]'
    return ''
  }

  const cellFlashClass = (r, c) => {
    if (!actionFlash || actionFlash.axis !== 'cells') return ''
    const inFrom = actionFlash.from
      && r >= actionFlash.from.r0 && r <= actionFlash.from.r1
      && c >= actionFlash.from.c0 && c <= actionFlash.from.c1
    const inTo = actionFlash.to
      && r >= actionFlash.to.r0 && r <= actionFlash.to.r1
      && c >= actionFlash.to.c0 && c <= actionFlash.to.c1
    if (inTo) return 'bg-[#d4edda]/80 ring-2 ring-inset ring-[#2f9e44]'
    if (inFrom) return 'bg-[#f8d7da]/80 ring-2 ring-inset ring-[#c92a2a]'
    return ''
  }

  const flashLegend = actionFlash ? (
    <div className="flex flex-wrap items-center gap-3 text-[11px] text-ink-soft">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-[#f8d7da] ring-1 ring-[#c92a2a]" aria-hidden />
        Previous place
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm bg-[#d4edda] ring-1 ring-[#2f9e44]" aria-hidden />
        New place
      </span>
    </div>
  ) : null

  // Selection chrome (blue) — kept distinct from green/red action-flash highlights.
  const cellSelectedClass = 'border-[#2b6cb0] bg-[#d6eaf8]'
  const hdrSelectedClass = 'ring-2 ring-inset ring-[#2b6cb0] bg-[#d6eaf8]'

  const selectionLabel = (() => {
    if (hdrSel) {
      const n = hdrSel.end - hdrSel.start + 1
      const kind = hdrSel.levelIdx < headerMeta.depth - 1 ? 'header group' : 'column'
      return n === 1
        ? `Selected 1 ${kind}`
        : `Selected ${n} columns (headers)`
    }
    if (rect) {
      const rowsN = Math.abs(rect.r1 - rect.r0) + 1
      const colsN = Math.abs(rect.c1 - rect.c0) + 1
      if (rowsN === 1 && colsN === 1) return `Selected cell · row ${rect.r0 + 1}, column ${rect.c0 + 1}`
      return `Selected ${rowsN}×${colsN} cells · Shift+click to extend`
    }
    return 'Tip: click a header to select columns · Shift+click cells to select a range'
  })()

  const shell = (
      <div
        className={`flex flex-col overflow-hidden bg-surface ${
          variant === 'page'
            ? 'h-full min-h-0 w-full'
            : 'h-[min(900px,96vh)] w-[min(1360px,calc(100vw-1.5rem))] rounded-[16px] shadow-dhara'
        }`}
        onClick={variant === 'modal' ? (e) => e.stopPropagation() : undefined}
      >
        {/* Compact title bar */}
        <div className="flex flex-shrink-0 items-center justify-between gap-3 border-b border-line bg-cream px-3 py-2 sm:px-4">
          <div className="flex min-w-0 flex-1 items-center gap-3">
            <div className="min-w-0 flex-1">
              <div id="table-edit-title" className={`truncate text-[15px] font-bold tracking-tight sm:text-base ${displayTitle(table) ? 'text-ink' : 'italic text-ink-soft'}`}>
                {displayTitle(table) || 'No title — review'}
              </div>
              <div className="mt-0.5 flex flex-wrap items-center gap-x-2 text-[11px] text-ink-soft">
                <span>Page {table.page}</span>
                <span>·</span>
                <span>{rows.length}×{columnCount}</span>
                {flashLegend}
              </div>
            </div>
            <div
              className="inline-flex flex-shrink-0 rounded-md border border-line bg-white p-0.5"
              role="group"
              aria-label="Interaction mode"
            >
              <button
                type="button"
                onClick={() => setInteractionMode('view')}
                className={`inline-flex items-center gap-1 rounded px-2.5 py-1 text-[12px] font-semibold transition-colors ${
                  interactionMode === 'view'
                    ? 'bg-teal text-cream'
                    : 'text-ink-soft hover:bg-sage/60 hover:text-teal'
                }`}
                title="View only — editing tools disabled"
                aria-pressed={interactionMode === 'view'}
              >
                <Eye className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                View
              </button>
              <button
                type="button"
                onClick={() => setInteractionMode('edit')}
                className={`inline-flex items-center gap-1 rounded px-2.5 py-1 text-[12px] font-semibold transition-colors ${
                  interactionMode === 'edit'
                    ? 'bg-teal text-cream'
                    : 'text-ink-soft hover:bg-sage/60 hover:text-teal'
                }`}
                title="Edit table structure and cells"
                aria-pressed={interactionMode === 'edit'}
              >
                <Pencil className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                Edit
              </button>
            </div>
          </div>
          <div className="flex items-center gap-1.5">
            <div className="relative">
          <button
            type="button"
                onClick={() => {
                  setComparePdf((v) => !v)
                  setShowCompareTip(false)
                }}
                className={`inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-[12px] font-semibold transition-all ${
                  showCompareTip
                    ? 'relative z-10 border-teal bg-sage text-teal ring-2 ring-teal ring-offset-2 ring-offset-cream animate-pulse'
                    : comparePdf
                      ? 'border-teal bg-sage text-teal'
                      : 'border-line bg-white text-ink-soft hover:border-teal hover:text-teal'
                }`}
                title="Show PDF snapshot beside the editable table"
                aria-describedby={showCompareTip ? 'compare-pdf-tip' : undefined}
              >
                <Columns2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                Compare PDF
              </button>
              {showCompareTip ? (
                <div
                  id="compare-pdf-tip"
                  role="status"
                  className="absolute right-0 top-[calc(100%+0.5rem)] z-20 w-[min(280px,calc(100vw-2rem))] rounded-lg border border-teal/30 bg-white px-3 py-2.5 text-left shadow-dhara"
                >
                  <p className="text-[12px] leading-snug text-ink">
                    Want to check extraction against the source? Turn on{' '}
                    <span className="font-semibold text-teal">Compare PDF</span> anytime.
                  </p>
                  <button
                    type="button"
                    className="mt-1.5 text-[11px] font-semibold text-teal hover:underline"
                    onClick={() => setShowCompareTip(false)}
                  >
                    Got it
                  </button>
                </div>
              ) : null}
            </div>
            <button
              type="button"
              className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md text-ink-soft hover:bg-white hover:text-ink"
            onClick={onClose}
            aria-label="Close"
          >
            <X className="h-5 w-5" strokeWidth={1.75} />
          </button>
          </div>
        </div>

        {/* Excel-style ribbon */}
        <div className={`flex flex-shrink-0 flex-wrap items-center gap-1 border-b border-line bg-[#F7F2E8] px-2 py-1.5 sm:px-3 ${!canEdit ? 'opacity-55' : ''}`}>
          <EditorToolBtn disabled={!canEdit || !canUndo} title={!canEdit ? 'Switch to Edit to undo' : canUndo ? `Undo (${undoCount})` : 'Nothing to undo'} onClick={() => onUndo?.()}>
            <Undo2 className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Undo
          </EditorToolBtn>
          <EditorToolBtn disabled={!canEdit || !canRedo} title={!canEdit ? 'Switch to Edit to redo' : canRedo ? `Redo (${redoCount})` : 'Nothing to redo'} onClick={() => onRedo?.()}>
            <Redo2 className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Redo
          </EditorToolBtn>
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <EditorToolBtn disabled={!canEdit} onClick={() => onInsertColumn(columnCount)} title={!canEdit ? 'Switch to Edit to add columns' : 'Add column'}>
            <Plus className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Col
          </EditorToolBtn>
          <EditorToolBtn disabled={!canEdit} onClick={() => onInsertRow(rows.length)} title={!canEdit ? 'Switch to Edit to add rows' : 'Add row'}>
            <Plus className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Row
          </EditorToolBtn>
          <EditorToolBtn
            danger
            disabled={!canEdit || !canDeleteColumns}
            title={!canEdit ? 'Switch to Edit to delete columns' : canDeleteColumns ? 'Delete selected columns' : 'Select column headers first'}
            onClick={() => {
              if (!canEdit || !hasColSelection) return
              onDeleteColumns?.(selectedColStart, selectedColEnd)
              setHdrSel(null)
              setSel(null)
            }}
          >
            <Trash2 className="h-3.5 w-3.5" strokeWidth={2} />
            Del col
          </EditorToolBtn>
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <EditorToolBtn
            disabled={!canEdit}
            title={!canEdit ? 'Switch to Edit to manage groups' : hasColSelection ? 'Wrap selection in a group' : 'Add grouped column'}
            onClick={() => {
              if (!canEdit) return
              if (hasColSelection) onAddHeaderGroup?.(selectedColStart, selectedColEnd, 'New group')
              else onAddHeaderGroup?.(columnCount, columnCount, 'New group')
            }}
          >
            <Plus className="h-3.5 w-3.5 text-teal" strokeWidth={2.25} />
            Group
          </EditorToolBtn>
          <EditorToolBtn
            disabled={!canEdit || !canMergeGroups}
            title={!canEdit ? 'Switch to Edit to merge groups' : canMergeGroups ? 'Merge selected into one group' : 'Select 2+ columns'}
            onClick={() => {
              if (!canEdit || !hasColSelection) return
              const sample = columns[selectedColStart]
              const label = columnParentPath(sample).slice(-1)[0] || existingGroups[0] || 'Group'
              onMergeHeaderGroups?.(selectedColStart, selectedColEnd, label)
            }}
          >
            <Combine className="h-3.5 w-3.5 text-teal" strokeWidth={2} />
            Merge grp
          </EditorToolBtn>
          <EditorToolBtn
            danger
            disabled={!canEdit || !canDeleteGroup}
            title={!canEdit ? 'Switch to Edit to ungroup' : canDeleteGroup ? 'Remove group label' : 'Select a group header'}
            onClick={() => {
              if (!canEdit || !hdrSel) return
              onDeleteHeaderGroup?.(hdrSel.start, hdrSel.end - hdrSel.start + 1, hdrSel.levelIdx)
              setHdrSel(null)
            }}
          >
            Ungroup
          </EditorToolBtn>
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <EditorToolBtn
            disabled={!canEdit || !canMerge}
            title={!canEdit ? 'Switch to Edit to merge cells' : canMerge ? 'Merge selected cells' : 'Shift+click cells first'}
            onClick={() => {
              if (!canEdit || !rect) return
              onMergeCells(rect)
              setSel(null)
            }}
          >
            <Combine className="h-3.5 w-3.5 text-teal" strokeWidth={2} />
            Merge
          </EditorToolBtn>
          <EditorToolBtn
            disabled={!canEdit || !canUnmerge}
            title={!canEdit ? 'Switch to Edit to unmerge' : canUnmerge ? 'Unmerge cell' : 'Select a merged cell'}
            onClick={() => {
              if (!canEdit || !rect) return
              const origin = spanAtSelection || findBodySpanOrigin(bodySpans, rect.r0, rect.c0)
              onUnmergeCells(origin?.r ?? rect.r0, origin?.c ?? rect.c0)
              setSel(null)
            }}
          >
            Unmerge
          </EditorToolBtn>
          {hasColSelection && selectedColStart === selectedColEnd ? (
            <>
              <span className="mx-1 h-5 w-px bg-line" aria-hidden />
              <select
                disabled={!canEdit}
                className="max-w-[160px] rounded-md border border-line bg-white px-2 py-1 text-[11px] font-semibold text-ink outline-none focus:border-teal disabled:cursor-not-allowed disabled:opacity-40"
                value={columnParentPath(columns[selectedColStart]).slice(-1)[0] || ''}
                title={!canEdit ? 'Switch to Edit to assign groups' : 'Assign selected column to a group'}
                onChange={(e) => onChangeGroup(selectedColStart, e.target.value)}
              >
                <option value="">No group</option>
                {existingGroups.map((g) => (
                  <option key={g} value={g}>{g}</option>
                ))}
              </select>
            </>
          ) : null}
          <span className="ml-auto hidden max-w-[280px] truncate text-[11px] text-ink-soft sm:inline" title={selectionLabel}>
            {!canEdit ? 'View mode · Compare and zoom still work' : selectionLabel}
          </span>
        </div>

        {/* Main workspace: optional PDF | resizable split | sheet */}
        <div
          ref={workspaceRef}
          className={`flex min-h-0 flex-1 ${comparePdf ? 'flex-col lg:flex-row' : 'flex-col'}`}
        >
          {comparePdf ? (
            <>
              <div
                className="flex min-h-0 min-w-0 flex-col border-line bg-[#FFFCF6] max-lg:border-b"
                style={{
                  flexBasis: `${splitPct}%`,
                  flexGrow: 0,
                  flexShrink: 0,
                }}
              >
                <div className="flex flex-shrink-0 items-center justify-between gap-2 border-b border-line px-3 py-1.5">
                  <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">PDF source</div>
                  <div className="flex items-center gap-2">
                    <EditorZoomControls zoom={pdfZoom} onChange={setPdfZoom} label="PDF zoom" />
                    <span className="text-[11px] text-ink-soft">Page {table.page}</span>
                  </div>
                </div>
                <div ref={pdfPaneRef} className="min-h-0 flex-1 overflow-auto p-2">
                  <PdfTableSnapshot
                    jobId={jobId}
                    tableId={table.table_id}
                    maxHeightClass="max-h-none"
                    zoom={pdfZoom}
                  />
                </div>
              </div>

              {/* Drag handle: horizontal on desktop, vertical on stacked mobile */}
              <div
                role="separator"
                aria-orientation="vertical"
                aria-label="Resize comparison panes"
                title="Drag to resize"
                className="group relative z-[5] hidden h-full w-1.5 flex-shrink-0 cursor-col-resize bg-line hover:bg-teal lg:block"
                onMouseDown={(e) => {
                  e.preventDefault()
                  splitDragRef.current = { axis: 'x' }
                  document.body.style.cursor = 'col-resize'
                  document.body.style.userSelect = 'none'
                }}
              >
                <div className="pointer-events-none absolute inset-y-0 -left-1 -right-1" />
                <div className="pointer-events-none absolute left-1/2 top-1/2 h-8 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-teal/40 opacity-0 group-hover:opacity-100" />
              </div>
              <div
                role="separator"
                aria-orientation="horizontal"
                aria-label="Resize comparison panes"
                title="Drag to resize"
                className="group relative z-[5] h-1.5 w-full flex-shrink-0 cursor-row-resize bg-line hover:bg-teal lg:hidden"
                onMouseDown={(e) => {
                  e.preventDefault()
                  splitDragRef.current = { axis: 'y' }
                  document.body.style.cursor = 'row-resize'
                  document.body.style.userSelect = 'none'
                }}
              />
            </>
          ) : null}

          <div className="flex min-h-0 min-w-0 flex-1 flex-col">
            <div className="flex flex-shrink-0 items-center justify-between gap-2 border-b border-line bg-white px-3 py-1.5">
              <div className="text-[11px] font-bold uppercase tracking-wide text-ink-soft">
                {comparePdf ? 'Extracted table (editable)' : 'Worksheet'}
              </div>
              <div className="flex items-center gap-2">
                <EditorZoomControls zoom={tableZoom} onChange={setTableZoom} label="Table zoom" />
                <button
                  type="button"
                  disabled={!canEdit}
                  className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-teal hover:bg-sage disabled:cursor-not-allowed disabled:opacity-40"
                  onClick={() => onInsertRow(rows.length)}
                >
                  + Row
                </button>
                <button
                  type="button"
                  disabled={!canEdit}
                  className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-teal hover:bg-sage disabled:cursor-not-allowed disabled:opacity-40"
                  onClick={() => onInsertColumn(columnCount)}
                >
                  + Col
                </button>
              </div>
            </div>
            <div ref={tablePaneRef} className="min-h-0 flex-1 overflow-auto bg-white" onDragEnd={clearDnd}>
              <div style={{ zoom: tableZoom }}>
              <table className="border-collapse text-[12px]" style={{ tableLayout: 'fixed', width: tableWidth }}>
              <colgroup>
                  <col style={{ width: 40 }} />
                {colWidths.map((w, i) => (
                    <col key={i} style={{ width: w }} />
                ))}
                  <col style={{ width: 32 }} />
              </colgroup>
                <thead>
                  {headerMeta.rows.map((segs, hr) => (
                    <tr key={`hdr-${hr}`} className="bg-[#E8F0EF]">
                      {hr === 0 ? (
                        <th
                          rowSpan={headerMeta.depth}
                          className="sticky left-0 z-[3] border border-[#c5d4d2] bg-[#D5E4E2] px-0.5 py-0.5 text-center text-[10px] font-semibold text-ink-soft"
                        >
                          #
                        </th>
                      ) : null}
                      {segs.map((seg) => {
                        const isLeaf = seg.isLeaf
                        const segEnd = seg.start + seg.colSpan - 1
                        const isGroup = !isLeaf
                        return (
                          <th
                            key={seg.key}
                            colSpan={seg.colSpan > 1 ? seg.colSpan : undefined}
                            rowSpan={seg.rowSpan > 1 ? seg.rowSpan : undefined}
                            onDragOver={(e) => onHeaderDragOver(e, seg.start, segEnd, isGroup || seg.colSpan > 1)}
                            onDragLeave={() => setDropHint((h) => (h && h.index === seg.start ? null : h))}
                            onDrop={(e) => {
                              e.preventDefault()
                              applyDrop(seg.start, segEnd, isGroup || seg.colSpan > 1)
                            }}
                            onClick={(e) => {
                              if (e.target.closest('textarea,select,button,input')) return
                              selectHeaderRange(seg.start, segEnd, hr, e.shiftKey)
                            }}
                            className={`group relative border border-[#c5d4d2] px-0.5 py-0.5 align-top font-medium text-ink ${seg.colSpan > 1 || !isLeaf ? 'text-center' : 'text-left'} ${dropClass(seg.start)} ${hdrSelected(seg.start, segEnd) ? hdrSelectedClass : 'bg-[#E8F0EF]'} ${(() => {
                              let red = false
                              let green = false
                              for (let c = seg.start; c <= segEnd; c += 1) {
                                if (actionFlash?.axis === 'cols' && flashCovers(actionFlash.to, c)) green = true
                                if (actionFlash?.axis === 'cols' && flashCovers(actionFlash.from, c)) red = true
                              }
                              if (green) return 'ring-2 ring-inset ring-[#2f9e44] bg-[#d4edda]'
                              if (red) return 'ring-2 ring-inset ring-[#c92a2a] bg-[#f8d7da]'
                              return ''
                            })()}`}
                          >
                            {isLeaf ? (
                              <div className="flex min-w-0 items-start gap-0.5">
                                <button
                                  type="button"
                                  draggable={canEdit}
                                  disabled={!canEdit}
                                  onDragStart={(e) => beginDrag('column', seg.start, segEnd, e)}
                                  onDragEnd={clearDnd}
                                  className="mt-0.5 flex-shrink-0 cursor-grab rounded p-0.5 text-ink-soft opacity-40 hover:bg-white/80 hover:opacity-100 active:cursor-grabbing group-hover:opacity-100 disabled:cursor-default disabled:opacity-20"
                                  title={canEdit ? 'Drag to reorder' : 'Switch to Edit to reorder'}
                                  aria-label="Drag column"
                                >
                                  <GripVertical className="h-3 w-3" strokeWidth={2} />
                                </button>
                                <AutoGrowTextarea
                                  readOnly={!canEdit}
                                  className="w-full min-w-0 border-0 bg-transparent px-0.5 py-0.5 text-[11px] font-semibold leading-snug text-ink outline-none [overflow-wrap:anywhere] break-words whitespace-pre-wrap focus:bg-white focus:ring-1 focus:ring-teal"
                                  value={columns[seg.start]?.name || ''}
                                  placeholder="Column"
                                  onChange={(next) => onRenameColumn(seg.start, next)}
                                />
                                <button
                                  type="button"
                                  className="mt-0.5 flex-shrink-0 rounded p-0.5 text-[#c45c4a] opacity-0 hover:bg-[#fde8e4] group-hover:opacity-100 disabled:opacity-0"
                                  disabled={!canEdit || columnCount <= 1}
                                  onClick={() => onDeleteColumn(seg.start)}
                                  title={canEdit ? 'Delete column' : 'Switch to Edit to delete'}
                                  aria-label="Delete column"
                                >
                                  <Trash2 className="h-3 w-3" />
                                </button>
                              </div>
                            ) : (
                              <div className="flex min-w-0 items-start justify-center gap-0.5">
                                {!seg.empty ? (
                                  <button
                                    type="button"
                                    draggable={canEdit}
                                    disabled={!canEdit}
                                    onDragStart={(e) => beginDrag('group', seg.start, segEnd, e)}
                                    onDragEnd={clearDnd}
                                    className="mt-0.5 flex-shrink-0 cursor-grab rounded p-0.5 text-ink-soft opacity-40 hover:opacity-100 active:cursor-grabbing group-hover:opacity-100 disabled:cursor-default disabled:opacity-20"
                                    title={canEdit ? 'Drag group' : 'Switch to Edit to reorder'}
                                    aria-label="Drag group"
                                  >
                                    <GripVertical className="h-3 w-3" strokeWidth={2} />
                                  </button>
                                ) : null}
                                <AutoGrowTextarea
                                  readOnly={!canEdit}
                                  className="w-full min-w-0 border-0 bg-transparent px-0.5 py-0.5 text-center text-[10px] font-bold uppercase leading-snug tracking-wide text-ink outline-none [overflow-wrap:anywhere] break-words whitespace-pre-wrap placeholder:font-medium placeholder:normal-case placeholder:tracking-normal placeholder:text-ink-soft focus:bg-white focus:ring-1 focus:ring-teal"
                                  value={seg.label || ''}
                                  placeholder={seg.empty ? 'Group…' : 'Group'}
                                  title={seg.empty ? 'Type a group name' : `Group spanning ${seg.colSpan} cols`}
                                  onChange={(next) => onSetHeaderPathLevel(seg.start, seg.colSpan, hr, next)}
                                />
                              </div>
                            )}
                            {isLeaf && canEdit ? (
                              <span
                                role="separator"
                                aria-orientation="vertical"
                                aria-label="Resize column"
                                onMouseDown={(e) => startResize(seg.start, e)}
                                className="absolute right-0 top-0 z-[4] h-full w-1 cursor-col-resize hover:bg-teal/50"
                              />
                            ) : null}
                          </th>
                        )
                      })}
                      {hr === 0 ? (
                        <th
                          rowSpan={headerMeta.depth}
                          className="border border-[#c5d4d2] bg-[#D5E4E2] px-0.5 py-0.5"
                        >
                          {' '}
                        </th>
                      ) : null}
                    </tr>
                  ))}
                </thead>
              <tbody>
                  {(rows || []).map((row, r) => (
                  <tr
                    key={r}
                      className={`group/row ${r % 2 === 0 ? 'bg-white' : 'bg-[#FAFBFA]'} hover:bg-[#F0F6F5] ${rowDropClass(r)} ${rowFlashClass(r)}`}
                      onDragOver={(e) => onRowDragOver(e, r)}
                      onDrop={(e) => {
                        e.preventDefault()
                        applyRowDrop(r)
                      }}
                    >
                      <td className="sticky left-0 z-[1] border border-[#d8e0de] bg-inherit px-0 py-0 text-center text-[10px] tabular-nums text-ink-soft">
                        <div className="flex items-center justify-center gap-0">
                          <button
                            type="button"
                            draggable={canEdit}
                            disabled={!canEdit}
                            onDragStart={(e) => beginDrag('row', r, r, e)}
                            onDragEnd={clearDnd}
                            className="cursor-grab rounded p-0.5 text-ink-soft opacity-30 hover:opacity-100 active:cursor-grabbing group-hover/row:opacity-70 disabled:cursor-default disabled:opacity-15"
                            title={canEdit ? 'Drag row' : 'Switch to Edit to reorder'}
                            aria-label={`Drag row ${r + 1}`}
                          >
                            <GripVertical className="h-3 w-3" strokeWidth={2} />
                          </button>
                          <span className="pr-0.5">{r + 1}</span>
                        </div>
                      </td>
                    {Array.from({ length: columnCount }, (_, c) => {
                        const span = bodySpans[r]?.[c]
                      if (span == null) return null
                        const selected = Boolean(
                          rect
                          && r >= rect.r0 && r <= rect.r1
                          && c >= rect.c0 && c <= rect.c1
                        )
                      const merged = span.rowSpan > 1 || span.colSpan > 1
                      return (
                        <td
                          key={c}
                          rowSpan={span.rowSpan > 1 ? span.rowSpan : undefined}
                          colSpan={span.colSpan > 1 ? span.colSpan : undefined}
                            onClick={(e) => selectCell(r, c, e.shiftKey)}
                            className={`max-w-0 cursor-cell border px-0 py-0 align-top break-words [overflow-wrap:anywhere] ${
                              selected ? cellSelectedClass : 'border-[#d8e0de]'
                            } ${merged ? '' : ''} ${colFlashClass(c)} ${cellFlashClass(r, c)}`}
                        >
                          <ExtractedDataCell
                            value={row[c] ?? null}
                              sourceValue={sourceRows?.[r]?.[c]}
                            col={columns[c]}
                              locked={!canEdit}
                            fitWidth
                            onChange={(next) => onChangeCell(r, c, next)}
                          />
                        </td>
                      )
                    })}
                      <td className="border border-[#d8e0de] px-0 py-0 text-center">
                        <button
                          type="button"
                          className="rounded p-0.5 text-[#c45c4a] opacity-40 hover:bg-[#fde8e4] hover:opacity-100 disabled:opacity-20 group-hover/row:opacity-70"
                          disabled={!canEdit || (rows || []).length <= 1}
                          onClick={() => onDeleteRow(r)}
                          title={canEdit ? 'Delete row' : 'Switch to Edit to delete'}
                          aria-label={`Delete row ${r + 1}`}
                        >
                          <Trash2 className="h-3 w-3" strokeWidth={2} />
                        </button>
                      </td>
                  </tr>
                ))}
              </tbody>
            </table>
              </div>
            </div>
          </div>
        </div>

        <div className="flex flex-shrink-0 items-center justify-between gap-2 border-t border-line bg-cream/70 px-3 py-2 sm:px-4">
          <div className="text-[11px] text-ink-soft sm:text-[12px]">{footerHint}</div>
          <div className="flex items-center gap-2">
            <Button variant="secondary" size="sm" onClick={onClose}>
              {variant === 'page' ? 'Close' : 'Cancel'}
            </Button>
            <Button
              variant="primary"
              size="sm"
              disabled={doneLabel?.includes('Saving')}
              onClick={async () => {
                await onDone?.()
                if (variant === 'modal') onClose?.()
              }}
            >
              {doneLabel}
          </Button>
        </div>
      </div>
      </div>
  )

  if (variant === 'page') {
    return (
      <div className="flex h-[100dvh] w-full flex-col overflow-hidden bg-surface" role="main" aria-labelledby="table-edit-title">
        {shell}
      </div>
    )
  }

  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center overflow-hidden bg-[rgba(16,64,63,0.52)] p-3 sm:p-5"
      role="dialog"
      aria-modal="true"
      aria-labelledby="table-edit-title"
      onClick={onClose}
    >
      {shell}
    </div>,
    document.body,
  )
}
