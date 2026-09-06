import { useEffect, useState } from 'react'

// Confirmation screen after Continue to publish writes the release to
// Postgres. API/MCP URLs here are still display placeholders.

const PUBLISH_STEPS = [
  'Validating harmonised columns',
  'Writing NMDS metadata record',
  'Registering API endpoint',
  'Registering MCP endpoint',
]

const MCP_TOOLS = ['search_datasets', 'get_table', 'get_metadata']

export default function Publish({ datasetLabel, metadataId, hasKey, onGoSettings, onGoDashboard, onUploadAnother, onGoCatalogue }) {
  const [publishing, setPublishing] = useState(true)
  const [doneSteps, setDoneSteps] = useState(0)
  const [access, setAccess] = useState('Public')
  const [licence, setLicence] = useState('GODL — India')
  const [version, setVersion] = useState('v1')
  const [copied, setCopied] = useState(null)

  useEffect(() => {
    if (!publishing) return
    if (doneSteps >= PUBLISH_STEPS.length) {
      const t = setTimeout(() => setPublishing(false), 350)
      return () => clearTimeout(t)
    }
    const t = setTimeout(() => setDoneSteps((n) => n + 1), 450)
    return () => clearTimeout(t)
  }, [publishing, doneSteps])

  const idBase = metadataId || 'DHARA_NEW_RELEASE'
  const apiUrl = `https://catalogue.dhara.people+ai.org/api/datasets/${idBase}`
  const mcpUrl = 'https://catalogue.dhara.people+ai.org/mcp'

  const copy = (label, text) => {
    navigator.clipboard?.writeText(text).catch(() => {})
    setCopied(label)
    setTimeout(() => setCopied(null), 1500)
  }

  if (publishing) {
    return (
      <div className="publish-loading">
        <div className="publish-loading-ring">
          <div className="publish-ring publish-ring-1" />
          <div className="publish-ring publish-ring-2" />
          <div className="publish-loading-check">✓</div>
        </div>
        <div className="publish-loading-title">Publishing to the catalogue…</div>
        <div className="publish-loading-sub">Almost there — this only takes a moment.</div>
        <div className="publish-steps">
          {PUBLISH_STEPS.map((label, i) => (
            <div className="publish-step-row" key={label}>
              <span className={`publish-step-mark${i < doneSteps ? ' publish-step-mark-done' : ''}`}>{i < doneSteps ? '✓' : i + 1}</span>
              <span>{label}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="publish-done">
      <div className="publish-done-banner">
        <div>
          <div className="publish-done-eyebrow">{datasetLabel}</div>
          <div className="publish-done-title">Published to the catalogue</div>
          <div className="publish-done-sub">This release is now discoverable via the API and MCP endpoint below.</div>
        </div>
        <button className="publish-open-cat-btn" onClick={onGoCatalogue}>Open in catalogue →</button>
      </div>

      <div className="publish-endpoints">
        <div className="publish-endpoint-card">
          <div className="publish-endpoint-head"><span className="publish-endpoint-dot" style={{ background: 'var(--green)' }} />API endpoint</div>
          <div className="publish-endpoint-desc">Fetch the harmonised table as JSON or CSV.</div>
          <div className="publish-code-row">
            <div className="publish-code-box">{apiUrl}</div>
            <button className="publish-copy-btn" onClick={() => copy('api', apiUrl)}>{copied === 'api' ? 'Copied' : 'Copy'}</button>
          </div>
          <div className="publish-endpoint-foot">GET · token in Authorization header</div>
        </div>

        <div className="publish-endpoint-card">
          <div className="publish-endpoint-head"><span className="publish-endpoint-dot" style={{ background: 'var(--teal)' }} />MCP endpoint</div>
          <div className="publish-endpoint-desc">Point an assistant at the catalogue and it can query this release.</div>
          <div className="publish-code-row">
            <div className="publish-code-box">{mcpUrl}</div>
            <button className="publish-copy-btn" onClick={() => copy('mcp', mcpUrl)}>{copied === 'mcp' ? 'Copied' : 'Copy'}</button>
          </div>
          <div className="publish-mcp-tools">
            {MCP_TOOLS.map((t) => <span className="publish-mcp-chip" key={t}>{t}</span>)}
          </div>
        </div>
      </div>

      <div className="publish-summary-card">
        <div className="publish-summary-head">
          <span className="publish-endpoint-dot" style={{ background: 'var(--yellow)' }} />
          <span>Metadata summary</span>
          <span className="publish-summary-tag">{hasKey ? 'Model-generated' : 'Awaiting model key'}</span>
        </div>
        {hasKey ? (
          <div className="publish-summary-text">
            Registered records for {datasetLabel}, harmonised to standard concepts and code lists during classification. Ready for downstream API and MCP consumption.
          </div>
        ) : (
          <div className="publish-summary-empty">
            <span>A written summary is generated from the metadata with your own model key. The dataset publishes without it.</span>
            <button className="cat-key-btn" onClick={onGoSettings}>Add model key</button>
          </div>
        )}
      </div>

      <div className="publish-release-card">
        <div className="publish-release-head">Release details</div>
        <div className="publish-release-grid">
          <div className="classify-field">
            <label className="classify-label">Access</label>
            <select className="classify-select" value={access} onChange={(e) => setAccess(e.target.value)}>
              <option value="Public">Public</option>
              <option value="Restricted">Restricted — on request</option>
              <option value="Internal">Internal to department</option>
            </select>
          </div>
          <div className="classify-field">
            <label className="classify-label">Licence</label>
            <select className="classify-select" value={licence} onChange={(e) => setLicence(e.target.value)}>
              <option value="GODL — India">Government Open Data Licence — India</option>
              <option value="CC BY 4.0">CC BY 4.0</option>
              <option value="Departmental terms">Departmental terms</option>
            </select>
          </div>
          <div className="classify-field">
            <label className="classify-label">Version</label>
            <input className="classify-select" type="text" value={version} onChange={(e) => setVersion(e.target.value)} />
          </div>
        </div>
      </div>

      <div className="publish-final-actions">
        <button className="console-primary-btn" onClick={onGoDashboard}>Back to dashboard</button>
        <button className="console-secondary-btn" onClick={onUploadAnother}>Upload another</button>
      </div>
    </div>
  )
}
