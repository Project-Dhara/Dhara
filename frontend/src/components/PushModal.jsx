import { useState, useEffect } from 'react'
import { withLlmKeyHeaders } from '../llmKey'
import { withAuthHeaders } from '../auth'
import { CLICK_THROUGH_ENABLED } from '../clickThrough'
import MetadataSheetGrid from './MetadataSheetGrid'
import NmdsConceptForm from './NmdsConceptForm'
import { emptyNmdsFields, nmdsFieldsToList, mergeNmdsConcepts, NMDS_CONCEPT_TEMPLATE } from '../nmdsConcepts'

const KNOWN_NMDS_CONCEPTS = new Set(NMDS_CONCEPT_TEMPLATE.filter((r) => !r.section).map((r) => r.concept))

const FORM_FIELDS = [
  'title', 'product', 'category', 'geography', 'frequency', 'time_period',
  'data_source', 'description', 'last_updated', 'future_release',
  'key_statistics', 'remarks',
]

function todayFormatted() {
  return new Date().toISOString().slice(0, 10)
}

function fieldsFromGroup(g) {
  return {
    title: g.title || '',
    product: g.product || '',
    category: g.category || '',
    geography: g.geography || '',
    frequency: g.frequency || '',
    time_period: g.time_period || '',
    data_source: g.data_source || '',
    description: g.description || '',
    last_updated: g.last_updated_date || '',
    future_release: g.future_release || '',
    key_statistics: g.key_statistics || '',
    remarks: g.remarks || '',
  }
}

function emptyFields() {
  return {
    title: '', product: '', category: '', geography: '', frequency: '',
    time_period: '', data_source: '', description: '',
    last_updated: todayFormatted(), future_release: '', key_statistics: '', remarks: '',
  }
}

