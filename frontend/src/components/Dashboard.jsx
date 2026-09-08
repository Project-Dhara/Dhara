'use client'

import { ArrowRight } from 'lucide-react'
import Button from './ui/Button'

// Mock dataset-readiness dashboard, ported from the mockup's hardcoded
// `stats` / `datasets` arrays. No backend calls.

const STATS = [
  { label: 'Datasets', value: '12', color: '#F2C230' },
  { label: 'Data products', value: '4', color: '#73A942' },
  { label: 'Awaiting review', value: '3', color: '#D95B68' },
  { label: 'Published', value: '7', color: '#176B6B' },
]

const DATASETS = [
  { name: 'Vital Statistics 2024 — Delhi', source: 'XLSX', product: 'Vital Statistics', pct: 72, status: 'Metadata review', action: 'Review' },
  { name: 'District Population 2024', source: 'SQL', product: 'Population Statistics', pct: 85, status: 'Harmonisation', action: 'Review' },
  { name: 'Employment Survey 2025', source: 'XLSX', product: 'Labour Statistics', pct: 100, status: 'Published', action: 'View' },
  { name: 'Agricultural Production 2024', source: 'CSV', product: 'Agriculture', pct: 64, status: 'Classification review', action: 'Review' },
]

function barColor(pct) {
  if (pct >= 95) return '#3d7a3d'
  if (pct >= 70) return '#9a7413'
  return '#D95B68'
}

const gridCols = 'grid-cols-[2.2fr_0.8fr_1.4fr_1.2fr_1.3fr_0.8fr]'

export default function Dashboard({ onStartFlow }) {
  return (
    <div className="flex flex-col gap-[22px]">
      <div className="flex items-start justify-between">
        <div className="flex flex-col gap-1.5">
          <div className="font-display text-4xl font-medium leading-tight text-ink">Dataset readiness</div>
          <div className="text-xs uppercase tracking-wide text-[#8E9398]">12 datasets · updated today</div>
        </div>
        <Button variant="primary" onClick={onStartFlow}>Upload datasets</Button>
      </div>

      <div className="grid grid-cols-4 gap-3.5">
        {STATS.map((s) => (
          <div className="flex flex-col gap-1.5 rounded-lg border border-line bg-white p-[18px]" key={s.label}>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} />
              <span className="text-xs uppercase tracking-wide text-[#8E9398]">{s.label}</span>
            </div>
            <div className="text-[34px] font-semibold leading-tight text-ink">{s.value}</div>
          </div>
        ))}
      </div>

      <div className="overflow-hidden rounded-lg border border-line bg-white">
        <div className={`grid ${gridCols} items-center gap-4 border-b border-line bg-cream px-5 py-3 text-xs uppercase tracking-wide text-[#8E9398]`}>
          <div>Dataset</div><div>Source</div><div>Data product</div><div>Readiness</div><div>Status</div><div />
        </div>
        {DATASETS.map((row) => (
          <div
            className={`grid ${gridCols} items-center gap-4 border-b border-[#f1ebdf] px-5 py-[15px] text-[15px] transition-colors last:border-b-0 hover:bg-[#FFFCF6] cursor-pointer`}
            key={row.name}
            onClick={onStartFlow}
          >
            <div className="font-semibold text-ink">{row.name}</div>
            <div className="text-xs text-ink-soft">{row.source}</div>
            <div className="text-ink-soft">{row.product}</div>
            <div className="flex items-center gap-2.5">
              <div className="h-[5px] w-16 overflow-hidden rounded-full bg-[#ece4d6]">
                <div className="h-full" style={{ width: `${row.pct}%`, background: barColor(row.pct) }} />
              </div>
              <span className="text-xs font-medium" style={{ color: barColor(row.pct) }}>{row.pct}%</span>
            </div>
            <div>
              <span className={`rounded px-2.5 py-1 text-xs font-semibold ${row.status === 'Published' ? 'bg-sage text-[#3d5230]' : 'bg-[rgba(242,194,48,0.28)] text-[#6b5406]'}`}>
                {row.status}
              </span>
            </div>
            <div className="inline-flex items-center justify-end gap-1 font-semibold text-teal">
              {row.action}
              <ArrowRight className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
