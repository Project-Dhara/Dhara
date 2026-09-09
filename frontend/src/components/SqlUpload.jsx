'use client'

import { useRef, useState } from 'react'
import { ArrowRight, X } from 'lucide-react'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { withAuthHeaders } from '../lib/auth'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'

function FileList({ files, onRemove }) {
  if (files.length === 0) return null
  return (
    <ul className="flex list-none flex-col gap-1">
      {files.map((f, i) => (
        <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-2 text-[13px]">
          <span className="break-all">{f.name}</span>
          <button className="flex h-6 w-6 flex-none items-center justify-center rounded text-ink-soft hover:bg-cream hover:text-[#b91c1c]" onClick={() => onRemove(i)} title="Remove" aria-label="Remove file">
            <X className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        </li>
      ))}
    </ul>
  )
}

const emptyConn = {
  database_url: '',
  host: '',
  port: '5432',
  database: '',
  user: '',
  password: '',
  sslmode: '',
}

/**
 * SQL → Excel-shaped extract → same batch-match / Console steps as BatchUpload.
 * Default: auto-extract every user table/view. Optional custom SELECT.
 */
export default function SqlUpload({
  onMatched,
  onError,
  metadataFiles: controlledMetadataFiles,
  onMetadataFilesChange,
  hideMetadataSection = false,
}) {
  const [connMode, setConnMode] = useState('url') // url | fields
  const [conn, setConn] = useState(emptyConn)
  const [query, setQuery] = useState('')
  const [title, setTitle] = useState('')
  const [tableId, setTableId] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [internalMetadataFiles, setInternalMetadataFiles] = useState([])
  const metadataControlled = controlledMetadataFiles != null
  const metadataFiles = metadataControlled ? controlledMetadataFiles : internalMetadataFiles
  const setMetadataFiles = metadataControlled ? onMetadataFilesChange : setInternalMetadataFiles
  const [stage, setStage] = useState('idle') // idle | extracting | matching | error
  const [error, setError] = useState('')
  const fileInputRef = useRef()

  const setField = (key, value) => setConn((prev) => ({ ...prev, [key]: value }))

  const busy = stage === 'extracting' || stage === 'matching'
  const hasQuery = Boolean(query.trim())
  const canRun =
    !busy
    && (
      (connMode === 'url' && conn.database_url.trim())
      || (connMode === 'fields' && conn.host.trim() && conn.database.trim() && conn.user.trim())
    )

  const run = async () => {
    setError('')
    setStage('extracting')
    try {
      const body = {}
      if (hasQuery) {
        body.query = query.trim()
        if (title.trim()) body.title = title.trim()
        if (tableId.trim()) body.table_id = tableId.trim()
      }
      if (connMode === 'url') {
        body.database_url = conn.database_url.trim()
      } else {
        body.host = conn.host.trim()
        body.port = Number(conn.port) || 5432
        body.database = conn.database.trim()
        body.user = conn.user.trim()
        if (conn.password) body.password = conn.password
        if (conn.sslmode.trim()) body.sslmode = conn.sslmode.trim()
      }

      const extractRes = await fetch(
        '/api/catalogue/sql-extract',
        withAuthHeaders(withLlmKeyHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        })),
      )
      if (!extractRes.ok) {
        const err = await extractRes.json().catch(() => ({ detail: 'SQL extraction failed' }))
        throw new Error(typeof err.detail === 'string' ? err.detail : 'SQL extraction failed')
      }
      const extractData = await extractRes.json()

      setStage('matching')
      const matchFd = new FormData()
      matchFd.append('tables_json', JSON.stringify(extractData.tables || []))
      metadataFiles.forEach((f) => matchFd.append('metadata_files', f))
      const matchRes = await fetch('/api/catalogue/batch-match', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: matchFd })))
      if (!matchRes.ok) {
        const err = await matchRes.json().catch(() => ({ detail: 'Matching failed' }))
        throw new Error(typeof err.detail === 'string' ? err.detail : 'Matching failed')
      }
      const matchData = await matchRes.json()

      setStage('idle')
      onMatched({ ...matchData, metadataFiles, perFile: extractData.per_file })
    } catch (e) {
      const message = e?.message === 'Failed to fetch'
        ? 'Could not reach the server for SQL extract. Check that the backend is running, then try again.'
        : (e?.message || 'Something went wrong')
      setError(message)
      setStage('error')
      onError?.(e)
    }
  }

  const fieldClass = 'w-full rounded-md border border-line bg-surface px-3 py-2 text-[13.5px] text-ink outline-none focus:border-teal'

  return (
    <div className="flex w-full flex-col gap-[18px]">
      <div className="rounded-lg border border-line bg-cream/30 px-4 py-3 text-[13px] leading-relaxed text-ink-soft">
        Connect to a <span className="font-semibold text-ink">PostgreSQL</span> database.
        Leave the SQL box empty to auto-extract tables. DHARA catalogue databases
        (<code className="rounded bg-cream px-1 text-[12px] text-ink">datasets</code>
        {' '}+{' '}
        <code className="rounded bg-cream px-1 text-[12px] text-ink">dataset_rows</code>)
        {' '}are expanded into one logical table per dataset — not the registry surface.
        Ordinary databases still extract every user table/view.
        {' '}If the API runs in Docker, use host <code className="rounded bg-cream px-1 text-[12px] text-ink">postgres</code>
        {' '}for this project’s Compose DB.
      </div>

      <div className="flex flex-wrap gap-2" role="tablist" aria-label="Connection mode">
        <button
          type="button"
          role="tab"
          aria-selected={connMode === 'url'}
          disabled={busy}
          onClick={() => setConnMode('url')}
          className={`dhara-tab rounded-xl px-3 py-1.5 text-[12.5px] font-semibold ${
            connMode === 'url'
              ? 'border-teal-deep bg-teal-deep text-cream'
              : 'border-line bg-surface text-ink-soft hover:border-teal-deep hover:bg-teal-deep hover:text-cream'
          }`}
        >
          Connection URL
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={connMode === 'fields'}
          disabled={busy}
          onClick={() => setConnMode('fields')}
          className={`dhara-tab rounded-xl px-3 py-1.5 text-[12.5px] font-semibold ${
            connMode === 'fields'
              ? 'border-teal-deep bg-teal-deep text-cream'
              : 'border-line bg-surface text-ink-soft hover:border-teal-deep hover:bg-teal-deep hover:text-cream'
          }`}
        >
          Host / user / database
        </button>
      </div>

      <div key={connMode} className="dhara-tab-panel flex flex-col gap-3">
      {connMode === 'url' ? (
        <label className="flex flex-col gap-1.5">
          <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Database URL</span>
          <input
            className={fieldClass}
            type="password"
            autoComplete="off"
            spellCheck={false}
            disabled={busy}
            placeholder="postgresql://dhara:dhara_local_password@postgres:5432/dhara"
            value={conn.database_url}
            onChange={(e) => setField('database_url', e.target.value)}
          />
        </label>
      ) : (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1.5 sm:col-span-1">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Host</span>
            <input className={fieldClass} disabled={busy} value={conn.host} onChange={(e) => setField('host', e.target.value)} placeholder="postgres (Compose) or host.docker.internal" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Port</span>
            <input className={fieldClass} disabled={busy} value={conn.port} onChange={(e) => setField('port', e.target.value)} placeholder="5432" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Database</span>
            <input className={fieldClass} disabled={busy} value={conn.database} onChange={(e) => setField('database', e.target.value)} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">User</span>
            <input className={fieldClass} disabled={busy} value={conn.user} onChange={(e) => setField('user', e.target.value)} autoComplete="off" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Password</span>
            <input className={fieldClass} type="password" disabled={busy} value={conn.password} onChange={(e) => setField('password', e.target.value)} autoComplete="new-password" />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">SSL mode (optional)</span>
            <input className={fieldClass} disabled={busy} value={conn.sslmode} onChange={(e) => setField('sslmode', e.target.value)} placeholder="require" />
          </label>
        </div>
      )}
      </div>

      <div className="flex flex-col gap-2">
        <button
          type="button"
          disabled={busy}
          className="self-start text-[13px] font-semibold text-teal hover:text-teal-dark"
          onClick={() => setShowAdvanced((v) => !v)}
        >
          {showAdvanced ? 'Hide optional SQL query' : 'Optional: write a custom SQL query'}
        </button>
        {showAdvanced && (
          <div className="flex flex-col gap-3 rounded-lg border border-line bg-surface p-3.5">
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">SQL query (optional)</span>
              <textarea
                className={`${fieldClass} min-h-[100px] font-mono text-[12.5px] leading-relaxed`}
                disabled={busy}
                spellCheck={false}
                placeholder="Leave empty to auto-extract. Catalogue DBs expand each dataset; otherwise SELECT * FROM each table. Example: SELECT * FROM indicators WHERE year = 2023"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            {hasQuery && (
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <label className="flex flex-col gap-1.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Result title (optional)</span>
                  <input className={fieldClass} disabled={busy} value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. State health indicators 2023" />
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Source table ID (optional)</span>
                  <input className={fieldClass} disabled={busy} value={tableId} onChange={(e) => setTableId(e.target.value)} placeholder="e.g. SQL-HEALTH-2023" />
                </label>
              </div>
            )}
          </div>
        )}
      </div>

      {!hideMetadataSection && (
        <div className="flex min-w-0 flex-col gap-2.5">
          <div className="flex items-center gap-2">
            <span className="h-2 w-2 rounded-sm bg-yellow" />
            <span className="text-xs font-bold uppercase tracking-wide text-ink">Metadata files (optional)</span>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls"
            multiple
            className="hidden"
            onChange={(e) => {
              const files = Array.from(e.target.files || []).filter((f) => /\.(xlsx|xls)$/i.test(f.name))
              setMetadataFiles((prev) => [...prev, ...files])
              e.target.value = ''
            }}
          />
          <div
            className={`flex h-[72px] cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border border-dashed border-[#c9bda6] bg-[#FFFCF6] ${busy ? 'cursor-not-allowed opacity-60' : ''}`}
            onClick={() => !busy && fileInputRef.current?.click()}
          >
            <div className="text-[14px] font-semibold text-teal">Add metadata tag files</div>
            <div className="text-[12.5px] text-[#8E9398]">Optional — same as Excel flow</div>
          </div>
          <FileList files={metadataFiles} onRemove={(i) => setMetadataFiles((prev) => prev.filter((_, idx) => idx !== i))} />
        </div>
      )}

      {error && <ErrorBanner>{error}</ErrorBanner>}

      <div className="flex items-center gap-4">
        <Button disabled={!canRun} onClick={run}>
          {busy && <span className="inline-block h-[13px] w-[13px] animate-spin rounded-full border-2 border-white/50 border-t-white" />}
          {stage === 'extracting' && (hasQuery ? 'Running query…' : 'Extracting tables…')}
          {stage === 'matching' && 'Matching to metadata…'}
          {(stage === 'idle' || stage === 'error') && (
            <span className="inline-flex items-center gap-1.5">
              {hasQuery ? 'Preview query result' : 'Extract all tables'}
              <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
            </span>
          )}
        </Button>
        {!busy && !hasQuery && (
          <span className="text-xs text-[#8E9398]">No SQL needed — catalogue DBs expand datasets automatically</span>
        )}
      </div>
    </div>
  )
}
