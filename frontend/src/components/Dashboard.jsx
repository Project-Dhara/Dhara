'use client'

import { ArrowRight, CheckCircle2, Clock, Database, Package } from 'lucide-react'
import Button from './ui/Button'

// Mock dataset-readiness dashboard, ported from the mockup's hardcoded
// `stats` / `datasets` arrays. No backend calls.

const STATS = [
  { label: 'Datasets', value: '12', color: '#F2C230', Icon: Database },
  { label: 'Data products', value: '4', color: '#73A942', Icon: Package },
  { label: 'Awaiting review', value: '3', color: '#D95B68', Icon: Clock },
  { label: 'Published', value: '7', color: '#12403E', Icon: CheckCircle2 },
]

const DATASETS = [
  { name: 'Vital Statistics 2024 — Delhi', source: 'XLSX', product: 'Vital Statistics', pct: 72, status: 'Metadata review', action: 'Review' },
  { name: 'District Population 2024', source: 'SQL', product: 'Population Statistics', pct: 85, status: 'Harmonisation', action: 'Review' },
  { name: 'Employment Survey 2025', source: 'XLSX', product: 'Labour Statistics', pct: 100, status: 'Published', action: 'View' },
  { name: 'Agricultural Production 2024', source: 'CSV', product: 'Agriculture', pct: 64, status: 'Classification review', action: 'Review' },
]

function barColor(pct) {
  if (pct >= 95) return '#12403E'
  if (pct >= 70) return '#F2C230'
  return '#D95B68'
}

const gridCols = 'grid-cols-[2.2fr_0.8fr_1.4fr_1.2fr_1.3fr_0.8fr]'

export default function Dashboard({ onStartFlow }) {
  return (
    <div className="flex flex-col gap-7">
      <div className="flex items-start justify-between gap-6">
        <div className="flex flex-col gap-1.5">
          <div className="font-display text-[28px] font-medium leading-tight tracking-tight text-ink">Dataset readiness</div>
          <div className="text-[12.5px] uppercase tracking-[0.06em] text-ink-soft">12 datasets · updated today</div>
        </div>
        <Button variant="primary" onClick={onStartFlow}>Upload datasets</Button>
      </div>

      <div className="grid grid-cols-4 gap-3.5">
        {STATS.map((s) => (
          <div
            className="dhara-tab dhara-surface group flex cursor-default flex-col gap-3 rounded-2xl border-line/90 bg-surface p-5 hover:border-teal/35 hover:bg-sage hover:shadow-[0_8px_24px_rgba(23,107,107,0.08)]"
            key={s.label}
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
            <div className="font-display text-[28px] font-medium leading-none tracking-tight text-ink transition-colors duration-200 group-hover:text-teal-deep">{s.value}</div>
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-2xl border border-line/90 bg-surface">
        <div className={`grid ${gridCols} items-center gap-4 border-b border-line/80 bg-cream/70 px-5 py-3 text-[11.5px] uppercase tracking-[0.05em] text-ink-soft`}>
          <div>Dataset</div><div>Source</div><div>Data product</div><div>Readiness</div><div>Status</div><div />
        </div>
        {DATASETS.map((row) => (
          <div
            className={`group grid ${gridCols} cursor-pointer items-center gap-4 border-b border-line/50 px-5 py-3.5 text-[14.5px] transition-all duration-dhara ease-dhara last:border-b-0 hover:bg-sage/40`}
            key={row.name}
            onClick={onStartFlow}
          >
            <div className="font-semibold tracking-tight text-ink">{row.name}</div>
            <div className="text-[12.5px] text-ink-soft">{row.source}</div>
            <div className="text-ink-soft">{row.product}</div>
            <div className="flex items-center gap-2.5">
              <div className="h-1.5 w-16 overflow-hidden rounded-full bg-line">
                <div className="h-full rounded-full transition-[width] duration-500 ease-out" style={{ width: `${row.pct}%`, background: barColor(row.pct) }} />
              </div>
              <span className="text-[12px] font-medium tabular-nums" style={{ color: row.pct >= 95 ? '#12403E' : row.pct >= 70 ? '#8a6116' : '#D95B68' }}>{row.pct}%</span>
            </div>
            <div>
              <span className={`rounded-full px-2.5 py-1 text-[11.5px] font-semibold ${row.status === 'Published' ? 'bg-sage text-teal' : 'bg-yellow/25 text-[#6b5406]'}`}>
                {row.status}
              </span>
            </div>
            <div className="inline-flex items-center justify-end gap-1 text-[13.5px] font-semibold text-teal transition-transform duration-150 group-hover:translate-x-0.5">
              {row.action}
              <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
