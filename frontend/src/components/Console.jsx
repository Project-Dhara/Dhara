import { useEffect, useState } from 'react'
import ModeSelector from './ModeSelector'
import FileUpload from './FileUpload'
import TableViewer from './TableViewer'
import PushModal from './PushModal'
import BatchUpload from './BatchUpload'
import BatchReview from './BatchReview'
import ReconcileIds from './ReconcileIds'
import Classify from './Classify'
import Publish from './Publish'
import { withLlmKeyHeaders } from '../llmKey'
import { withAuthHeaders } from '../auth'

// Short government table code for a tab button — e.g. "Table : D-12 & D-13"
// → "D12, D13" — pulled from the source's own table-label row (`table.title`,
// which the extractor sets to that raw label, not a display title; see
// backend/extractor.py's _build_ddi_id for the same "letter-digits" pattern).
function tableCode(table) {
  const src = table.title || ''
  const matches = [...src.matchAll(/\b([A-Za-z])-?(\d+(?:\.\d+)?)\b/g)]
  if (matches.length > 0) {
    const codes = [...new Set(matches.map((m) => `${m[1].toUpperCase()}${m[2]}`))]
    return codes.join(', ')
  }
  return table.sheet || table.title || table.id
}

const STAGE_DEFS = [
  { name: 'Dataset Inventory', firstStep: 0, sub: 'Files, preview, grouping' },
  { name: 'Metadata Workspace', firstStep: 5, sub: 'Title, category, coverage' },
  { name: 'Transformation & Harmonisation', firstStep: 6, sub: 'Concepts and code maps' },
  { name: 'Dataset Publication', firstStep: 7, sub: 'API, MCP, catalogue' },
]

function stepInfoFor(step, mode) {
  const batch = mode === 'batch'
  return [
    { title: 'Dataset inventory', sub: 'Bring datasets into DHARA. Pick how you want to upload.' },
    {
      title: batch ? 'Select dataset and metadata files' : 'Select the dataset file',
      sub: batch
        ? 'Upload the workbooks and their metadata tag files for this release.'
        : 'One dataset workbook and its metadata tag file.',
    },
    {
      title: 'Preview what was read',
      sub: batch
        ? 'Pick a table above to check the rows and the metadata read from the tag files.'
        : 'Pick a table above to check what was read from the workbook.',
    },
    {
      title: 'Confirm Table Details',
      sub: 'Code-based and prompt-based validation disagreed on some tables — confirm or correct them.',
    },
    { title: 'Grouping', sub: 'Optional. Tables with the same columns can share one metadata record.' },
    { title: 'Metadata', sub: 'One card per table. Fill in what you know — only the title is required.' },
    { title: 'Classification and harmonisation', sub: 'Map columns to standard concepts and code lists.' },
    { title: 'Publish this release', sub: 'Register the API and MCP endpoints for this release.' },
  ][step]
}

const BACK_LABELS = [
  '', 'Choose another method', 'Change files', 'Back to preview', 'Back to table details', 'Back to grouping', 'Back to metadata',
]

function stageIndexForStep(step) {
  if (step <= 4) return 0
  if (step === 5) return 1
  if (step === 6) return 2
  return 3
}

