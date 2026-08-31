import { useState } from 'react'
import { withLlmKeyHeaders } from '../llmKey'
import { withAuthHeaders } from '../auth'
import { CLICK_THROUGH_ENABLED } from '../clickThrough'
import MetadataSheetGrid from './MetadataSheetGrid'
import NmdsConceptForm from './NmdsConceptForm'
import { emptyNmdsFields, nmdsFieldsToList, mergeNmdsConcepts } from '../nmdsConcepts'

const CONFIDENCE_LABEL = {
  exact: 'Exact ID match',
  stem: 'ID match (ignoring year/version typo)',
  code: 'Table-code match',
  'code+keyword': 'Table-code + keyword match',
  grouped: 'Grouped with siblings (no exact row)',
  manual: 'Manually assigned',
}


export default function BatchReview({ matchResult, metadataFiles, onDone, onCancel }) {
  const [groups, setGroups] = useState(matchResult.groups)
  const [assignments, setAssignments] = useState({}) // unmatchedTableIndex -> groupIndex ('' = skip)
  const [step, setStep] = useState('review') // review | nmds | pushing | done | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  const [nmdsFields, setNmdsFields] = useState(emptyNmdsFields())
  const [nmdsFile, setNmdsFile] = useState(null)
  const [nmdsParsing, setNmdsParsing] = useState(false)
  const [nmdsParseError, setNmdsParseError] = useState('')

  const updateMetadata = (groupIndex, metadata) => {
    setGroups((prev) => prev.map((g, i) => (i === groupIndex ? { ...g, metadata } : g)))
  }

  const assignedCount = Object.values(assignments).filter((v) => v !== '' && v !== undefined).length
  const totalMatched = groups.reduce((sum, g) => sum + g.matched_tables.length, 0) + assignedCount

  const handleNmdsFileSelected = async (file) => {
    setNmdsFile(file)
    setNmdsParseError('')
    if (!file) return

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
      setNmdsFields((prev) => mergeNmdsConcepts(prev, concepts))
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
      setResult({ groups_pushed: groups.length })
      setStep('done')
      return
    }

    try {
      const finalGroups = groups.map((g) => ({ ...g, matched_tables: [...g.matched_tables] }))
      matchResult.unmatched_tables.forEach((u, idx) => {
        const target = assignments[idx]
        if (target !== undefined && target !== '') {
          finalGroups[Number(target)].matched_tables.push({ table: u.table, confidence: 'manual' })
        }
      })

      const fd = new FormData()
      fd.append('groups_json', JSON.stringify(finalGroups))
      metadataFiles.forEach((f) => fd.append('metadata_files', f))
      fd.append('nmds_concepts_json', JSON.stringify(nmdsFieldsToList(nmdsFields)))

      const res = await fetch('/api/catalogue/batch-push', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })))
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Push failed' }))
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

  if (step === 'done' && result) {
    const label = groups[0]?.metadata?.title || groups[0]?.file_name || ''
    return (
      <div className="batch-review">
        <div className="push-success">
          <div className="push-success-icon">✓</div>
          <div className="push-success-msg">
            {result.groups_pushed} metadata group{result.groups_pushed !== 1 ? 's' : ''} pushed
          </div>
          <button className="push-btn" onClick={() => onDone(label)}>Continue to classification →</button>
        </div>
      </div>
    )
  }

  return (
    <div className="batch-review">
      <div className="batch-review-header">
        <h2>Review auto-mapped catalogue</h2>
        <p>
          {totalMatched} table{totalMatched !== 1 ? 's' : ''} matched across {groups.length} metadata group{groups.length !== 1 ? 's' : ''}.
          Nothing is pushed until you confirm below.
        </p>
      </div>

      {error && <div className="error-banner"><strong>Error:</strong> {error}</div>}

      {step === 'nmds' || step === 'pushing' || step === 'error' ? (
        <NmdsConceptForm
          fields={nmdsFields}
          onFieldChange={(concept, value) => setNmdsFields((prev) => ({ ...prev, [concept]: value }))}
          onFileSelected={handleNmdsFileSelected}
          file={nmdsFile}
          parsing={nmdsParsing}
          parseError={nmdsParseError}
          onBack={() => setStep('review')}
          onSave={handlePush}
          saving={step === 'pushing'}
          saveDisabled={step === 'pushing'}
        />
      ) : (
        <>
      <MetadataSheetGrid
        rows={groups.map((g, gi) => ({ id: gi, label: g.file_name, values: g.metadata }))}
        onChange={(gi, key, value) => updateMetadata(gi, { ...groups[gi].metadata, [key]: value })}
        note="Fields marked * are required. One card per metadata group."
      />

      {groups.map((g, gi) => (
        g.matched_tables.length > 0 && (
          <div className="batch-group" key={gi}>
            <div className="batch-group-header">
              <span className="batch-group-file">{g.file_name}</span>
              <span className="batch-group-count">{g.matched_tables.length} table{g.matched_tables.length !== 1 ? 's' : ''}</span>
            </div>
            <table className="batch-table-list">
              <thead>
                <tr><th>Dataset ID</th><th>Title</th><th>Match basis</th></tr>
              </thead>
              <tbody>
                {g.matched_tables.map((mt, ti) => (
                  <tr key={ti}>
                    <td className="batch-table-id">{mt.table.id}</td>
                    <td>{mt.table.description || mt.table.title}</td>
                    <td>
                      <span className="batch-confidence" data-confidence={mt.confidence}>
                        {CONFIDENCE_LABEL[mt.confidence] || mt.confidence}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ))}

      {matchResult.unmatched_tables.length > 0 && (
        <div className="batch-group batch-group-warn">
          <div className="batch-group-header">
            <span className="batch-group-file">⚠ Extracted tables with no metadata match ({matchResult.unmatched_tables.length})</span>
          </div>
          <p className="batch-hint">
            Not included in the push below unless you assign them to a group manually.
          </p>
          <table className="batch-table-list">
            <thead><tr><th>Dataset ID</th><th>Title</th><th>Assign to group</th></tr></thead>
            <tbody>
              {matchResult.unmatched_tables.map((u, idx) => (
                <tr key={idx}>
                  <td className="batch-table-id">{u.table.id}</td>
                  <td>{u.table.description || u.table.title}</td>
                  <td>
                    <select
                      className="push-input"
                      value={assignments[idx] ?? ''}
                      onChange={(e) => setAssignments((prev) => ({ ...prev, [idx]: e.target.value }))}
                    >
                      <option value="">Skip (don't push)</option>
                      {groups.map((g, gi) => (
                        <option key={gi} value={gi}>{g.metadata.title || g.file_name}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {matchResult.unmatched_inventory.length > 0 && (
        <div className="batch-group batch-group-info">
          <div className="batch-group-header">
            <span className="batch-group-file">ℹ Metadata entries with no matching table ({matchResult.unmatched_inventory.length})</span>
          </div>
          <p className="batch-hint">
            Cataloged in the metadata file but no uploaded dataset table matched them — likely missing from what was uploaded.
          </p>
          <table className="batch-table-list">
            <thead><tr><th>Unique dataset ID</th><th>Description</th></tr></thead>
            <tbody>
              {matchResult.unmatched_inventory.map((u, idx) => (
                <tr key={idx}>
                  <td className="batch-table-id">{u.inventory_item.unique_dataset_id}</td>
                  <td>{u.inventory_item.short_description}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
        </>
      )}

      {step !== 'nmds' && step !== 'pushing' && step !== 'error' && (
      <div className="push-modal-footer batch-review-footer">
        <button className="console-secondary-btn" onClick={onCancel}>Cancel</button>
        <button className="console-primary-btn" disabled={totalMatched === 0} onClick={() => setStep('nmds')}>
          Show NMDS concept metadata →
        </button>
      </div>
      )}
    </div>
  )
}
