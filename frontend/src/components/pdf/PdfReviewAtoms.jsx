'use client'

import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ArrowUp, ChevronDown } from 'lucide-react'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import { REASON_LABELS, canonicalizeReviewReason, getScrollParent, isDocumentScroller } from '../../lib/pdfReviewHelpers'

export function ScrollToTopButton({ scrollRootRef }) {
  const [visible, setVisible] = useState(false)
  const [mounted, setMounted] = useState(false)
  const scrollElRef = useRef(null)

  useEffect(() => {
    setMounted(true)
  }, [])

  useEffect(() => {
    if (!mounted) return undefined

    let listening = null

    const readTop = (el) => {
      if (isDocumentScroller(el)) {
        return window.scrollY || document.documentElement.scrollTop || 0
      }
      return el.scrollTop || 0
    }

    const onScroll = () => {
      setVisible(readTop(scrollElRef.current) > 240)
    }

    const attach = () => {
      if (listening) {
        listening.removeEventListener('scroll', onScroll)
        listening = null
      }
      const scrollEl = getScrollParent(scrollRootRef?.current)
      scrollElRef.current = scrollEl
      listening = isDocumentScroller(scrollEl) ? window : scrollEl
      listening.addEventListener('scroll', onScroll, { passive: true })
      onScroll()
    }

    attach()
    // Re-bind after layout — scrollport / refs can resolve a tick late.
    const raf = window.requestAnimationFrame(attach)

    return () => {
      window.cancelAnimationFrame(raf)
      listening?.removeEventListener('scroll', onScroll)
    }
  }, [scrollRootRef, mounted])

  const scrollUp = () => {
    const el = scrollElRef.current
    if (isDocumentScroller(el)) {
      window.scrollTo({ top: 0, behavior: 'smooth' })
      return
    }
    el.scrollTo({ top: 0, behavior: 'smooth' })
  }

  if (!mounted) return null

  // Portal to body so `fixed` stays on the viewport (page-enter animation
  // uses transform, which would otherwise trap position:fixed in the content).
  return createPortal(
    <button
      type="button"
      aria-label="Scroll to top"
      onClick={scrollUp}
      className={`fixed bottom-7 right-7 z-[200] flex h-11 w-11 items-center justify-center rounded-full border border-line bg-white text-teal shadow-[0_6px_20px_rgba(16,64,63,0.16)] transition-all duration-200 hover:border-teal hover:bg-sage ${
        visible ? 'pointer-events-auto translate-y-0 opacity-100' : 'pointer-events-none translate-y-2 opacity-0'
      }`}
    >
      <ArrowUp className="h-[18px] w-[18px]" strokeWidth={1.75} aria-hidden />
    </button>,
    document.body,
  )
}


/**
 * Gradual accordion open/close for review table cards.
 * Keeps content mounted briefly on close so the collapse can animate.
 */
export function TableExpandPanel({ open, children }) {
  const [rendered, setRendered] = useState(open)
  const [expanded, setExpanded] = useState(open)

  useEffect(() => {
    if (open) {
      setRendered(true)
      const id = window.requestAnimationFrame(() => {
        window.requestAnimationFrame(() => setExpanded(true))
      })
      return () => window.cancelAnimationFrame(id)
    }
    setExpanded(false)
    const t = window.setTimeout(() => setRendered(false), 420)
    return () => window.clearTimeout(t)
  }, [open])

  if (!rendered) return null

  return (
    <div
      className={`grid transition-[grid-template-rows] duration-[420ms] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${
        expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
      }`}
    >
      <div className="min-h-0 overflow-hidden">
        <div
          className={`origin-top transition-[opacity,transform] duration-[380ms] ease-[cubic-bezier(0.22,1,0.36,1)] motion-reduce:transition-none ${
            expanded ? 'translate-y-0 opacity-100' : '-translate-y-1 opacity-0'
          }`}
        >
          {children}
        </div>
      </div>
    </div>
  )
}


