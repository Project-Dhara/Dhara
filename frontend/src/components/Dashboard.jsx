'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ArrowRight, CheckCircle2, Clock, Database, Package } from 'lucide-react'
import Button from './ui/Button'
import { withAuthHeaders } from '../lib/auth'

const PAGE_SIZE = 5

const STAT_META = [
  { key: 'datasets', label: 'Uploads', color: '#F2C230', Icon: Database },
  { key: 'data_products', label: 'Data products', color: '#73A942', Icon: Package },
  { key: 'awaiting_review', label: 'Awaiting review', color: '#D95B68', Icon: Clock },
  { key: 'published', label: 'Published', color: '#12403E', Icon: CheckCircle2 },
]

function barColor(pct) {
  if (pct >= 95) return '#12403E'
  if (pct >= 70) return '#F2C230'
  return '#D95B68'
}

function statusClass(status) {
  if (status === 'Published') return 'bg-sage text-teal'
  if (status === 'Failed') return 'bg-[#f8d7da] text-[#842029]'
  if (status === 'Processing') return 'bg-[#e8f1f8] text-[#2b6cb0]'
  return 'bg-yellow/25 text-[#6b5406]'
}

function subtitleFor(stats, rows) {
  const n = stats?.datasets ?? rows?.length ?? 0
  if (!rows?.length) return 'No uploads yet'
  return `your workspace`
}

// minmax(0, …) so long filenames wrap inside the column instead of shoving neighbors.
const gridCols = 'grid-cols-[minmax(0,2.4fr)_minmax(0,0.7fr)_minmax(0,1.3fr)_minmax(0,1.1fr)_minmax(0,1.2fr)_minmax(0,0.7fr)]'
const cellWrap = 'min-w-0 break-words'

