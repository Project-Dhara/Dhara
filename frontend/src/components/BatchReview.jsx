import { useEffect, useState } from 'react'
import { withLlmKeyHeaders } from '../llmKey'
import { withAuthHeaders } from '../auth'
import { CLICK_THROUGH_ENABLED } from '../clickThrough'
import MetadataSheetGrid from './MetadataSheetGrid'
import NmdsGroupPanel from './NmdsGroupPanel'
import { emptyNmdsFields, isNmdsFieldsComplete, nmdsFieldsToList, mergeNmdsConcepts, NMDS_CONCEPT_TEMPLATE } from '../nmdsConcepts'

const KNOWN_NMDS_CONCEPTS = new Set(NMDS_CONCEPT_TEMPLATE.filter((r) => !r.section).map((r) => r.concept))

// A group whose auto-fill left every catalogue field blank (e.g. no metadata
// workbook covered it) needs the same by-hand entry as the "no LLM key at
// all" case -- just scoped to that one group instead of the whole page, so
// the "Review auto-mapped" framing at the top doesn't mislead the user into
// thinking this group's blank fields are the reviewed (correct) result.
function isMetadataAutoMapped(metadata) {
  return Object.entries(metadata || {}).some(([key, value]) => key !== 'title' && String(value || '').trim())
}

function emptyNmdsGroupState() {
  return { fields: emptyNmdsFields(), file: null, appliedFrom: null, appliedToAll: false, parsing: false, parseError: '', fileMismatch: false }
}

function nmdsGroupLabel(group, groupIndex) {
  return group?.metadata?.title || group?.file_name || `Group ${groupIndex + 1}`
}