export default function PushModal({ tables, groups, onClose, inline = false, onPushed, initialExcelFile = null }) {
  const [existingGroups, setExistingGroups] = useState([])
  const [scope, setScope] = useState('all')
  const [metaMode, setMetaMode] = useState('new')
  const [selectedMetaId, setSelectedMetaId] = useState('')
  const [form, setForm] = useState(emptyFields())
  const [originalExistingFields, setOriginalExistingFields] = useState(null)
  const [excelFile, setExcelFile] = useState(initialExcelFile)
  const [parsingExcel, setParsingExcel] = useState(false)
  const [excelParseError, setExcelParseError] = useState('')
  const [step, setStep] = useState('config')
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const [nmdsFields, setNmdsFields] = useState(emptyNmdsFields())
  const [nmdsFile, setNmdsFile] = useState(null)
  const [nmdsParsing, setNmdsParsing] = useState(false)
  const [nmdsParseError, setNmdsParseError] = useState('')
  // Flags when most rows in an uploaded concept file don't match any known
  // NMDS concept name — usually means the wrong file was uploaded rather
  // than a file that's just sparsely filled in.
  const [nmdsFileMismatch, setNmdsFileMismatch] = useState(false)

  useEffect(() => {
    fetch('/api/catalogue/groups', withAuthHeaders())
      .then((r) => r.json())
      .then((data) => {
        const grps = data.groups || []
        setExistingGroups(grps)
        if (grps.length > 0) {
          // Prime the dropdown for "add to existing group", but do not
          // copy those values into a new-group form. Without a metadata
          // file, Product / Category / Geography etc. stay empty.
          if (initialExcelFile) selectExistingGroup(grps[0].metadata_id, grps)
          else setSelectedMetaId(grps[0].metadata_id)
        }
      })
      .catch(() => {})
    // A metadata file picked earlier at the Files step (single-upload)
    // auto-prefills the sheet below, same as if it were dropped here.
    if (initialExcelFile) handleExcelSelected(initialExcelFile)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // No metadata file was uploaded for this scope's group -- fall back to
  // whatever the backend already computed for it (Stage 4 LLM-generated
  // fields when nothing matched a metadata workbook; see
  // catalogue_matching.match_result_to_push_groups). A manually uploaded
  // excel file always wins, per the "metadata file entry stays the same"
  // rule -- so this only fires when none is present.
  useEffect(() => {
    if (excelFile || metaMode !== 'new' || scope === 'all') return
    const grp = groups && groups.find((g) => g.name === scope)
    const meta = grp?.metadata
    if (!meta || !FORM_FIELDS.some((f) => meta[f])) return
    setForm((prev) => {
      const next = { ...emptyFields() }
      for (const f of FORM_FIELDS) {
        const v = meta[f]
        if (v == null || v === '') continue
        // key_statistics can come back as a JSON object (see the notebook's
        // Stage 4 example output) rather than plain text.
        next[f] = typeof v === 'object' ? JSON.stringify(v) : String(v)
      }
      return next
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scope, excelFile, metaMode])

  const selectExistingGroup = (metadataId, groupsList = existingGroups) => {
    setSelectedMetaId(metadataId)
    const g = groupsList.find((x) => x.metadata_id === metadataId)
    if (g) {
      const fields = fieldsFromGroup(g)
      setForm(fields)
      setOriginalExistingFields(fields)
    }
  }

  const handleMetaModeChange = (mode) => {
    setMetaMode(mode)
    if (mode === 'new') {
      setForm(emptyFields())
      setOriginalExistingFields(null)
    } else if (selectedMetaId) {
      selectExistingGroup(selectedMetaId)
    }
  }

  // Editing a prefilled existing-group field means "this should become its
  // own group" rather than silently overwriting the group everyone else's
  // datasets are already filed under.
  const editedExisting = metaMode === 'existing' && originalExistingFields
    && FORM_FIELDS.some((f) => (form[f] || '') !== (originalExistingFields[f] || ''))

  const effectiveMode = metaMode === 'existing' && !editedExisting ? 'existing' : 'new'

  const tablesToPush = (() => {
    if (scope === 'all') return tables
    const grp = groups && groups.find((g) => g.name === scope)
    if (!grp) return []
    return tables.filter((t) => grp.table_ids.includes(t.id))
  })()

  const handleFormChange = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }))
  }

  const handleExcelSelected = async (file) => {
    setExcelFile(file)
    setExcelParseError('')
    if (!file) return

    setParsingExcel(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/catalogue/parse-metadata-excel', withAuthHeaders({ method: 'POST', body: fd }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Could not read this file' }))
        throw new Error(err.detail || 'Could not read this file')
      }
      const { fields } = await res.json()
      setForm((prev) => {
        const next = { ...prev }
        for (const [key, value] of Object.entries(fields)) {
          if (value) next[key] = value
        }
        return next
      })
    } catch (e) {
      setExcelParseError(e.message)
    } finally {
      setParsingExcel(false)
    }
  }

  const handleNmdsFileSelected = async (file) => {
    setNmdsFile(file)
    setNmdsParseError('')
    setNmdsFileMismatch(false)
    if (!file) {
      setNmdsFields(emptyNmdsFields())
      return
    }

    setNmdsParsing(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/catalogue/parse-concept-file', withAuthHeaders({ method: 'POST', body: fd }))
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Could not read this file' }))
        throw new Error(err.detail || 'Could not read this file')
      }
      const { concepts } = await res.json()
      const rows = concepts || []
      const matched = rows.filter((r) => r.concept && KNOWN_NMDS_CONCEPTS.has(r.concept) && r.details).length
      // A wrong file most often has no "Concept Name" column at all, so the
      // backend parses zero rows — that's just as much a mismatch signal as
      // rows that parsed but mostly didn't match a known concept.
      setNmdsFileMismatch(rows.length === 0 || matched / rows.length < 0.5)
      // Reset before merging so a re-upload doesn't carry over values left
      // behind by a previous (possibly wrong) file.
      setNmdsFields(mergeNmdsConcepts(emptyNmdsFields(), concepts))
    } catch (e) {
      setNmdsParseError(e.message)
    } finally {
      setNmdsParsing(false)
    }
  }

  const handlePush = async () => {
    setStep('pushing')
    setError('')

    // Click-through mode (VITE_ENABLE_CLICK_THROUGH=true): skip the real
    // push and continue as if it succeeded. Leave this off to write
    // catalogue rows to Neon (GCS is optional via ENABLE_GCS).
    if (CLICK_THROUGH_ENABLED) {
      setResult({ tables_pushed: tablesToPush.length, metadata_id: 'click-through-demo' })
      setStep('done')
      return
    }

    try {
      const fd = new FormData()
      fd.append('tables_json', JSON.stringify(tablesToPush))
      fd.append('metadata_mode', effectiveMode)
      if (effectiveMode === 'existing') {
        fd.append('metadata_id', selectedMetaId)
      }
      fd.append('meta_title', form.title || '')
      fd.append('meta_product', form.product || '')
      fd.append('meta_category', form.category || '')
      fd.append('meta_geography', form.geography || '')
      fd.append('meta_frequency', form.frequency || '')
      fd.append('meta_time_period', form.time_period || '')
      fd.append('meta_data_source', form.data_source || '')
      fd.append('meta_description', form.description || '')
      fd.append('meta_last_updated', form.last_updated || '')
      fd.append('meta_future_release', form.future_release || '')
      fd.append('meta_key_statistics', form.key_statistics || '')
      fd.append('meta_remarks', form.remarks || '')
      if (excelFile) {
        fd.append('meta_excel', excelFile)
      }
      fd.append('meta_nmds_concepts', JSON.stringify(nmdsFieldsToList(nmdsFields)))

      const res = await fetch('/api/catalogue/push', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })))
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Unknown error' }))
        throw new Error(err.detail || 'Push failed')
      }
      const data = await res.json()
      setResult(data)
      setStep('done')
    } catch (e) {
      setError(e.message)
      setStep('error')
    }
  }

  const pushDisabled =
    step === 'pushing' || (effectiveMode === 'new' && !form.title.trim())

  const finishDone = () => {
    onPushed?.(result, form.title)
    onClose?.()
  }

  const wrapperClass = inline ? 'push-inline' : 'push-overlay'
  const bodyClass = inline ? 'push-modal push-modal-inline' : 'push-modal'

  return (
    <div className={wrapperClass}>
      <div className={bodyClass}>
        {!inline && (
          <div className="push-modal-header">
            <span className="push-modal-title">CREATE METADATA</span>
            <button className="push-close" onClick={onClose}>✕</button>
          </div>
        )}

        {step === 'done' && result && (
          <div className="push-success">
            <div className="push-success-icon">✓</div>
            <div className="push-success-msg">{result.tables_pushed} tables pushed successfully</div>
            <div className="push-success-detail">Metadata ID: {result.metadata_id}</div>
            <button className="push-btn" onClick={finishDone}>{inline ? 'Continue to classification →' : 'Done'}</button>
          </div>
        )}

        {step === 'error' && (
          <div className="push-error-state">
            <div className="push-error-msg">{error}</div>
            <button className="push-btn-secondary" onClick={() => setStep('nmds')}>Try Again</button>
          </div>
        )}

        {step === 'config' && (
          <>
            <div className="push-modal-body">
              {/* Section 1: scope */}
              <div className="push-section">
                <div className="push-section-title">Tables to push</div>
                <div className="push-radio-group">
                  <label className="push-radio">
                    <input
                      type="radio"
                      name="scope"
                      value="all"
                      checked={scope === 'all'}
                      onChange={() => setScope('all')}
                    />
                    All tables ({tables.length})
                  </label>
                  {groups && groups.map((g) => (
                    <label key={g.name} className="push-radio">
                      <input
                        type="radio"
                        name="scope"
                        value={g.name}
                        checked={scope === g.name}
                        onChange={() => setScope(g.name)}
                      />
                      Group: {g.name} ({g.table_ids.length})
                    </label>
                  ))}
                </div>
                <div className="push-scope-count">{tablesToPush.length} tables selected</div>
              </div>

              {/* Section 2: metadata group */}
              <div className="push-section">
                <div className="push-section-title">Metadata Group</div>
                <div className="push-radio-group">
                  <label className="push-radio">
                    <input
                      type="radio"
                      name="metaMode"
                      value="new"
                      checked={metaMode === 'new'}
                      onChange={() => handleMetaModeChange('new')}
                    />
                    Create new group
                  </label>
                  {existingGroups.length > 0 && (
                    <label className="push-radio">
                      <input
                        type="radio"
                        name="metaMode"
                        value="existing"
                        checked={metaMode === 'existing'}
                        onChange={() => handleMetaModeChange('existing')}
                      />
                      Add to existing group
                    </label>
                  )}
                </div>

                {metaMode === 'existing' && (
                  <div className="push-field">
                    <label className="push-label">Select group</label>
                    <select
                      className="push-input"
                      value={selectedMetaId}
                      onChange={(e) => selectExistingGroup(e.target.value)}
                    >
                      {existingGroups.map((g) => (
                        <option key={g.metadata_id} value={g.metadata_id}>
                          {g.title} ({g.table_count ?? 0} datasets)
                        </option>
                      ))}
                    </select>
                  </div>
                )}

                {metaMode === 'existing' && (
                  <div className={editedExisting ? 'push-mode-hint push-mode-hint-new' : 'push-mode-hint'}>
                    {editedExisting
                      ? 'You\'ve edited fields below — pushing will create a new group with these values instead of changing the existing one.'
                      : 'These tables will be added to the selected group as-is. Edit any field below to create a new group instead (e.g. for a new year\'s data).'}
                  </div>
                )}

                {excelFile && (
                  <div className="push-excel-row">
                    {!parsingExcel && !excelParseError && (
                      <div className="push-file-name">{excelFile.name} — fields filled in below</div>
                    )}
                    {parsingExcel && (
                      <div className="push-file-status">Reading metadata from {excelFile.name}…</div>
                    )}
                    {excelParseError && (
                      <div className="push-file-error">
                        Couldn't auto-fill from {excelFile.name}: {excelParseError}. You can still fill the fields in manually.
                      </div>
                    )}
                  </div>
                )}
              </div>
            </div>

            <MetadataSheetGrid
              rows={[{
                id: 'single',
                label: scope === 'all' ? 'All tables' : `Group: ${scope}`,
                values: form,
              }]}
              onChange={(_rowId, key, value) => handleFormChange(key, value)}
              note="Fields marked * are required. Every table in this scope shares this metadata."
            />

            <div className="push-modal-footer">
              {!inline && <button className="push-btn-secondary" onClick={onClose}>Cancel</button>}
              <button
                className="push-btn"
                onClick={() => setStep('nmds')}
                disabled={effectiveMode === 'new' && !form.title.trim()}
              >
                Show NMDS concept metadata →
              </button>
            </div>
          </>
        )}

        {(step === 'nmds' || step === 'pushing') && (
          <div className="push-modal-body">
            <NmdsConceptForm
              fields={nmdsFields}
              onFieldChange={(concept, value) => setNmdsFields((prev) => ({ ...prev, [concept]: value }))}
              onFileSelected={handleNmdsFileSelected}
              file={nmdsFile}
              parsing={nmdsParsing}
              parseError={nmdsParseError}
              fileMismatch={nmdsFileMismatch}
              onBack={() => setStep('config')}
              onSave={handlePush}
              saving={step === 'pushing'}
              saveDisabled={pushDisabled}
            />
          </div>
        )}
      </div>
    </div>
  )
}
