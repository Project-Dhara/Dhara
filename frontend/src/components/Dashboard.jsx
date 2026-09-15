'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowRight, CheckCircle2, Clock, Database, Package } from 'lucide-react'
import Button from './ui/Button'
import { withAuthHeaders } from '../lib/auth'

const STAT_META = [
  { key: 'datasets', label: 'Datasets', color: '#F2C230', Icon: Database },
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
  if (!rows?.length) return 'No datasets yet'
  return `${n} dataset${n === 1 ? '' : 's'} · your workspace`
}

const gridCols = 'grid-cols-[2.2fr_0.8fr_1.4fr_1.2fr_1.3fr_0.8fr]'

export default function Dashboard({ onStartFlow }) {
  const router = useRouter()
  const [stats, setStats] = useState(null)
  const [rows, setRows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

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
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load dashboard')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

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
          <div className="font-display text-[28px] font-medium leading-tight tracking-tight text-ink">Dataset readiness</div>
          <div className="text-[12.5px] uppercase tracking-[0.06em] text-ink-soft">
            {loading ? 'Loading…' : subtitleFor(stats, rows)}
          </div>
        </div>
        <Button variant="primary" onClick={onStartFlow}>Upload datasets</Button>
      </div>

      <div className="grid grid-cols-4 gap-3.5">
        {STAT_META.map((s) => (
          <div
            className="dhara-tab dhara-surface group flex cursor-default flex-col gap-3 rounded-2xl border-line/90 bg-surface p-5 hover:border-teal/35 hover:bg-sage hover:shadow-[0_8px_24px_rgba(23,107,107,0.08)]"
            key={s.key}
          >
            <div className="flex items-center gap-2.5">
              <span
                className="flex h-8 w-8 flex-none items-center justify-center rounded-full transition-colors duration-200"
                style={{ background: `${s.color}1F`, color: s.color }}
              >
                <s.Icon className="h-4 w-4" strokeWidth={1.85} aria-hidden />
              </span>
              <span className="text-[11.5px] uppercase tracking-[0.05em] text-ink-soft transition-colors duration-200 group-hover:text-teal-deep">{s.label}</span>
            </div>
            <div className="font-display text-[28px] font-medium leading-none tracking-tight text-ink transition-colors duration-200 group-hover:text-teal-deep">
              {loading ? '—' : String(stats?.[s.key] ?? 0)}
            </div>
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-2xl border border-line/90 bg-surface">
        <div className={`grid ${gridCols} items-center gap-4 border-b border-line/80 bg-cream/70 px-5 py-3 text-[11.5px] uppercase tracking-[0.05em] text-ink-soft`}>
          <div>Dataset</div><div>Source</div><div>Data product</div><div>Readiness</div><div>Status</div><div />
        </div>

        {loading && (
          <div className="px-5 py-10 text-center text-[14px] text-ink-soft">Loading your datasets…</div>
        )}

        {!loading && error && (
          <div className="px-5 py-10 text-center text-[14px] text-[#D95B68]">{error}</div>
        )}

        {!loading && !error && rows.length === 0 && (
          <div className="flex flex-col items-center gap-3 px-5 py-12 text-center">
            <div className="text-[14.5px] text-ink-soft">No datasets in your workspace yet.</div>
            <Button variant="primary" onClick={onStartFlow}>Upload datasets</Button>
          </div>
        )}

        {!loading && !error && rows.map((row) => {
          const pct = Math.max(0, Math.min(100, Number(row.readiness_pct) || 0))
          return (
            <div
              className={`group grid ${gridCols} cursor-pointer items-center gap-4 border-b border-line/50 px-5 py-3.5 text-[14.5px] transition-all duration-dhara ease-dhara last:border-b-0 hover:bg-sage/40`}
              key={row.id || row.name}
              onClick={() => openRow(row)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') openRow(row) }}
              role="link"
              tabIndex={0}
            >
              <div className="font-semibold tracking-tight text-ink">{row.name}</div>
              <div className="text-[12.5px] text-ink-soft">{row.source}</div>
              <div className="text-ink-soft">{row.product || '—'}</div>
              <div className="flex items-center gap-2.5">
                <div className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
                  <div className="h-full rounded-full transition-[width] duration-500 ease-out" style={{ width: `${pct}%`, background: barColor(pct) }} />
                </div>
                <span className="text-[12px] font-medium tabular-nums" style={{ color: pct >= 95 ? '#12403E' : pct >= 70 ? '#8a6116' : '#D95B68' }}>{pct}%</span>
              </div>
              <div>
                <span className={`rounded-full px-2.5 py-1 text-[11.5px] font-semibold ${statusClass(row.status)}`}>
                  {row.status}
                </span>
              </div>
              <div className="inline-flex items-center justify-end gap-1 text-[13.5px] font-semibold text-teal transition-transform duration-150 group-hover:translate-x-0.5">
                {row.action || 'Open'}
                <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
