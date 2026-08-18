import { useState } from 'react'

// Mock searchable dataset list + detail panel, ported from the mockup's
// CAT_DEFS / TAGS / MCP_TOOLS data. No calls to /api/catalogue/groups —
// this is a presentational preview of the catalogue experience.

const CAT_DEFS = [
  { id: 'DDI_DEL_DES_VS_2024_V1', title: 'Population, registration units, monthly returns due and received',
    rows: '3', geo: 'National Capital Territory (NCT) of Delhi', freq: 'Annual',
    source: 'Civil Registration System (CRS) — birth registration records', access: 'Public',
    summary: 'Annual counts of population, registration units and monthly returns due and received for the NCT of Delhi, 2024. Three rows cover rural, urban and combined areas. Compiled from the Civil Registration System; return figures are useful for judging registration coverage before reading any birth or death table in this product.',
    keywords: 'births registration returns population delhi annual', facets: ['area', 'place_of_occurence'] },
  { id: 'DDI_DEL_DES_VS_B10_RURAL_2024_V1', title: 'Live births by level of education of father and birth order (rural)',
    rows: '7', geo: 'National Capital Territory (NCT) of Delhi', freq: 'Annual',
    source: 'Civil Registration System (CRS) — birth registration records', access: 'Public',
    summary: "Registered live births in rural Delhi for 2024, cross-tabulated by the father's level of education and the birth order of the child. Seven education levels run from illiterate to graduate and above; birth order runs one to four and above. Counts are of registered events, not survey estimates.",
    keywords: 'births education father birth order rural delhi', facets: ['area', 'place_of_occurence'] },
  { id: 'DDI_DEL_DES_VS_D07_OCC_2024_V1', title: 'Registered deaths by occupation, sex and age group',
    rows: '42', geo: 'National Capital Territory (NCT) of Delhi', freq: 'Annual',
    source: 'Civil Registration System (CRS) — death registration records', access: 'Public',
    summary: 'Registered deaths in Delhi for 2024 by occupation of the deceased, sex and age group. Occupation values are harmonised to NCO-2015 divisions and age is reported in standard bands. Sex includes a third category, which is sparsely populated.',
    keywords: 'deaths occupation sex age group nco delhi', facets: ['gender', 'age_group', 'occupation', 'place_of_occurence'] },
  { id: 'DDI_DEL_EMP_2024_V2_T1', title: 'Workers by district, sector and wage band',
    rows: '128', geo: 'Districts of Delhi (11)', freq: 'Annual',
    source: 'Directorate of Economics and Statistics — employment survey', access: 'Restricted',
    summary: "District-level worker counts for Delhi, 2024, split by sector and wage band. District names are matched to LGD codes; wage bands follow the department's own five-band scheme rather than a national standard, so comparisons across states need care.",
    keywords: 'workers district sector wage employment labour', facets: ['area', 'gender', 'occupation'] },
]

const TAGS = ['births', 'registration', 'sex', 'age group', 'occupation', 'Delhi', 'CRS', 'annual']
const MCP_TOOLS = ['search_datasets', 'get_table', 'get_metadata']
const TOOL_DESCS = {
  search_datasets: 'Find releases by keyword, geography or time period.',
  get_table: 'Return rows of a published table, with optional filters.',
  get_metadata: 'Return the NMDS metadata record for a release.',
}
const MCP_URL = 'https://catalogue.dhara.ekstep.org/mcp'

const FACET_OPTIONS = [
  { value: 'all', label: 'All facets' },
  { value: 'area', label: 'Area' },
  { value: 'gender', label: 'Gender' },
  { value: 'age_group', label: 'Age group' },
  { value: 'occupation', label: 'Occupation' },
  { value: 'place_of_occurence', label: 'Place of occurrence' },
]

const TABS = ['summary', 'metadata', 'api', 'mcp']

