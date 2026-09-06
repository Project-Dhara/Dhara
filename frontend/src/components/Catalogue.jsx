'use client'

import { useEffect, useMemo, useState } from 'react'
import { withAuthHeaders } from '../lib/auth'

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

const metaCardClass = 'flex min-w-0 flex-col gap-1.5 rounded-lg border border-[#f0e7d6] bg-cream p-3 px-3.5'
const metaCardLabelClass = 'text-[10.5px] uppercase tracking-wide text-[#8E9398]'
const tagListClass = 'flex flex-wrap gap-1.5 pt-0.5'
const tagChipClass = 'rounded-full border border-line bg-cream px-2.5 py-1 text-[11.5px] text-ink-soft'
const copyBtnClass = 'flex h-[34px] flex-none items-center rounded-full border border-teal bg-white px-3.5 text-[13px] font-semibold text-teal transition-colors hover:bg-sage'

function MetaCard({ label, value, wide }) {
  const empty = isEmptyMeta(value)
  return (
    <div className={`${metaCardClass} ${wide ? 'col-span-2' : ''}`}>
      <div className={metaCardLabelClass}>{label}</div>
      <div className={`break-words text-sm font-medium leading-snug text-ink ${empty ? 'font-normal italic text-[#a49c8e]' : ''}`}>
        {empty ? 'Not recorded' : value}
      </div>
    </div>
  )
}

