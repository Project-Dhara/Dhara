'use client'

import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { isGarbled } from '../../lib/garbled'
import {
  buildMultiLevelHeaderRows,
  columnHeaderPath,
  isDirectionLikeColumn,
  directionDisplay,
  directionSelectOptions,
} from '../../lib/pdfReviewHelpers'

export function ExtractedTableHead({ columns, lockedCols = [], sticky = false, showIndex = false }) {
  const { depth, rows } = buildMultiLevelHeaderRows(columns)
  const rowRefs = useRef([])
  // Sticky `top` must match each row's real offset or the leaf row hangs over the body.
  const [stickyTops, setStickyTops] = useState(() => Array.from({ length: Math.max(depth, 1) }, () => 0))
  const headerSig = `${depth}:${(columns || []).map((c) => columnHeaderPath(c).join('\u0001')).join('\u0002')}`

  useLayoutEffect(() => {
    if (!sticky) return undefined
    const measure = () => {
      const baseEl = rowRefs.current[0]
      if (!baseEl) return
      const base = baseEl.getBoundingClientRect().top
      const tops = rows.map((_, i) => {
        const el = rowRefs.current[i]
        if (!el) return 0
        // Prefer row box; fall back to first cell if rowspan collapses tr height to 0.
        let top = Math.round(el.getBoundingClientRect().top - base)
        if (i > 0 && top <= 0) {
          const th = el.querySelector('th')
          if (th) top = Math.round(th.getBoundingClientRect().top - base)
        }
        return Math.max(0, top)
      })
      setStickyTops((prev) => (
        prev.length === tops.length && prev.every((v, i) => v === tops[i]) ? prev : tops
      ))
    }
    measure()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(measure) : null
    rowRefs.current.forEach((el) => { if (el) ro?.observe(el) })
    window.addEventListener('resize', measure)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', measure)
    }
  }, [sticky, headerSig, rows])

  // Don't stick multi-level headers until offsets are known — fixed guesses overlap row 1.
  const stickyOn = sticky && (
    depth <= 1 || stickyTops.length >= depth && stickyTops.every((t, i) => i === 0 || t > 0)
  )

  const thFor = (seg, isIndex = false) => {
    const isGroup = !isIndex && depth > 1 && !seg.isLeaf
    if (stickyOn) {
      return [
        // One teal for every header level — groups used to be teal-deep.
        'sticky max-w-0 px-1 pt-0.5 pb-1 align-top font-sans text-[10px] font-medium leading-snug tracking-wide text-cream bg-teal',
        // Same teal rule between levels as between columns.
        'border-x border-b border-teal-deep/40',
        isGroup ? 'text-center font-semibold' : 'text-left',
        isIndex ? 'text-center' : '',
      ].filter(Boolean).join(' ')
    }
    if (sticky) {
      // Pre-measure: same chrome, not sticky yet (avoids body overlap).
      return [
        'max-w-0 px-1 pt-0.5 pb-1 align-top font-sans text-[10px] font-medium leading-snug tracking-wide text-cream bg-teal',
        'border-x border-b border-teal-deep/40',
        isGroup ? 'text-center font-semibold' : 'text-left',
        isIndex ? 'text-center' : '',
      ].filter(Boolean).join(' ')
    }
    return [
      'max-w-0 px-2.5 py-1.5 align-top font-sans text-[11.5px] uppercase tracking-wide text-cream bg-teal',
      'border-x border-b border-teal-deep/35',
      isGroup ? 'text-center font-semibold' : 'text-left font-medium',
      isIndex || seg.colSpan > 1 || seg.rowSpan > 1 ? 'text-center' : '',
    ].filter(Boolean).join(' ')
  }

  return (
    <thead className="bg-teal">
      {rows.map((segs, r) => (
        <tr
          key={`hr-${r}`}
          ref={(el) => { rowRefs.current[r] = el }}
          className="bg-teal"
        >
          {showIndex && r === 0 ? (
            <th
              className={thFor({ isLeaf: true, colSpan: 1, rowSpan: depth }, true)}
              rowSpan={depth}
              style={stickyOn ? { top: stickyTops[0] ?? 0, zIndex: 2 } : undefined}
            >
              #
            </th>
          ) : null}
          {segs.map((seg) => {
            const showLocked = seg.isLeaf && lockedCols[seg.start]
            return (
              <th
                key={seg.key}
                colSpan={seg.colSpan > 1 ? seg.colSpan : undefined}
                rowSpan={seg.rowSpan > 1 ? seg.rowSpan : undefined}
                className={thFor(seg)}
                style={stickyOn ? { top: stickyTops[r] ?? 0, zIndex: 2 + r } : undefined}
                title={showLocked ? `${seg.label} — read-only` : seg.label}
              >
                <span className="block min-w-0 whitespace-normal break-words [overflow-wrap:anywhere] hyphens-auto leading-snug">
                  {seg.label}
                  {showLocked ? (
                    <span className={`font-semibold normal-case tracking-normal text-cream/70 ${(sticky || stickyOn) ? 'mt-0.5 block' : 'ml-1'}`}>
                      {(sticky || stickyOn) ? 'locked' : '· locked'}
                    </span>
                  ) : null}
                </span>
              </th>
            )
          })}
        </tr>
      ))}
    </thead>
  )
}


export function DirectionGlyph({ dir, className = '' }) {
  if (!dir?.Icon) return null
  const Icon = dir.Icon
  return (
    <Icon
      className={`h-4 w-4 ${dir.className} ${className}`}
      strokeWidth={2.25}
      aria-hidden
    />
  )
}


