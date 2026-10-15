'use client'

import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import Button from '../ui/Button'
import {
  computeFittedColumnLayout,
  displayTitle,
  resolveEditorBodySpans,
} from '../../lib/pdfReviewHelpers'
import { ExtractedDataCell, ExtractedTableHead } from './ExtractedTableGrid'

/**
 * Read-only full-table viewer. Fits columns to the modal width (no horizontal
 * scroll); tall tables scroll vertically.
 */
export function ViewAllTableModal({
  table,
  columns,
  rows,
  sourceRows,
  cellMerges = [],
  mergesExplicit = false,
  lockedCols = [],
  onClose,
}) {
  const [mounted, setMounted] = useState(false)
  const columnCount = (columns || []).length
  const title = displayTitle(table) || 'Table preview'
  const spans = resolveEditorBodySpans(rows, columns, cellMerges, mergesExplicit)
  const colLayout = computeFittedColumnLayout(columns, rows)

  useEffect(() => {
    setMounted(true)
    const onKey = (e) => {
      if (e.key === 'Escape') onClose?.()
    }
    window.addEventListener('keydown', onKey)
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [onClose])

  if (!mounted) return null

  return createPortal(
    <div
      className="fixed inset-0 z-[1200] flex items-center justify-center overflow-hidden bg-[rgba(16,64,63,0.55)] p-3 sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="view-all-table-title"
      onClick={onClose}
    >
      <div
        className="flex max-h-[min(920px,92vh)] w-[min(1100px,calc(100vw-1.5rem))] flex-col overflow-hidden rounded-2xl bg-surface shadow-dhara"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex flex-shrink-0 items-start justify-between gap-3 border-b border-line bg-cream px-4 py-3.5 sm:px-5">
          <div className="min-w-0">
            <div className="text-[11px] font-bold uppercase tracking-wide text-teal">Full table</div>
            <div
              id="view-all-table-title"
              className="mt-0.5 whitespace-normal break-words text-[15px] font-bold leading-snug text-ink sm:text-base"
            >
              {title}
            </div>
            <div className="mt-0.5 text-[12px] text-ink-soft">
              {(rows || []).length} rows · {columnCount} columns
            </div>
          </div>
          <button
            type="button"
            className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-md text-ink-soft hover:bg-white hover:text-ink"
            onClick={onClose}
            aria-label="Close full table"
          >
            <X className="h-5 w-5" strokeWidth={1.75} />
          </button>
        </div>

        {/* Readable headers via minWidth; scroll both axes when needed. */}
        <div className="min-h-0 flex-1 overflow-auto p-3 sm:p-4">
          <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full table-fixed border-collapse text-[12.5px]">
            {colLayout.length === columnCount ? (
              <colgroup>
                {colLayout.map((col, i) => (
                  <col
                    key={i}
                    style={{ width: `${col.pct}%`, minWidth: `${col.minCh}ch` }}
                  />
                ))}
              </colgroup>
            ) : null}
            <ExtractedTableHead columns={columns} lockedCols={lockedCols} sticky />
            <tbody>
              {(rows || []).map((row, r) => (
                <tr key={r} className="odd:bg-white even:bg-[#FFFCF6]">
                  {Array.from({ length: columnCount }, (_, c) => {
                    const span = spans[r]?.[c]
                    if (span == null) return null
                    const v = row?.[c] ?? null
                    const col = columns[c]
                    const merged = span.rowSpan > 1 || span.colSpan > 1
                    const numeric = lockedCols[c]
                    const dense = columnCount >= 10
                    return (
                      <td
                        key={c}
                        rowSpan={span.rowSpan > 1 ? span.rowSpan : undefined}
                        colSpan={span.colSpan > 1 ? span.colSpan : undefined}
                        className={`max-w-0 border border-line align-top ${dense ? 'px-1 py-1' : 'px-2 py-1.5'} ${numeric ? 'whitespace-nowrap text-center tabular-nums' : 'break-words [overflow-wrap:anywhere]'} ${merged ? 'align-middle' : ''}`}
                      >
                        <ExtractedDataCell
                          value={v}
                          sourceValue={sourceRows?.[r]?.[c]}
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
          </div>
        </div>

        <div className="flex flex-shrink-0 justify-end border-t border-line bg-cream/60 px-4 py-3 sm:px-5">
          <Button variant="primary" size="sm" onClick={onClose}>Close</Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