export function ReviewBadge({ needed, reason }) {
  if (!needed) return <Badge tone="ok">No review needed</Badge>
  const label = REASON_LABELS[canonicalizeReviewReason(reason)] || 'Needs review'
  return <Badge tone="warn">{label}</Badge>
}


export function DeleteConfirmDialog({ count, onCancel, onConfirm, deleting }) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  if (!mounted) return null
  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="delete-tables-title"
      aria-describedby="delete-tables-body"
      onClick={onCancel}
    >
      <div
        className="flex w-full max-w-[440px] flex-col gap-3.5 rounded-xl border border-line bg-white p-5 shadow-[0_16px_40px_rgba(16,64,63,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="delete-tables-title" className="text-[16px] font-bold text-ink">
          Delete {count === 1 ? 'this table' : `${count} tables`}?
        </div>
        <p id="delete-tables-body" className="text-[13px] leading-snug text-ink-soft">
          {count === 1
            ? 'This table will be removed from the review list. You can’t undo this without re-uploading the PDF.'
            : `These ${count} tables will be removed from the review list. You can’t undo this without re-uploading the PDF.`}
        </p>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={deleting}>Cancel</Button>
          <Button
            variant="primary"
            size="sm"
            loading={deleting}
            className="!bg-[#c45c4a] hover:!bg-[#a84a3b]"
            onClick={onConfirm}
          >
            Delete
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}


export function MergeConfirmDialog({ count, onCancel, onConfirm, merging }) {
  const [mounted, setMounted] = useState(false)
  useEffect(() => { setMounted(true) }, [])

  if (!mounted) return null
  return createPortal(
    <div
      className="fixed inset-0 z-[1100] flex items-center justify-center bg-[rgba(16,64,63,0.52)] p-5"
      role="alertdialog"
      aria-modal="true"
      aria-labelledby="merge-tables-title"
      aria-describedby="merge-tables-body"
      onClick={onCancel}
    >
      <div
        className="flex w-full max-w-[440px] flex-col gap-3.5 rounded-xl border border-line bg-white p-5 shadow-[0_16px_40px_rgba(16,64,63,0.18)]"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="merge-tables-title" className="text-[16px] font-bold text-ink">
          Merge {count} tables?
        </div>
        <p id="merge-tables-body" className="text-[13px] leading-snug text-ink-soft">
          Rows will be stacked in page order into the earliest table. The other
          {count === 2 ? ' table' : ` ${count - 1} tables`} will be removed from the list.
          Only tables with the same column headers can be merged.
        </p>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={merging}>Cancel</Button>
          <Button variant="primary" size="sm" loading={merging} onClick={onConfirm}>
            Merge
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}


export function CollapsibleSection({ label, open, onToggle, hint, children }) {
  return (
    <div className="flex flex-col">
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={open}
        className="group flex w-full items-center gap-2 rounded-md px-1.5 py-1.5 text-left transition-colors hover:bg-cream/80"
      >
        <span
          className={`flex h-5 w-5 flex-none items-center justify-center rounded-full border border-line bg-white text-ink-soft transition-all duration-300 ease-out group-hover:border-teal group-hover:text-teal ${open ? 'rotate-180 bg-sage/40' : 'rotate-0'}`}
          aria-hidden
        >
          <ChevronDown className="h-3.5 w-3.5" strokeWidth={2} />
        </span>
        <span className="text-[11px] font-bold uppercase tracking-wide text-ink-soft group-hover:text-ink">{label}</span>
        {hint ? (
          <span className="text-[11px] font-semibold normal-case tracking-normal text-ink-soft/70">{hint}</span>
        ) : null}
      </button>
      <div
        className="grid transition-[grid-template-rows] duration-300 ease-in-out"
        style={{ gridTemplateRows: open ? '1fr' : '0fr' }}
      >
        <div className="min-h-0 overflow-hidden">
          <div
            className={`pt-2 transition-[opacity,transform] duration-300 ease-in-out ${
              open ? 'pointer-events-auto translate-y-0 opacity-100' : 'pointer-events-none -translate-y-1.5 opacity-0'
            }`}
          >
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}