/** Spreadsheet cell textarea that grows to show all wrapped text. */
export function AutoGrowTextarea({
  value,
  onChange,
  className,
  style,
  placeholder,
  title,
  readOnly = false,
}) {
  const ref = useRef(null)

  const syncHeight = () => {
    const el = ref.current
    if (!el) return
    el.style.height = '0px'
    el.style.height = `${Math.max(el.scrollHeight, 22)}px`
  }

  useLayoutEffect(() => {
    syncHeight()
  }, [value])

  useEffect(() => {
    const el = ref.current
    if (!el) return undefined
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => syncHeight()) : null
    ro?.observe(el)
    // Parent width changes (column resize / zoom) also need a remeasure.
    const parent = el.parentElement
    if (parent) ro?.observe(parent)
    window.addEventListener('resize', syncHeight)
    return () => {
      ro?.disconnect()
      window.removeEventListener('resize', syncHeight)
    }
  }, [])

  return (
    <textarea
      ref={ref}
      rows={1}
      readOnly={readOnly}
      className={`${className} overflow-hidden outline-none ring-0 focus:outline-none focus:ring-0 ${readOnly ? 'cursor-default caret-transparent' : ''}`}
      style={style}
      value={value}
      placeholder={placeholder}
      title={title}
      onChange={(e) => {
        if (readOnly) return
        onChange(e.target.value)
        // Grow immediately on keystroke before React commits the new value height.
        requestAnimationFrame(syncHeight)
      }}
      onInput={syncHeight}
    />
  )
}


/** Spreadsheet-style cell for extracted PDF rows (preview + full-table modal). */
export function ExtractedDataCell({
  value,
  sourceValue,
  col,
  locked,
  onChange,
  fitWidth = false,
}) {
  const flagged = isGarbled(sourceValue) || (value == null && col?.input_type === 'dropdown')
  const editable = !locked
  const directionCol = isDirectionLikeColumn(col)
  const dir = directionDisplay(value)
  const dropdownOptions =
    editable && col?.input_type === 'dropdown' && Array.isArray(col.input_options) && col.input_options.length > 0
      ? col.input_options
      : null
  const controlWidth = fitWidth ? 'w-full min-w-0 max-w-full' : 'w-full min-w-[4.5rem]'
  const fitStyle = fitWidth ? { minWidth: 0, width: '100%', maxWidth: '100%' } : undefined

  if (editable && (dropdownOptions || directionCol)) {
    const opts = directionCol ? directionSelectOptions(dropdownOptions || col?.input_options) : dropdownOptions
    return (
      <select
        className={`${controlWidth} box-border rounded-none border-0 bg-transparent px-1 py-0.5 text-[12.5px] outline-none ring-0 focus:outline-none focus:ring-0 ${flagged ? 'bg-[#fff8e1]' : ''} ${dir?.className || ''}`}
        style={fitStyle}
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        title={dir ? dir.label : undefined}
        aria-label={col?.name || 'Direction'}
      >
        <option value="">{directionCol ? '' : '—'}</option>
        {opts.map((opt) => {
          const d = directionDisplay(opt)
          return (
            <option key={opt} value={opt} title={d?.label || opt}>
              {d ? d.symbol : opt}
            </option>
          )
        })}
      </select>
    )
  }

  if (editable && !directionCol) {
    const text = value ?? ''
    return (
      <AutoGrowTextarea
        value={text}
        onChange={onChange}
        className={`${controlWidth} box-border resize-none appearance-none rounded-none border-0 bg-transparent px-1.5 py-1 text-[12.5px] leading-snug [overflow-wrap:anywhere] break-words whitespace-pre-wrap shadow-none outline-none focus-visible:outline-none ${flagged ? 'bg-[#fff8e1]' : ''}`}
        style={fitStyle}
      />
    )
  }

  if (directionCol || dir) {
    if (!dir) {
      return <span className="inline-block min-h-[1em]" aria-hidden="true" />
    }
    return (
      <span className="inline-flex items-center justify-center" title={dir.label} aria-label={dir.label}>
        <DirectionGlyph dir={dir} />
      </span>
    )
  }

  const display = value === null || value === undefined || value === '' ? null : String(value)
  return (
    <span
      className={`block min-w-0 whitespace-normal break-words [overflow-wrap:anywhere] leading-snug ${display == null ? 'italic text-[#a49c8e]' : 'text-ink'}`}
      title={display || ''}
    >
      {display == null ? '—' : display}
    </span>
  )
}



/** Labeled tool cluster for the table editor (beginner-friendly grouping). */
export function EditorToolSection({ icon: Icon, title, hint, children, accent = 'teal' }) {
  const accents = {
    teal: 'border-teal/25 bg-[#F3F8F7]',
    amber: 'border-[#e6d4a0] bg-[#FFF9EB]',
    rose: 'border-[#e8c4bc] bg-[#FFF6F4]',
  }
  return (
    <div className={`rounded-xl border px-3 py-2.5 ${accents[accent] || accents.teal}`}>
      <div className="mb-2 flex items-start gap-2">
        <span className="mt-0.5 flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-md bg-white/80 text-teal shadow-sm">
          <Icon className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
        </span>
        <div className="min-w-0">
          <div className="text-[12px] font-bold tracking-tight text-ink">{title}</div>
          {hint ? <div className="text-[11px] leading-snug text-ink-soft">{hint}</div> : null}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">{children}</div>
    </div>
  )
}


export function EditorToolBtn({
  children,
  onClick,
  disabled,
  danger = false,
  title,
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-semibold transition-colors disabled:cursor-not-allowed disabled:opacity-40 ${
        danger
          ? 'border-[#e8c4bc] bg-white text-[#b54a3a] hover:bg-[#fde8e4]'
          : 'border-line bg-white text-ink hover:border-teal hover:bg-sage/60'
      }`}
    >
      {children}
    </button>
  )
}