function EndpointCard({ label, url, copied, copyLabel, onCopy, hint, children }) {
  return (
    <div className="flex flex-col gap-3">
      {hint && <p className="m-0 text-sm leading-relaxed text-ink-soft">{hint}</p>}
      <div className={`${metaCardClass} col-span-2 gap-2.5`}>
        <div className={metaCardLabelClass}>{label}</div>
        <div className="flex min-w-0 items-center gap-2.5">
          <code className="min-w-0 flex-1 break-all font-mono text-[12.5px] leading-snug text-ink">{url}</code>
          <button type="button" className={copyBtnClass} onClick={onCopy}>
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
    <div className="cat-screen flex flex-1 min-h-0 flex-col gap-3.5 overflow-hidden">
      <div className="flex items-end justify-between gap-6">
        <div>
          <div className="font-display text-[32px] font-medium leading-tight text-ink">Catalogue</div>
          <div className="text-[15px] text-ink-soft">Published releases, their summaries and the endpoints that serve them.</div>
        </div>
        <button
          className="h-10 rounded-full border border-teal bg-white px-4 text-[13px] font-semibold text-teal transition-colors hover:bg-sage"
          onClick={() => setMcpOpen((v) => !v)}
        >
          MCP endpoint
        </button>
      </div>

      {mcpOpen && (
        <div className="flex items-center gap-4 rounded-[10px] bg-teal-deep px-5 py-4">
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="text-[15px] font-semibold text-cream">Catalogue MCP endpoint</div>
            <div className="text-xs text-[#a8bdb3]">{MCP_URL}</div>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {MCP_TOOLS.map((t) => <span className="rounded-full bg-white/[.12] px-2.5 py-[5px] text-xs text-cream" key={t}>{t}</span>)}
          </div>
          <button className={copyBtnClass} onClick={() => copy('mcp', MCP_URL)}>{copied === 'mcp' ? 'Copied' : 'Copy'}</button>
        </div>
      )}

      <div className="flex items-center gap-2.5">
        <input
          className="h-11 min-w-0 flex-1 rounded-md border border-[#ddd3c0] bg-white px-3.5 font-sans text-[15px] text-ink"
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by dataset id, title, geography…"
        />
        <select className="h-11 rounded-md border border-[#ddd3c0] bg-white px-2.5 text-sm text-ink" value={filter} onChange={(e) => setFilter(e.target.value)}>
          {facetOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      <div className="flex flex-1 min-h-0 items-stretch gap-4 overflow-hidden">
        <div className="flex min-h-0 w-[328px] flex-none flex-col gap-2 overflow-hidden">
          <div className="flex flex-none items-center justify-between px-0.5 text-[11.5px] uppercase tracking-wide text-[#8E9398]">
            <span>
              {loading ? 'Loading…' : `${list.length} dataset${list.length !== 1 ? 's' : ''}`}
            </span>
            {(query || filter !== 'all') && (
              <span className="cursor-pointer text-[12.5px] font-semibold text-teal" onClick={() => { setQuery(''); setFilter('all') }}>Clear filter</span>
            )}
          </div>
          <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-0.5">
            {error && <div className="rounded-[10px] border border-dashed border-[#ddd3c0] bg-white p-5 text-sm text-[#8E9398]">{error}</div>}
            {!error && !loading && list.map((d) => (
              <div
                key={d.id}
                className={`flex cursor-pointer flex-col gap-1.5 rounded-lg border p-3 ${
                  d.id === sel?.id ? 'border-teal bg-sage shadow-[inset_0_0_0_1px_#176B6B]' : 'border-line bg-white hover:border-teal hover:bg-cream'
                }`}
                onClick={() => { setSelId(d.id); setTab('summary'); setSummaryChip('ai'); setApiPreviewOpen(false); setMcpPreviewOpen(false) }}
              >
                <div className="flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-green" />
                  <span className="rounded-full border border-[#c9dcc0] bg-white px-2 py-0.5 text-[11px] font-semibold text-teal">{d.id}</span>
                </div>
                <div className="text-[13.5px] font-semibold leading-snug text-ink">{d.title}</div>
                <div className="text-[11.5px] text-[#8E9398]">
                  {[d.geo, d.freq].filter((x) => !isEmptyMeta(x)).join(' · ') || 'Published release'}
                </div>
              </div>
            ))}
            {!error && !loading && list.length === 0 && (
              <div className="rounded-[10px] border border-dashed border-[#ddd3c0] bg-white p-5 text-sm text-[#8E9398]">
                {datasets.length === 0
                  ? 'No published datasets yet. Finish classification and continue to publish.'
                  : 'Nothing matches that search.'}
              </div>
            )}
          </div>
        </div>

        {sel && (
          <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto rounded-[10px] border border-line bg-white">
            <div className="flex flex-col gap-3 border-b border-line px-[22px] pb-4 pt-5">
              <div className="flex items-center gap-2.5">
                <span className="rounded-full border border-[#c9dcc0] bg-sage px-2.5 py-1 text-[12.5px] font-semibold text-teal">{sel.id}</span>
                <span className={`rounded-full px-2.5 py-[3px] text-[11.5px] font-semibold ${access === 'restricted' ? 'bg-[rgba(217,91,104,0.16)] text-[#8c3540]' : 'bg-sage text-[#3d5230]'}`}>{sel.access || 'Public'}</span>
                <span className="ml-auto text-[11.5px] text-[#8E9398]">v1</span>
              </div>
              <div className="text-xl font-semibold leading-tight text-ink">{sel.title}</div>
              <div className="grid grid-cols-[0.6fr_1.2fr_0.8fr_1.4fr] gap-2.5">
                <div className="flex flex-col gap-[3px] rounded-lg border border-[#f0e7d6] bg-cream px-3 py-2.5">
                  <div className="text-[10.5px] uppercase tracking-wide text-[#8E9398]">Rows</div>
                  <div className="text-[13px] font-medium leading-snug text-ink">{sel.rows}</div>
                </div>
                <div className="flex flex-col gap-[3px] rounded-lg border border-[#f0e7d6] bg-cream px-3 py-2.5">
                  <div className="text-[10.5px] uppercase tracking-wide text-[#8E9398]">Geography</div>
                  <div className={`text-[13px] font-medium leading-snug text-ink ${isEmptyMeta(sel.geo) ? 'font-normal italic text-[#a49c8e]' : ''}`}>
                    {isEmptyMeta(sel.geo) ? 'Not recorded' : sel.geo}
                  </div>
                </div>
                <div className="flex flex-col gap-[3px] rounded-lg border border-[#f0e7d6] bg-cream px-3 py-2.5">
                  <div className="text-[10.5px] uppercase tracking-wide text-[#8E9398]">Frequency</div>
                  <div className={`text-[13px] font-medium leading-snug text-ink ${isEmptyMeta(sel.freq) ? 'font-normal italic text-[#a49c8e]' : ''}`}>
                    {isEmptyMeta(sel.freq) ? 'Not recorded' : sel.freq}
                  </div>
                </div>
                <div className="flex flex-col gap-[3px] rounded-lg border border-[#f0e7d6] bg-cream px-3 py-2.5">
                  <div className="text-[10.5px] uppercase tracking-wide text-[#8E9398]">Source</div>
                  <div className={`text-[13px] font-medium leading-snug text-ink ${isEmptyMeta(sel.source) ? 'font-normal italic text-[#a49c8e]' : ''}`}>
                    {isEmptyMeta(sel.source) ? 'Not recorded' : sel.source}
                  </div>
                </div>
              </div>
            </div>

            <div className="flex items-center gap-1 px-[22px] pt-2.5">
              {TABS.map((t) => (
                <div
                  key={t}
                  className={`cursor-pointer border-b-2 px-3 py-2 text-[13.5px] font-semibold ${
                    tab === t ? 'border-teal text-teal' : 'border-transparent text-ink-soft'
                  }`}
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

            <div className="flex flex-col gap-3.5 px-[22px] pb-[22px] pt-[18px]">
              {tab === 'summary' && (
                <div className="flex flex-col gap-3">
                  <div className="flex items-stretch gap-2" role="tablist" aria-label="Summary type">
                    <button
                      type="button"
                      className={`flex h-8 flex-1 items-center justify-center rounded-full border font-sans text-[12.5px] font-semibold transition-colors ${
                        summaryChip === 'ai' ? 'border-teal bg-sage text-ink' : 'border-line bg-white text-ink-soft hover:border-teal hover:text-ink'
                      }`}
                      onClick={() => setSummaryChip('ai')}
                    >
                      AI summary
                    </button>
                    <button
                      type="button"
                      className={`flex h-8 flex-1 items-center justify-center rounded-full border font-sans text-[12.5px] font-semibold transition-colors ${
                        summaryChip === 'nmds' ? 'border-teal bg-sage text-ink' : 'border-line bg-white text-ink-soft hover:border-teal hover:text-ink'
                      }`}
                      onClick={() => setSummaryChip('nmds')}
                    >
                      NMDS concept summary
                    </button>
                  </div>
                  {summaryChip === 'ai' ? (
                    <div className={`${metaCardClass} col-span-2`}>
                      <div className={metaCardLabelClass}>Narrative</div>
                      <div className="text-[15px] leading-relaxed text-ink [text-wrap:pretty]">{sel.summary}</div>
                      {!hasKey && (
                        <button
                          className="mt-2 flex h-9 items-center self-start rounded-full border border-teal bg-white px-3.5 text-[13px] font-semibold text-teal transition-colors hover:bg-sage"
                          onClick={onGoSettings}
                        >
                          Add model key
                        </button>
                      )}
                    </div>
                  ) : (sel.nmds_concepts || []).length === 0 ? (
                    <div className={`${metaCardClass} col-span-2`}>
                      <div className={metaCardLabelClass}>NMDS concepts</div>
                      <div className="text-[15px] leading-relaxed text-ink-soft [text-wrap:pretty]">
                        No NMDS concept details were saved with this release.
                      </div>
                    </div>
                  ) : (
                    <div className="flex max-h-[420px] flex-col gap-2.5 overflow-auto pr-0.5">
                      {(sel.nmds_concepts || []).map((row) => (
                        <div className={`${metaCardClass} col-span-2`} key={`${row.item_no}-${row.concept}`}>
                          <div className="flex items-baseline gap-2 text-[13px] font-semibold text-ink">
                            {row.item_no ? <span className="text-[11.5px] font-semibold tabular-nums text-teal">{row.item_no}</span> : null}
                            {row.concept}
                          </div>
                          <div className="text-sm leading-relaxed text-ink">{row.details}</div>
                        </div>
                      ))}
                    </div>
                  )}
                  {keywords.length > 0 && (
                    <div className="flex flex-col gap-2 rounded-lg border border-line bg-white px-3.5 py-3">
                      <div className={metaCardLabelClass}>Tags</div>
                      <div className={tagListClass}>
                        {keywords.map((t) => <span className={tagChipClass} key={t}>{t}</span>)}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === 'metadata' && (
                <div className="flex flex-col gap-3.5">
                  <div className="flex flex-wrap items-center gap-2.5">
                    <span className="rounded-full border border-[#c9dcc0] bg-sage px-[11px] py-[5px] text-[12.5px] font-semibold text-teal">{sel.id}</span>
                    <span className={`rounded-full px-2.5 py-[3px] text-[11.5px] font-semibold ${access === 'restricted' ? 'bg-[rgba(217,91,104,0.16)] text-[#8c3540]' : 'bg-sage text-[#3d5230]'}`}>{sel.access || 'Public'}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-2.5">
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
                    <div className="flex flex-col gap-2 rounded-lg border border-line bg-white px-3.5 py-3">
                      <div className={metaCardLabelClass}>Keywords</div>
                      <div className={tagListClass}>
                        {keywords.map((t) => (
                          <span className={tagChipClass} key={t}>{t}</span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {tab === 'api' && (
                <div className="flex flex-col gap-3.5">
                  <div className={`${metaCardClass} col-span-2 gap-2.5`}>
                    <div className="text-lg font-bold text-ink">Coming soon</div>
                    <div className="text-sm leading-relaxed text-ink-soft">
                      Live dataset API access is not available yet. Open a preview of the planned endpoint for this release.
                    </div>
                    <button
                      type="button"
                      className="mt-1 self-start rounded-lg border border-teal bg-white px-3.5 py-2 text-[13px] font-semibold text-teal transition-colors hover:bg-cream"
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
                      <div className={`${tagListClass} pt-0`}>
                        <span className={tagChipClass}>GET</span>
                        <span className={tagChipClass}>JSON</span>
                        <span className={tagChipClass}>CSV</span>
                      </div>
                      <div className="flex flex-col gap-1.5 rounded-lg bg-teal-deep px-4 py-3.5">
                        <div className="text-[11px] uppercase tracking-wide text-[#7d9891]">Example</div>
                        <div className="break-all font-mono text-[12.5px] leading-relaxed text-[#e8f0e8]">curl -H "Authorization: Bearer $TOKEN" "{apiUrl}"</div>
                      </div>
                    </EndpointCard>
                  )}
                </div>
              )}

              {tab === 'mcp' && (
                <div className="flex flex-col gap-3.5">
                  <div className={`${metaCardClass} col-span-2 gap-2.5`}>
                    <div className="text-lg font-bold text-ink">Coming soon</div>
                    <div className="text-sm leading-relaxed text-ink-soft">
                      Live MCP access is not available yet. Open a preview of the planned endpoint and tools for this release.
                    </div>
                    <button
                      type="button"
                      className="mt-1 self-start rounded-lg border border-teal bg-white px-3.5 py-2 text-[13px] font-semibold text-teal transition-colors hover:bg-cream"
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
                      <div className="grid grid-cols-1 gap-2.5">
                        {MCP_TOOLS.map((t) => (
                          <div className={metaCardClass} key={t}>
                            <div className={metaCardLabelClass}>Tool</div>
                            <div className="font-mono text-sm font-semibold text-teal">{t}</div>
                            <div className="text-[13.5px] leading-snug text-ink">{TOOL_DESCS[t]}</div>
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