export default function Console({ hasKey, onGoSettings, onGoDashboard, onGoCatalogue, onUploadAnother }) {
  const [step, setStep] = useState(0)
  const [mode, setMode] = useState(null)

  // ── single-file flow state (ported from SingleFileFlow.jsx) ──
  const [tables, setTables] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [filename, setFilename] = useState('')
  const [groups, setGroups] = useState(null)
  const [grouping, setGrouping] = useState(false)
  const [singleDatasetFile, setSingleDatasetFile] = useState(null)
  const [singleMetaFile, setSingleMetaFile] = useState(null)

  // ── batch flow state (ported from BatchFlow.jsx) ──
  const [matchResult, setMatchResult] = useState(null)
  const [metadataFiles, setMetadataFiles] = useState([])
  const [batchPreviewId, setBatchPreviewId] = useState(null)

  // ── carried into Classify / Publish after the metadata save ──
  const [metaLabel, setMetaLabel] = useState('')
  const [metadataId, setMetadataId] = useState(null)

  const pickMode = (m) => {
    setMode(m)
    setTables([]); setSelectedId(null); setGroups(null); setFilename(''); setError(null)
    setMatchResult(null); setMetadataFiles([]); setBatchPreviewId(null)
    setSingleMetaFile(null); setSingleDatasetFile(null)
    setStep(1)
  }

  const runSingleExtract = async () => {
    if (!singleDatasetFile) return
    setLoading(true)
    setError(null)
    setTables([]); setSelectedId(null); setGroups(null)
    const formData = new FormData()
    formData.append('file', singleDatasetFile)
    try {
      const res = await fetch('/api/extract', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: formData })))
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(err.detail || 'Extraction failed')
      }
      const data = await res.json()
      setTables(data.tables)
      setFilename(data.filename)
      if (data.tables.length > 0) setSelectedId(data.tables[0].id)
      setStep(2)
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  const handleGroup = async () => {
    setGrouping(true)
    try {
      const fd = new FormData()
      fd.append('tables_json', JSON.stringify(tables))
      if (singleMetaFile) fd.append('metadata_files', singleMetaFile)
      // Sent so a group with no metadata-file match can be auto-filled via
      // Stage 4 LLM metadata generation server-side instead of staying blank.
      if (singleDatasetFile) fd.append('dataset_files', singleDatasetFile)
      const res = await fetch('/api/group-tables', withAuthHeaders({ method: 'POST', body: fd }))
      if (!res.ok) throw new Error('Grouping failed')
      const data = await res.json()
      setGroups(data.groups)
    } catch {
      // best-effort
    } finally {
      setGrouping(false)
    }
  }

  // Auto-run grouping once on arriving at the grouping step, so Stage 4
  // metadata generation happens without requiring the optional "Group
  // similar tables" button click — mirrors batch mode, where matching (and
  // therefore metadata generation) always runs automatically.
  useEffect(() => {
    if (step === 4 && mode === 'single' && groups === null && !grouping && tables.length > 0) {
      handleGroup()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, mode])

  const handleUpdateId = (newId) => {
    setTables((prev) => prev.map((t) => t.id === selectedId ? { ...t, id: newId } : t))
    setSelectedId(newId)
  }

  const applyReconcile = (corrections) => {
    const patchTable = (t) => (corrections[t.id] ? { ...t, ...corrections[t.id] } : t)
    if (mode === 'single') {
      setTables((prev) => prev.map(patchTable))
    } else if (mode === 'batch') {
      setMatchResult((prev) => prev && ({
        ...prev,
        groups: prev.groups.map((g) => ({
          ...g,
          matched_tables: g.matched_tables.map((mt) => ({ ...mt, table: patchTable(mt.table) })),
        })),
        unmatched_tables: prev.unmatched_tables.map((u) => ({ ...u, table: patchTable(u.table) })),
      }))
    }
    setStep(4)
  }

  const handleMatched = (data) => {
    setMetadataFiles(data.metadataFiles)
    setMatchResult(data)
    const all = data.groups.flatMap((g) => g.matched_tables.map((mt) => mt.table))
      .concat(data.unmatched_tables.map((u) => u.table))
    if (all.length > 0) setBatchPreviewId(all[0].id)
    setStep(2)
  }

  const back = () => setStep((s) => Math.max(0, s - 1))

  const stageIdx = stageIndexForStep(step)
  const info = stepInfoFor(step, mode)

  const goStage = (firstStep) => {
    if (firstStep <= step) setStep(firstStep)
  }

  // ── step 2: preview ──
  const batchAllTables = matchResult
    ? matchResult.groups.flatMap((g) => g.matched_tables.map((mt) => mt.table))
      .concat(matchResult.unmatched_tables.map((u) => u.table))
    : []
  const previewTables = mode === 'batch' ? batchAllTables : tables
  const previewSelectedId = mode === 'batch' ? batchPreviewId : selectedId
  const previewSelected = previewTables.find((t) => t.id === previewSelectedId) || previewTables[0]
  const setPreviewSelected = mode === 'batch' ? setBatchPreviewId : setSelectedId

  return (
    <div className="console">
      <aside className="console-stages">
        <div className="console-stages-label">Console stages</div>
        {STAGE_DEFS.map((s, i) => (
          <div
            key={s.name}
            className={`console-stage${i === stageIdx ? ' console-stage-active' : ''}${i < stageIdx ? ' console-stage-done' : ''}`}
            onClick={() => goStage(s.firstStep)}
          >
            <div className="console-stage-mark">{i < stageIdx ? '✓' : i + 1}</div>
            <div className="console-stage-text">
              <div className="console-stage-name">{s.name}</div>
              <div className="console-stage-sub">{s.sub}</div>
            </div>
          </div>
        ))}
      </aside>

      <div className="console-main">
        <div className="console-header">
          <div>
            {step > 0 && step < 7 && (
              <div className="console-back" onClick={back}>← {BACK_LABELS[step]}</div>
            )}
            <div className="console-step-title">{info.title}</div>
            <div className="console-step-sub">{info.sub}</div>
          </div>
          <div className="console-stage-counter">Stage {stageIdx + 1} of {STAGE_DEFS.length}</div>
        </div>

        {step === 0 && (
          <ModeSelector mode={mode} onModeChange={setMode} onPick={pickMode} />
        )}

        {step === 1 && mode === 'single' && (
          <div className="console-files-step">
            <div className="batch-upload-cols">
              <div className="batch-upload-col">
                <div className="batch-upload-label-row">
                  <span className="batch-upload-swatch" style={{ background: 'var(--green)' }} />
                  <span className="batch-upload-label">Dataset file</span>
                </div>
                <FileUpload
                  onUpload={setSingleDatasetFile}
                  loading={loading}
                  label="Add dataset file"
                  hint="XLSX — drag and drop or browse"
                  selectedName={singleDatasetFile?.name}
                  compact
                />
              </div>

              <div className="batch-upload-col">
                <div className="batch-upload-label-row">
                  <span className="batch-upload-swatch" style={{ background: 'var(--yellow)' }} />
                  <span className="batch-upload-label">Metadata file</span>
                </div>
                <FileUpload
                  onUpload={setSingleMetaFile}
                  label="Add metadata file"
                  hint="XLSX tag file — prefills the metadata step"
                  selectedName={singleMetaFile?.name}
                  compact
                />
              </div>
            </div>

            {error && <div className="error-banner"><strong>Error:</strong> {error}</div>}

            <div className="batch-upload-actions">
              <button
                className="console-primary-btn"
                disabled={!singleDatasetFile || loading}
                onClick={runSingleExtract}
              >
                {loading ? 'Extracting tables…' : 'Preview files →'}
              </button>
              <span className="batch-upload-hint">
                {singleDatasetFile ? '1' : '0'} dataset · {singleMetaFile ? '1' : '0'} metadata
              </span>
            </div>
          </div>
        )}

        {step === 1 && mode === 'batch' && (
          <BatchUpload onMatched={handleMatched} />
        )}

        {step === 2 && previewTables.length > 0 && (
          <div className="console-preview-step">
            <div className="console-preview-tabs">
              {previewTables.map((t, i) => (
                <div
                  key={t.id}
                  className={`console-preview-tab${t.id === previewSelected?.id ? ' console-preview-tab-active' : ''}`}
                  onClick={() => setPreviewSelected(t.id)}
                  title={t.id}
                >
                  <span className="console-preview-tab-id">{tableCode(t)}</span>
                  <span className="console-preview-tab-meta">{t.row_count} rows</span>
                </div>
              ))}
            </div>
            {previewSelected && (
              <TableViewer table={previewSelected} onUpdateId={mode === 'single' ? handleUpdateId : undefined} compact />
            )}
            <div className="console-step-actions">
              <button className="console-primary-btn" onClick={() => setStep(3)}>Looks right, continue →</button>
              <button className="console-secondary-btn" onClick={() => setStep(1)}>Change files</button>
            </div>
          </div>
        )}

        {step === 3 && (
          <ReconcileIds
            tables={mode === 'batch' ? batchAllTables : tables}
            onContinue={applyReconcile}
          />
        )}

        {step === 4 && mode === 'single' && (
          <div className="console-grouping-step">
            <div className="console-group-action-row">
              <button className="console-secondary-btn" onClick={handleGroup} disabled={grouping || tables.length < 2}>
                {grouping ? 'Grouping…' : 'Group similar tables'}
              </button>
              {tables.length < 2 && <span className="console-group-hint">Only one table — nothing to group, but metadata is still being prepared.</span>}
              {grouping && <span className="console-group-hint">Preparing metadata…</span>}
              {!grouping && groups && <span className="console-group-hint">{groups.length} group{groups.length !== 1 ? 's' : ''} found</span>}
            </div>

            {groups && groups.length > 0 && (
              <div className="console-group-summary">
                {groups.map((g, i) => (
                  <div className="console-group-card" key={i}>
                    <div className="console-group-card-head">
                      <span className="console-group-card-file">{g.name}</span>
                      <span className="console-group-card-count">{g.table_ids.length} table{g.table_ids.length !== 1 ? 's' : ''}</span>
                    </div>
                    <div className="console-group-card-ids">{g.table_ids.join(', ')}</div>
                  </div>
                ))}
              </div>
            )}

            <div className="console-step-actions">
              <button className="console-primary-btn" onClick={() => setStep(5)}>Continue to metadata →</button>
            </div>
          </div>
        )}

        {step === 4 && mode === 'batch' && matchResult && (
          <div className="console-grouping-step">
            <div className="console-group-summary">
              {matchResult.groups.map((g, i) => (
                <div className="console-group-card" key={i}>
                  <div className="console-group-card-head">
                    <span className="console-group-card-file">{g.file_name}</span>
                    <span className="console-group-card-count">{g.matched_tables.length} table{g.matched_tables.length !== 1 ? 's' : ''}</span>
                  </div>
                  <div className="console-group-card-ids">
                    {g.matched_tables.map((mt) => mt.table.id).join(', ') || '—'}
                  </div>
                </div>
              ))}
              {matchResult.unmatched_tables.length > 0 && (
                <div className="console-group-card console-group-card-warn">
                  <div className="console-group-card-head">
                    <span className="console-group-card-file">⚠ Unmatched tables</span>
                    <span className="console-group-card-count">{matchResult.unmatched_tables.length}</span>
                  </div>
                  <div className="console-group-card-ids">
                    {matchResult.unmatched_tables.map((u) => u.table.id).join(', ')}
                  </div>
                </div>
              )}
            </div>
            <div className="console-step-actions">
              <button className="console-primary-btn" onClick={() => setStep(5)}>Continue to metadata →</button>
            </div>
          </div>
        )}

        {step === 5 && mode === 'single' && (
          <PushModal
            tables={tables}
            groups={groups}
            inline
            initialExcelFile={singleMetaFile}
            onPushed={(result, title) => {
              setMetaLabel(title || filename || selectedId || 'this dataset')
              setMetadataId(result?.metadata_id || null)
              setStep(6)
            }}
          />
        )}

        {step === 5 && mode === 'batch' && matchResult && (
          <BatchReview
            matchResult={matchResult}
            metadataFiles={metadataFiles}
            onDone={(label) => {
              setMetaLabel(label || 'this release')
              setStep(6)
            }}
            onCancel={() => setStep(4)}
          />
        )}

        {step === 6 && (
          <Classify datasetLabel={metaLabel || 'This dataset'} onContinue={() => setStep(7)} />
        )}

        {step === 7 && (
          <Publish
            datasetLabel={metaLabel || 'This dataset'}
            metadataId={metadataId}
            hasKey={hasKey}
            onGoSettings={onGoSettings}
            onGoDashboard={onGoDashboard}
            onGoCatalogue={onGoCatalogue}
            onUploadAnother={onUploadAnother}
          />
        )}
      </div>
    </div>
  )
}
