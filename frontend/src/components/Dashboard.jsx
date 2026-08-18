// Mock dataset-readiness dashboard, ported from the mockup's hardcoded
// `stats` / `datasets` arrays. No backend calls.

const STATS = [
  { label: 'Datasets', value: '12', color: 'var(--yellow)' },
  { label: 'Data products', value: '4', color: 'var(--green)' },
  { label: 'Awaiting review', value: '3', color: 'var(--coral)' },
  { label: 'Published', value: '7', color: 'var(--teal)' },
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
  return 'var(--coral)'
}

export default function Dashboard({ onStartFlow }) {
  return (
    <div className="dash">
      <div className="dash-head">
        <div className="dash-head-text">
          <div className="dash-title">Dataset readiness</div>
          <div className="dash-eyebrow">12 datasets · updated today</div>
        </div>
        <button className="dash-upload-btn" onClick={onStartFlow}>Upload datasets</button>
      </div>

      <div className="dash-stats">
        {STATS.map((s) => (
          <div className="dash-stat-card" key={s.label}>
            <div className="dash-stat-head">
              <span className="dash-stat-dot" style={{ background: s.color }} />
              <span className="dash-stat-label">{s.label}</span>
            </div>
            <div className="dash-stat-value">{s.value}</div>
          </div>
        ))}
      </div>

      <div className="dash-table">
        <div className="dash-table-head">
          <div>Dataset</div><div>Source</div><div>Data product</div><div>Readiness</div><div>Status</div><div />
        </div>
        {DATASETS.map((row) => (
          <div className="dash-table-row" key={row.name} onClick={onStartFlow}>
            <div className="dash-row-name">{row.name}</div>
            <div className="dash-row-source">{row.source}</div>
            <div className="dash-row-product">{row.product}</div>
            <div className="dash-row-readiness">
              <div className="dash-bar-track"><div className="dash-bar-fill" style={{ width: `${row.pct}%`, background: barColor(row.pct) }} /></div>
              <span className="dash-pct" style={{ color: barColor(row.pct) }}>{row.pct}%</span>
            </div>
            <div>
              <span className={`dash-badge${row.status === 'Published' ? ' dash-badge-done' : ''}`}>{row.status}</span>
            </div>
            <div className="dash-row-action">{row.action} →</div>
          </div>
        ))}
      </div>
    </div>
  )
}