export default function Dashboard({ onStartFlow }) {
  const router = useRouter()
  const [stats, setStats] = useState(null)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(0)
  const [pageDir, setPageDir] = useState(1)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch('/api/dashboard', withAuthHeaders())
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text()
          throw new Error(text || `Could not load dashboard (${res.status})`)
        }
        return res.json()
      })
      .then((data) => {
        if (cancelled) return
        setStats(data.stats || {})
        setRows(Array.isArray(data.rows) ? data.rows : [])
        setPage(0)
        setPageDir(1)
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load dashboard')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE))
  const currentPage = Math.min(page, pageCount - 1)
  const pageStart = currentPage * PAGE_SIZE
  const pageEnd = Math.min(pageStart + PAGE_SIZE, rows.length)
  const pageRows = rows.slice(pageStart, pageEnd)
  const pageAnim = pageDir >= 0 ? 'dhara-carousel-panel-forward' : 'dhara-carousel-panel-back'

  const goToPage = (next) => {
    const clamped = Math.max(0, Math.min(pageCount - 1, next))
    if (clamped === currentPage) return
    setPageDir(clamped > currentPage ? 1 : -1)
    setPage(clamped)
  }

  const openRow = (row) => {
    if (row?.href) {
      router.push(row.href)
      return
    }
    onStartFlow?.()
  }

  return (
    <div className="flex flex-col gap-7">
      <div className="flex items-start justify-between gap-6">
        <div className="flex flex-col gap-1.5">
          <div className="font-display text-[28px] font-medium leading-tight tracking-tight text-ink">Dashboard</div>
          <div className="text-[12.5px] uppercase tracking-[0.06em] text-ink-soft">
            {loading ? 'Loading…' : subtitleFor(stats, rows)}
          </div>
        </div>
        <Button variant="primary" onClick={onStartFlow}>Upload datasets</Button>
      </div>

      <div className="grid grid-cols-4 gap-3">
        {STAT_META.map((s) => (
          <div
            className="dhara-tab dhara-surface group flex cursor-default items-center justify-between gap-3 rounded-2xl border-line/90 bg-surface px-4 py-3.5 hover:border-teal/35 hover:bg-sage hover:shadow-[0_8px_24px_rgba(23,107,107,0.08)]"
            key={s.key}
          >
            <div className="flex min-w-0 items-center gap-2.5">
              <span
                className="flex h-8 w-8 flex-none items-center justify-center rounded-full transition-colors duration-200"
                style={{ background: `${s.color}1F`, color: s.color }}
              >
                <s.Icon className="h-4 w-4" strokeWidth={1.85} aria-hidden />
              </span>
              <span className="truncate text-[11.5px] uppercase tracking-[0.05em] text-ink-soft transition-colors duration-200 group-hover:text-teal-deep">{s.label}</span>
            </div>
            <div className="font-display flex-none text-[26px] font-medium leading-none tracking-tight text-ink tabular-nums transition-colors duration-200 group-hover:text-teal-deep">
              {loading ? '—' : String(stats?.[s.key] ?? 0)}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-3">
        {!loading && !error && rows.length > 0 && (
          <div className="flex h-8 flex-none flex-wrap items-center justify-between gap-3">
            <div className="text-[12.5px] text-ink-soft">
              Showing {pageStart + 1}–{pageEnd} of {rows.length}
              {' · '}{PAGE_SIZE} per page
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line bg-white text-ink-soft hover:border-teal hover:text-teal disabled:cursor-not-allowed disabled:opacity-35"
                disabled={currentPage <= 0}
                aria-label="Previous page"
                title="Previous page"
                onClick={() => goToPage(currentPage - 1)}
              >
                <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              </button>
              <span className="min-w-[5.5rem] text-center text-[12.5px] font-semibold tabular-nums text-ink">
                {currentPage + 1} / {pageCount}
              </span>
              <button
                type="button"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line bg-white text-ink-soft hover:border-teal hover:text-teal disabled:cursor-not-allowed disabled:opacity-35"
                disabled={currentPage >= pageCount - 1}
                aria-label="Next page"
                title="Next page"
                onClick={() => goToPage(currentPage + 1)}
              >
                <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
              </button>
            </div>
          </div>
        )}

        <div className="overflow-hidden rounded-2xl border border-line/90 bg-surface">
          <div className={`grid ${gridCols} items-center gap-4 border-b border-line/80 bg-cream/70 px-5 py-3 text-[11.5px] uppercase tracking-[0.05em] text-ink-soft`}>
            <div className={cellWrap}>Uploaded file</div>
            <div className={cellWrap}>Source</div>
            <div className={cellWrap}>Data product</div>
            <div className={cellWrap}>Readiness</div>
            <div className={cellWrap}>Status</div>
            <div />
          </div>

          {loading && (
            <div className="px-5 py-10 text-center text-[14px] text-ink-soft">Loading your uploads…</div>
          )}

          {!loading && error && (
            <div className="px-5 py-10 text-center text-[14px] text-[#D95B68]">{error}</div>
          )}

          {!loading && !error && rows.length === 0 && (
            <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
              <div className="text-[14.5px] text-ink-soft">No uploads in your workspace yet.</div>
              <Button variant="primary" onClick={onStartFlow}>Upload datasets</Button>
            </div>
          )}

          {!loading && !error && rows.length > 0 && (
            <div key={currentPage} className={pageAnim}>
              {pageRows.map((row, idx) => {
                const pct = Math.max(0, Math.min(100, Number(row.readiness_pct) || 0))
                const isLast = idx === pageRows.length - 1
                return (
                  <div
                    className={`group grid ${gridCols} cursor-pointer items-start gap-4 border-b border-line/50 px-5 py-3.5 text-[14.5px] transition-colors duration-dhara ease-dhara hover:bg-sage/40 ${isLast ? 'border-b-0' : ''}`}
                    key={row.id || row.name}
                    onClick={() => openRow(row)}
                    onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') openRow(row) }}
                    role="link"
                    tabIndex={0}
                  >
                    <div className="min-w-0 break-all font-semibold leading-snug tracking-tight text-ink">{row.name}</div>
                    <div className={`${cellWrap} text-[12.5px] text-ink-soft`}>{row.source}</div>
                    <div className={`${cellWrap} leading-snug text-ink-soft`}>{row.product || '—'}</div>
                    <div className={`${cellWrap} flex items-center gap-2.5 pt-0.5`}>
                      <div className="h-1.5 w-16 flex-none overflow-hidden rounded-full bg-line">
                        <div className="h-full rounded-full transition-[width] duration-500 ease-out" style={{ width: `${pct}%`, background: barColor(pct) }} />
                      </div>
                      <span className="text-[12px] font-medium tabular-nums" style={{ color: pct >= 95 ? '#12403E' : pct >= 70 ? '#8a6116' : '#D95B68' }}>{pct}%</span>
                    </div>
                    <div className={cellWrap}>
                      <span className={`inline-block rounded-full px-2.5 py-1 text-[11.5px] font-semibold leading-snug ${statusClass(row.status)}`}>
                        {row.status}
                      </span>
                    </div>
                    <div className={`${cellWrap} inline-flex items-center justify-end gap-1 pt-0.5 text-[13.5px] font-semibold text-teal transition-transform duration-150 group-hover:translate-x-0.5`}>
                      {row.action || 'Open'}
                      <ArrowRight className="h-3.5 w-3.5 flex-none" strokeWidth={2} aria-hidden />
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
