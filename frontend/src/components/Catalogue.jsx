import { useEffect, useMemo, useState } from 'react'
import { withAuthHeaders } from '../auth'

const MCP_TOOLS = ['search_datasets', 'get_table', 'get_metadata']
const TOOL_DESCS = {
  search_datasets: 'Find releases by keyword, geography or time period.',
  get_table: 'Return rows of a published table, with optional filters.',
  get_metadata: 'Return the NMDS metadata record for a release.',
}
const MCP_URL = 'https://catalogue.dhara.people+ai.org/mcp'

const TABS = ['summary', 'metadata', 'api', 'mcp']

function labelFacet(key) {
  return String(key).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

function isEmptyMeta(v) {
  return v == null || String(v).trim() === '' || String(v).trim() === '—'
}

function keywordChips(sel) {
  const fromTags = (sel.tags || []).filter((t) => !isEmptyMeta(t))
  if (fromTags.length) return [...new Set(fromTags)]
  return [...new Set(
    String(sel.keywords || '')
      .split(/\s+/)
      .map((w) => w.trim())
      .filter((w) => w && w !== '—' && w.length > 1)
  )]
}

function MetaCard({ label, value, wide }) {
  const empty = isEmptyMeta(value)
  return (
    <div className={`cat-meta-card${wide ? ' cat-meta-card-wide' : ''}`}>
      <div className="cat-meta-card-label">{label}</div>
      <div className={`cat-meta-card-value${empty ? ' cat-meta-card-empty' : ''}`}>
        {empty ? 'Not recorded' : value}
      </div>
    </div>
  )
}

function EndpointCard({ label, url, copied, copyLabel, onCopy, hint, children }) {
  return (
    <div className="cat-endpoint">
      {hint && <p className="cat-api-hint">{hint}</p>}
      <div className="cat-meta-card cat-meta-card-wide cat-endpoint-card">
        <div className="cat-meta-card-label">{label}</div>
        <div className="cat-endpoint-row">
          <code className="cat-endpoint-url">{url}</code>
          <button type="button" className="cat-copy-btn" onClick={onCopy}>
            {copied === copyLabel ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>
      {children}
    </div>
  )
}

export default function Catalogue({ hasKey, onGoSettings }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [selId, setSelId] = useState(null)
  const [tab, setTab] = useState('summary')
  const [summaryChip, setSummaryChip] = useState('ai')
  const [mcpOpen, setMcpOpen] = useState(false)
  const [copied, setCopied] = useState(null)
  const [apiPreviewOpen, setApiPreviewOpen] = useState(false)
  const [mcpPreviewOpen, setMcpPreviewOpen] = useState(false)
  const [datasets, setDatasets] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    fetch('/api/catalogue/datasets', withAuthHeaders())
      .then(async (res) => {
        if (!res.ok) {
          const text = await res.text()
          throw new Error(text || `Could not load catalogue (${res.status})`)
        }
        return res.json()
      })
      .then((data) => {
        if (cancelled) return
        const rows = data.datasets || []
        setDatasets(rows)
        setSelId((prev) => (prev && rows.some((r) => r.id === prev) ? prev : rows[0]?.id || null))
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Could not load catalogue')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [])

  const facetOptions = useMemo(() => {
    const keys = new Set()
    datasets.forEach((d) => (d.facets || []).forEach((f) => keys.add(f)))
    return [
      { value: 'all', label: 'All facets' },
      ...[...keys].sort().map((k) => ({ value: k, label: labelFacet(k) })),
    ]
  }, [datasets])

  const q = query.trim().toLowerCase()
  const list = datasets.filter((r) =>
    (filter === 'all' || (r.facets || []).includes(filter)) &&
    (!q || `${r.id} ${r.title} ${r.keywords} ${r.geo}`.toLowerCase().includes(q))
  )
  const sel = list.find((r) => r.id === selId) || list[0]
  const access = (sel?.access || 'Public').toLowerCase()
  const keywords = sel ? keywordChips(sel) : []

  const copy = (label, text) => {
    navigator.clipboard?.writeText(text).catch(() => {})
    setCopied(label)
    setTimeout(() => setCopied(null), 1500)
  }

  const apiUrl = sel ? `https://catalogue.dhara.people+ai.org/api/datasets/${sel.id}` : ''

  return (
    <div className="cat-screen">
      <div className="cat-head">
        <div>
          <div className="cat-title">Catalogue</div>
          <div className="cat-sub">Published releases, their summaries and the endpoints that serve them.</div>
        </div>
        <button className="cat-mcp-pill" onClick={() => setMcpOpen((v) => !v)}>MCP endpoint</button>
      </div>

      {mcpOpen && (
        <div className="cat-mcp-panel">
          <div className="cat-mcp-panel-text">
            <div className="cat-mcp-panel-title">Catalogue MCP endpoint</div>
            <div className="cat-mcp-panel-url">{MCP_URL}</div>
          </div>
          <div className="cat-mcp-tools">
            {MCP_TOOLS.map((t) => <span className="cat-mcp-tool-chip" key={t}>{t}</span>)}
          </div>
          <button className="cat-copy-btn" onClick={() => copy('mcp', MCP_URL)}>{copied === 'mcp' ? 'Copied' : 'Copy'}</button>
        </div>
      )}

      <div className="cat-search-row">
        <input
          className="cat-search-input"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by dataset id, title, geography…"
        />
        <select className="cat-filter-select" value={filter} onChange={(e) => setFilter(e.target.value)}>
          {facetOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      <div className="cat-body">
        <div className="cat-list">
          <div className="cat-list-head">
            <span>
              {loading ? 'Loading…' : `${list.length} dataset${list.length !== 1 ? 's' : ''}`}
            </span>
            {(query || filter !== 'all') && (
              <span className="cat-clear" onClick={() => { setQuery(''); setFilter('all') }}>Clear filter</span>
            )}
          </div>
          <div className="cat-list-scroll">
            {error && <div className="cat-empty">{error}</div>}
            {!error && !loading && list.map((d) => (
              <div
                key={d.id}
                className={`cat-list-row${d.id === sel?.id ? ' cat-list-row-active' : ''}`}
                onClick={() => { setSelId(d.id); setTab('summary'); setSummaryChip('ai'); setApiPreviewOpen(false); setMcpPreviewOpen(false) }}
              >
                <div className="cat-list-row-top">
                  <span className="cat-list-dot" />
                  <span className="cat-list-id">{d.id}</span>
                </div>
                <div className="cat-list-title">{d.title}</div>
                <div className="cat-list-meta">
                  {[d.geo, d.freq].filter((x) => !isEmptyMeta(x)).join(' · ') || 'Published release'}
                </div>
              </div>
            ))}
            {!error && !loading && list.length === 0 && (
              <div className="cat-empty">
                {datasets.length === 0
                  ? 'No published datasets yet. Finish classification and continue to publish.'
                  : 'Nothing matches that search.'}
              </div>
            )}
          </div>
        </div>

        {sel && (
          <div className="cat-detail">
            <div className="cat-detail-head">
              <div className="cat-detail-top">
                <span className="cat-detail-id">{sel.id}</span>
                <span className={`cat-access-pill cat-access-${access}`}>{sel.access || 'Public'}</span>
                <span className="cat-detail-version">v1</span>
              </div>
              <div className="cat-detail-title">{sel.title}</div>
              <div className="cat-fact-grid">
                <div className="cat-fact">
                  <div className="cat-fact-label">Rows</div>
                  <div className="cat-fact-value">{sel.rows}</div>
                </div>
                <div className="cat-fact">
                  <div className="cat-fact-label">Geography</div>
                  <div className={`cat-fact-value${isEmptyMeta(sel.geo) ? ' cat-meta-card-empty' : ''}`}>
                    {isEmptyMeta(sel.geo) ? 'Not recorded' : sel.geo}
                  </div>
                </div>
                <div className="cat-fact">
                  <div className="cat-fact-label">Frequency</div>
                  <div className={`cat-fact-value${isEmptyMeta(sel.freq) ? ' cat-meta-card-empty' : ''}`}>
                    {isEmptyMeta(sel.freq) ? 'Not recorded' : sel.freq}
                  </div>
                </div>
                <div className="cat-fact">
                  <div className="cat-fact-label">Source</div>
                  <div className={`cat-fact-value${isEmptyMeta(sel.source) ? ' cat-meta-card-empty' : ''}`}>
                    {isEmptyMeta(sel.source) ? 'Not recorded' : sel.source}
                  </div>
                </div>
              </div>
            </div>

            <div className="cat-tabs">
              {TABS.map((t) => (
                <div
                  key={t}
                  className={`cat-tab${tab === t ? ' cat-tab-active' : ''}`}
                  onClick={() => {
                    setTab(t)
                    if (t !== 'api') setApiPreviewOpen(false)
                    if (t !== 'mcp') setMcpPreviewOpen(false)
                  }}
                >
                  {t[0].toUpperCase() + t.slice(1)}
                </div>
              ))}
            </div>

            <div className="cat-tab-body">
              {tab === 'summary' && (
                <div className="cat-summary">
                  <div className="cat-summary-chips" role="tablist" aria-label="Summary type">
                    <button
                      type="button"
                      className={`cat-summary-chip${summaryChip === 'ai' ? ' cat-summary-chip-active' : ''}`}
                      onClick={() => setSummaryChip('ai')}
                    >
                      AI summary
                    </button>
                    <button
                      type="button"
                      className={`cat-summary-chip${summaryChip === 'nmds' ? ' cat-summary-chip-active' : ''}`}
                      onClick={() => setSummaryChip('nmds')}
                    >
                      NMDS concept summary
                    </button>
                  </div>
                  {summaryChip === 'ai' ? (
                    <div className="cat-meta-card cat-meta-card-wide">
                      <div className="cat-meta-card-label">Narrative</div>
                      <div className="cat-summary-text">{sel.summary}</div>
                      {!hasKey && <button className="cat-key-btn" onClick={onGoSettings}>Add model key</button>}
                    </div>
                  ) : (sel.nmds_concepts || []).length === 0 ? (
                    <div className="cat-meta-card cat-meta-card-wide">
                      <div className="cat-meta-card-label">NMDS concepts</div>
                      <div className="cat-summary-text cat-nmds-empty">
                        No NMDS concept details were saved with this release.
                      </div>
                    </div>
                  ) : (
                    <div className="cat-nmds-list">
                      {(sel.nmds_concepts || []).map((row) => (
                        <div className="cat-meta-card cat-meta-card-wide" key={`${row.item_no}-${row.concept}`}>
                          <div className="cat-nmds-concept">
                            {row.item_no ? <span className="cat-nmds-no">{row.item_no}</span> : null}
                            {row.concept}
                          </div>
                          <div className="cat-nmds-details">{row.details}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  {keywords.length > 0 && (
                    <div className="cat-meta-keywords">
                      <div className="cat-meta-card-label">Tags</div>
                      <div className="cat-tag-list">
                        {keywords.map((t) => <span className="cat-tag-chip" key={t}>{t}</span>)}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === 'metadata' && (
                <div className="cat-meta">
                  <div className="cat-meta-id-bar">
                    <span className="cat-meta-id">{sel.id}</span>
                    <span className={`cat-access-pill cat-access-${access}`}>{sel.access || 'Public'}</span>
                  </div>
                  <div className="cat-meta-grid">
                    <MetaCard label="Title" value={sel.title} wide />
                    <MetaCard label="Rows" value={sel.rows} />
                    <MetaCard label="Geography" value={sel.geo} />
                    <MetaCard label="Frequency" value={sel.freq} />
                    <MetaCard label="Time period" value={sel.time_period} />
                    <MetaCard label="Data source" value={sel.source} wide />
                    <MetaCard label="Theme" value={sel.theme} />
                    <MetaCard label="Product" value={sel.product} />
                  </div>
                  {keywords.length > 0 && (
                    <div className="cat-meta-keywords">
                      <div className="cat-meta-card-label">Keywords</div>
                      <div className="cat-tag-list">
                        {keywords.map((t) => (
                          <span className="cat-tag-chip" key={t}>{t}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === 'api' && (
                <div className="cat-api-soon">
                  <div className="cat-meta-card cat-meta-card-wide cat-api-soon-card">
                    <div className="cat-api-soon-title">Coming soon</div>
                    <div className="cat-api-soon-blurb">
                      Live dataset API access is not available yet. Open a preview of the planned endpoint for this release.
                    </div>
                    <button
                      type="button"
                      className="cat-api-preview-btn"
                      onClick={() => setApiPreviewOpen((v) => !v)}
                      aria-expanded={apiPreviewOpen}
                    >
                      {apiPreviewOpen ? 'Hide preview' : 'Preview'}
                    </button>
                  </div>
                  {apiPreviewOpen && (
                    <EndpointCard
                      label="Dataset endpoint"
                      url={apiUrl}
                      copied={copied}
                      copyLabel="api"
                      onCopy={() => copy('api', apiUrl)}
                      hint="Fetch the harmonised table as JSON. Add ?format=csv for a flat file."
                    >
                      <div className="cat-tag-list cat-api-formats">
                        <span className="cat-tag-chip">GET</span>
                        <span className="cat-tag-chip">JSON</span>
                        <span className="cat-tag-chip">CSV</span>
                      </div>
                      <div className="cat-example-box">
                        <div className="cat-example-label">Example</div>
                        <div className="cat-example-code">curl -H "Authorization: Bearer $TOKEN" "{apiUrl}"</div>
                      </div>
                    </EndpointCard>
                  )}
                </div>
              )}

              {tab === 'mcp' && (
                <div className="cat-api-soon">
                  <div className="cat-meta-card cat-meta-card-wide cat-api-soon-card">
                    <div className="cat-api-soon-title">Coming soon</div>
                    <div className="cat-api-soon-blurb">
                      Live MCP access is not available yet. Open a preview of the planned endpoint and tools for this release.
                    </div>
                    <button
                      type="button"
                      className="cat-api-preview-btn"
                      onClick={() => setMcpPreviewOpen((v) => !v)}
                      aria-expanded={mcpPreviewOpen}
                    >
                      {mcpPreviewOpen ? 'Hide preview' : 'Preview'}
                    </button>
                  </div>
                  {mcpPreviewOpen && (
                    <EndpointCard
                      label="MCP endpoint"
                      url={MCP_URL}
                      copied={copied}
                      copyLabel="mcp2"
                      onCopy={() => copy('mcp2', MCP_URL)}
                      hint="Add this endpoint to an assistant so it can find and read this release."
                    >
                      <div className="cat-mcp-tools-grid">
                        {MCP_TOOLS.map((t) => (
                          <div className="cat-meta-card" key={t}>
                            <div className="cat-meta-card-label">Tool</div>
                            <div className="cat-tool-name">{t}</div>
                            <div className="cat-tool-desc">{TOOL_DESCS[t]}</div>
                          </div>
                        ))}
                      </div>
                    </EndpointCard>
                  )}
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