export default function BatchReview({ matchResult, metadataFiles, onDone, onCancel }) {
  const [groups, setGroups] = useState(matchResult.groups)
  const [assignments, setAssignments] = useState({}) // unmatchedTableIndex -> groupIndex ('' = skip)
  const [step, setStep] = useState('review') // review | pushing | done | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  // One NMDS upload/fields state per metadata group, keyed by group index.
  const [nmdsByGroup, setNmdsByGroup] = useState(() => groups.map(() => emptyNmdsGroupState()))
  const [nmdsModalGroup, setNmdsModalGroup] = useState(null) // group index whose fields modal is open, or null
  const [toast, setToast] = useState(null) // { type: 'warn' | 'success', message } | null

  useEffect(() => {
    if (!toast) return undefined
    const timer = setTimeout(() => setToast(null), 6000)
    return () => clearTimeout(timer)
  }, [toast])

  // BatchReview stays mounted across a trip back to the grouping step (step
  // 3) so metadata already typed in isn't lost -- but that also means its
  // own `groups` state, seeded once from the initial matchResult, never
  // picked up a regrouping made after that. Re-sync whenever the parent
  // hands down a new matchResult (which only happens on a grouping change),
  // so the metadata page reflects the current groups without a refresh.
  useEffect(() => {
    setGroups(matchResult.groups)
    setNmdsByGroup(matchResult.groups.map(() => emptyNmdsGroupState()))
    setAssignments({})
  }, [matchResult])

  const patchNmdsGroup = (groupIndex, patch) => {
    setNmdsByGroup((prev) => prev.map((g, i) => (i === groupIndex ? { ...g, ...patch } : g)))
  }

  const applyNmdsToAll = (groupIndex) => {
    const sourceState = nmdsByGroup[groupIndex] || emptyNmdsGroupState()
    const copy = { ...sourceState.fields }
    const appliedFrom = {
      groupLabel: nmdsGroupLabel(groups[groupIndex], groupIndex),
      fileName: sourceState.file?.name || null,
    }
    setNmdsByGroup((prev) => prev.map((g, i) => (
      i === groupIndex
        ? { ...g, appliedToAll: true }
        : {
            ...g,
            fields: { ...copy },
            appliedFrom,
            appliedToAll: true,
            file: null,
            parseError: '',
            fileMismatch: false,
            parsing: false,
          }
    )))
    setToast({ type: 'success', message: 'NMDS fields applied to all other groups.' })
  }

  const updateMetadata = (groupIndex, metadata) => {
    setGroups((prev) => prev.map((g, i) => (i === groupIndex ? { ...g, metadata } : g)))
  }

  const assignedCount = Object.values(assignments).filter((v) => v !== '' && v !== undefined).length
  const totalMatched = groups.reduce((sum, g) => sum + g.matched_tables.length, 0) + assignedCount
  // Nothing got auto-mapped anywhere -- same "fill it in yourself" framing
  // as the no-LLM-key case, just for a different reason (e.g. no metadata
  // workbook covered any group), so the heading doesn't claim a review of
  // an auto-mapping that never happened.
  const noneAutoMapped = groups.length > 0 && groups.every((g) => !isMetadataAutoMapped(g.metadata))
  const showFillInHeading = matchResult.llm_autofill_skipped_no_key || noneAutoMapped

  const handleNmdsFileSelected = async (groupIndex, file) => {
    patchNmdsGroup(groupIndex, { file, appliedFrom: null, appliedToAll: false, parseError: '', fileMismatch: false })
    if (!file) {
      patchNmdsGroup(groupIndex, { fields: emptyNmdsFields(), appliedFrom: null })
      return
    }

    patchNmdsGroup(groupIndex, { parsing: true })
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
      const mismatch = rows.length === 0 || matched / rows.length < 0.5
      // Reset before merging so a re-upload doesn't carry over values left
      // behind by a previous (possibly wrong) file.
      patchNmdsGroup(groupIndex, {
        fileMismatch: mismatch,
        fields: mergeNmdsConcepts(emptyNmdsFields(), concepts),
      })
    } catch (e) {
      patchNmdsGroup(groupIndex, { parseError: e.message })
    } finally {
      patchNmdsGroup(groupIndex, { parsing: false })
      setNmdsModalGroup(groupIndex)
    }
  }

  const handleSaveGroup = (groupIndex) => {
    const complete = isNmdsFieldsComplete(nmdsByGroup[groupIndex]?.fields || emptyNmdsFields())
    if (!complete) {
      setToast({ type: 'warn', message: 'NMDS fields not filled. Fill all NMDS details for this group.' })
      return
    }
    setToast({ type: 'success', message: 'Group data saved.' })
  }

  const handlePush = async () => {
    const allNmdsComplete = nmdsByGroup.every((g) => isNmdsFieldsComplete(g?.fields || emptyNmdsFields()))
    if (!allNmdsComplete) {
      setToast({ type: 'warn', message: 'NMDS fields not filled. Fill all NMDS details.' })
      return
    }

    setStep('pushing')
    setError('')
    setToast(null)

    // Click-through mode (VITE_ENABLE_CLICK_THROUGH=true): skip the real
    // push and continue as if it succeeded. Leave this off to write
    // catalogue rows (GCS is optional via ENABLE_GCS).
    if (CLICK_THROUGH_ENABLED) {
      setResult({ groups_pushed: groups.length, results: [] })
      setStep('done')
      return
    }

    try {
      // Always take the latest table objects from matchResult so title / table_id
      // corrections made in ReconcileIds (and patched onto matchResult) are what
      // get written to the catalogue — BatchReview's local `groups` copy can lag.
      const tablesByUid = {}
      matchResult.groups.forEach((g) => {
        g.matched_tables.forEach((mt) => {
          if (mt?.table?._uid) tablesByUid[mt.table._uid] = mt.table
        })
      })
      matchResult.unmatched_tables.forEach((u) => {
        if (u?.table?._uid) tablesByUid[u.table._uid] = u.table
      })

      const finalGroups = groups.map((g, gi) => ({
        ...g,
        matched_tables: g.matched_tables.map((mt) => ({
          ...mt,
          table: tablesByUid[mt.table?._uid] || mt.table,
        })),
        nmds_concepts: nmdsFieldsToList(nmdsByGroup[gi]?.fields || emptyNmdsFields()),
      }))
      matchResult.unmatched_tables.forEach((u, idx) => {
        const target = assignments[idx]
        if (target !== undefined && target !== '') {
          finalGroups[Number(target)].matched_tables.push({
            table: tablesByUid[u.table?._uid] || u.table,
            confidence: 'manual',
          })
        }
      })

      const fd = new FormData()
      fd.append('groups_json', JSON.stringify(finalGroups))
      metadataFiles.forEach((f) => fd.append('metadata_files', f))

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
          <button
            className="push-btn"
            onClick={() => onDone(label, (result.results || []).map((r) => r.metadata_id).filter(Boolean))}
          >
            Continue to classification →
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="batch-review">
      {step === 'review' && (
        <div className="batch-review-header">
          {showFillInHeading ? (
            <>
              <h2 className="batch-review-title-pill">Fill in Metadata</h2>
              <p>
                {totalMatched} table{totalMatched !== 1 ? 's' : ''} matched across {groups.length} metadata group{groups.length !== 1 ? 's' : ''}.
                Fields couldn't be auto-filled — please fill them in groupwise below, including the NMDS fields for each group. Your entries are kept as you move between groups. Nothing is pushed to the catalogue until you confirm below.
              </p>
            </>
          ) : (
            <>
              <h2 className="batch-review-title-pill">Review auto-mapped catalogue</h2>
              <p>
                {totalMatched} table{totalMatched !== 1 ? 's' : ''} matched across {groups.length} metadata group{groups.length !== 1 ? 's' : ''}.
                Kindly review the fields across all groups. Nothing is pushed until you confirm below.
              </p>
            </>
          )}
        </div>
      )}

      {error && <div className="error-banner"><strong>Error:</strong> {error}</div>}

      {step === 'review' && matchResult.llm_autofill_skipped_no_key && (
        <div className="warn-banner">
          <strong>LLM key not configured</strong> — metadata couldn't be auto-filled
          from the dataset and your KYDS entry. Set an API key in Settings to enable
          this next time, or fill the fields below in by hand.
        </div>
      )}

      {step !== 'done' && (
        <MetadataSheetGrid
          rows={groups.map((g, gi) => ({
            id: gi,
            label: g.file_name,
            values: g.metadata,
            manual: !matchResult.llm_autofill_skipped_no_key && !isMetadataAutoMapped(g.metadata),
          }))}
          onChange={(gi, key, value) => updateMetadata(gi, { ...groups[gi].metadata, [key]: value })}
          renderGroupFooter={(row, gi) => {
            const nmdsState = nmdsByGroup[gi] || emptyNmdsGroupState()
            return (
              <NmdsGroupPanel
                fields={nmdsState.fields}
                onFieldChange={(concept, value) =>
                  patchNmdsGroup(gi, { fields: { ...nmdsState.fields, [concept]: value } })
                }
                onFileSelected={(file) => handleNmdsFileSelected(gi, file)}
                file={nmdsState.file}
                appliedFrom={nmdsState.appliedFrom}
                parsing={nmdsState.parsing}
                parseError={nmdsState.parseError}
                fileMismatch={nmdsState.fileMismatch}
                modalOpen={nmdsModalGroup === gi}
                onOpenModal={() => setNmdsModalGroup(gi)}
                onCloseModal={() => setNmdsModalGroup(null)}
                groupLabel={row.label}
                onSaveGroup={() => handleSaveGroup(gi)}
                canApplyToAll={groups.length > 1}
                appliedToAll={!!nmdsState.appliedToAll}
                onApplyToAll={() => applyNmdsToAll(gi)}
              />
            )
          }}
        />
      )}

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

      <div className="push-modal-footer batch-review-footer">
        <button className="console-secondary-btn" onClick={onCancel} disabled={step === 'pushing'}>Cancel</button>
        <button className="console-primary-btn" disabled={totalMatched === 0 || step === 'pushing'} onClick={handlePush}>
          {step === 'pushing' ? 'Saving…' : 'Save Metadata →'}
        </button>
      </div>

      {toast && (
        <div className={`app-toast ${toast.type === 'success' ? 'app-toast-success' : 'app-toast-warn'}`} role="alert">
          <span>{toast.message}</span>
          <button type="button" className="app-toast-close" onClick={() => setToast(null)} aria-label="Dismiss">×</button>
        </div>
      )}
    </div>
  )
}