export default function Catalogue({ hasKey, onGoSettings }) {
  const [query, setQuery] = useState('')
  const [filter, setFilter] = useState('all')
  const [selId, setSelId] = useState(CAT_DEFS[0].id)
  const [tab, setTab] = useState('summary')
  const [mcpOpen, setMcpOpen] = useState(false)
  const [copied, setCopied] = useState(null)

  const q = query.trim().toLowerCase()
  const list = CAT_DEFS.filter((r) =>
    (filter === 'all' || (r.facets || []).includes(filter)) &&
    (!q || `${r.id} ${r.title} ${r.keywords} ${r.geo}`.toLowerCase().includes(q))
  )
  const sel = list.find((r) => r.id === selId) || list[0]

  const copy = (label, text) => {
    navigator.clipboard?.writeText(text).catch(() => {})
    setCopied(label)
    setTimeout(() => setCopied(null), 1500)
  }

  const apiUrl = sel ? `https://catalogue.dhara.ekstep.org/api/datasets/${sel.id}` : ''

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
          placeholder="Search by dataset id, title, district, cause, occupation…"
        />
        <select className="cat-filter-select" value={filter} onChange={(e) => setFilter(e.target.value)}>
          {FACET_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>

      <div className="cat-body">
        <div className="cat-list">
          <div className="cat-list-head">
            <span>{list.length} dataset{list.length !== 1 ? 's' : ''}</span>
            {(query || filter !== 'all') && (
              <span className="cat-clear" onClick={() => { setQuery(''); setFilter('all') }}>Clear filter</span>
            )}
          </div>
          {list.map((d) => (
            <div
              key={d.id}
              className={`cat-list-row${d.id === sel?.id ? ' cat-list-row-active' : ''}`}
              onClick={() => { setSelId(d.id); setTab('summary') }}
            >
              <div className="cat-list-row-top">
                <span className="cat-list-dot" />
                <span className="cat-list-id">{d.id}</span>
              </div>
              <div className="cat-list-title">{d.title}</div>
              <div className="cat-list-meta">{d.geo} · {d.freq}</div>
            </div>
          ))}
          {list.length === 0 && (
            <div className="cat-empty">Nothing matches that search. Try a district, a cause or an occupation.</div>
          )}
        </div>

        {sel && (
          <div className="cat-detail">
            <div className="cat-detail-head">
              <div className="cat-detail-top">
                <span className="cat-detail-id">{sel.id}</span>
                <span className={`cat-access-pill cat-access-${sel.access.toLowerCase()}`}>{sel.access}</span>
                <span className="cat-detail-version">v1</span>
              </div>
              <div className="cat-detail-title">{sel.title}</div>
              <div className="cat-fact-grid">
                <div className="cat-fact"><div className="cat-fact-label">Rows</div><div className="cat-fact-value">{sel.rows}</div></div>
                <div className="cat-fact"><div className="cat-fact-label">Geography</div><div className="cat-fact-value">{sel.geo}</div></div>
                <div className="cat-fact"><div className="cat-fact-label">Frequency</div><div className="cat-fact-value">{sel.freq}</div></div>
                <div className="cat-fact"><div className="cat-fact-label">Source</div><div className="cat-fact-value">{sel.source}</div></div>
              </div>
            </div>

            <div className="cat-tabs">
              {TABS.map((t) => (
                <div key={t} className={`cat-tab${tab === t ? ' cat-tab-active' : ''}`} onClick={() => setTab(t)}>
                  {t[0].toUpperCase() + t.slice(1)}
                </div>
              ))}
            </div>

            <div className="cat-tab-body">
              {tab === 'summary' && (
                <div className="cat-summary">
                  <div className="cat-summary-tagrow">
                    <span className="cat-summary-tag">{hasKey ? 'Model-generated' : 'Awaiting model key'}</span>
                    {hasKey && <span className="cat-link-action">Regenerate</span>}
                  </div>
                  <div className="cat-summary-text">{sel.summary}</div>
                  {!hasKey && <button className="cat-key-btn" onClick={onGoSettings}>Add model key</button>}
                  <div className="cat-tag-list">
                    {TAGS.map((t) => <span className="cat-tag-chip" key={t}>{t}</span>)}
                  </div>
                </div>
              )}

              {tab === 'metadata' && (
                <div className="cat-meta-fields">
                  {[
                    ['metadata_code', sel.id], ['title', sel.title], ['geography', sel.geo],
                    ['frequency', sel.freq], ['data_source', sel.source], ['access', sel.access],
                    ['row_count', sel.rows], ['keywords', sel.keywords],
                  ].map(([k, v]) => (
                    <div className="cat-meta-field" key={k}>
                      <div className="cat-meta-key">{k}</div>
                      <div className="cat-meta-value">{v}</div>
                    </div>
                  ))}
                </div>
              )}

              {tab === 'api' && (
                <div className="cat-api">
                  <div className="cat-api-hint">Fetch the harmonised table as JSON. Add <code>?format=csv</code> for a flat file.</div>
                  <div className="cat-code-row">
                    <div className="cat-code-box">{apiUrl}</div>
                    <button className="cat-copy-btn" onClick={() => copy('api', apiUrl)}>{copied === 'api' ? 'Copied' : 'Copy'}</button>
                  </div>
                  <div className="cat-example-box">
                    <div className="cat-example-label">Example</div>
                    <div className="cat-example-code">curl -H "Authorization: Bearer $TOKEN" "{apiUrl}"</div>
                  </div>
                </div>
              )}

              {tab === 'mcp' && (
                <div className="cat-mcp-tab">
                  <div className="cat-api-hint">Add this endpoint to an assistant and it can find and read this release itself.</div>
                  <div className="cat-code-row">
                    <div className="cat-code-box">{MCP_URL}</div>
                    <button className="cat-copy-btn" onClick={() => copy('mcp2', MCP_URL)}>{copied === 'mcp2' ? 'Copied' : 'Copy'}</button>
                  </div>
                  <div className="cat-tool-rows">
                    {MCP_TOOLS.map((t) => (
                      <div className="cat-tool-row" key={t}>
                        <div className="cat-tool-name">{t}</div>
                        <div className="cat-tool-desc">{TOOL_DESCS[t]}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
