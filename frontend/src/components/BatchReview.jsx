'use client'

import { useEffect, useState } from 'react'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { withAuthHeaders } from '../lib/auth'
import { CLICK_THROUGH_ENABLED } from '../lib/clickThrough'
import MetadataSheetGrid from './MetadataSheetGrid'
import NmdsGroupPanel from './NmdsGroupPanel'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'
import { emptyNmdsFields, isNmdsFieldsComplete, nmdsFieldsToList, mergeNmdsConcepts, NMDS_CONCEPT_TEMPLATE } from '../lib/nmdsConcepts'

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
      <div className="mx-auto flex max-w-[920px] flex-col gap-6">
        <div className="flex flex-col items-center gap-2.5 px-5 py-10 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#e6f7f3] text-4xl text-[#0a6e57]">✓</div>
          <div className="text-base font-bold text-ink">
            {result.groups_pushed} metadata group{result.groups_pushed !== 1 ? 's' : ''} pushed
          </div>
          <Button
            size="sm"
            onClick={() => onDone(label, (result.results || []).map((r) => r.metadata_id).filter(Boolean))}
          >
            Continue to classification →
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="mx-auto flex max-w-[920px] flex-col gap-6">
      {step === 'review' && (
        <div className="mb-1 text-center">
          {showFillInHeading ? (
            <>
              <h2 className="text-xl font-bold text-ink">Fill in Metadata</h2>
              <p className="m-0 text-[13px] leading-relaxed text-ink-soft">
                {totalMatched} table{totalMatched !== 1 ? 's' : ''} matched across {groups.length} metadata group{groups.length !== 1 ? 's' : ''}.
                Fields couldn't be auto-filled — please fill them in groupwise below, including the NMDS fields for each group. Your entries are kept as you move between groups. Nothing is pushed to the catalogue until you confirm below.
              </p>
            </>
          ) : (
            <>
              <h2 className="text-xl font-bold text-ink">Review auto-mapped catalogue</h2>
              <p className="m-0 text-[13px] leading-relaxed text-ink-soft">
                {totalMatched} table{totalMatched !== 1 ? 's' : ''} matched across {groups.length} metadata group{groups.length !== 1 ? 's' : ''}.
                Kindly review the fields across all groups. Nothing is pushed until you confirm below.
              </p>
            </>
          )}
        </div>
      )}

      {error && <ErrorBanner>{error}</ErrorBanner>}

      {step === 'review' && matchResult.llm_autofill_skipped_no_key && (
        <div className="rounded-lg border border-[#f3c98b] bg-[#fffaf1] px-4 py-3 text-sm leading-relaxed text-[#8a5a12]">
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
        <div className="flex flex-col gap-2 rounded-[10px] border border-[#f3c98b] bg-[#fffaf1] p-4">
          <div className="flex items-center justify-between gap-2.5">
            <span className="text-[13.5px] font-bold text-ink">⚠ Extracted tables with no metadata match ({matchResult.unmatched_tables.length})</span>
          </div>
          <p className="m-0 text-xs leading-relaxed text-ink-soft">
            Not included in the push below unless you assign them to a group manually.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[12.5px]">
              <thead><tr>
                <th className="border-b border-line px-2 py-1.5 text-left font-semibold text-ink-soft">Dataset ID</th>
                <th className="border-b border-line px-2 py-1.5 text-left font-semibold text-ink-soft">Title</th>
                <th className="border-b border-line px-2 py-1.5 text-left font-semibold text-ink-soft">Assign to group</th>
              </tr></thead>
              <tbody>
                {matchResult.unmatched_tables.map((u, idx) => (
                  <tr key={idx}>
                    <td className="whitespace-nowrap border-b border-[#f1ebdf] px-2 py-1.5 align-top font-sans text-[11.5px] text-teal">{u.table.id}</td>
                    <td className="border-b border-[#f1ebdf] px-2 py-1.5 align-top text-ink">{u.table.description || u.table.title}</td>
                    <td className="border-b border-[#f1ebdf] px-2 py-1.5 align-top">
                      <select
                        className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink focus:border-transparent focus:outline focus:outline-2 focus:outline-[#7fbfd4]"
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
        </div>
      )}

      {matchResult.unmatched_inventory.length > 0 && (
        <div className="flex flex-col gap-2 rounded-[10px] border border-line bg-[#F7F3EA] p-4">
          <div className="flex items-center justify-between gap-2.5">
            <span className="text-[13.5px] font-bold text-ink">ℹ Metadata entries with no matching table ({matchResult.unmatched_inventory.length})</span>
          </div>
          <p className="m-0 text-xs leading-relaxed text-ink-soft">
            Cataloged in the metadata file but no uploaded dataset table matched them — likely missing from what was uploaded.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full border-collapse text-[12.5px]">
              <thead><tr>
                <th className="border-b border-line px-2 py-1.5 text-left font-semibold text-ink-soft">Unique dataset ID</th>
                <th className="border-b border-line px-2 py-1.5 text-left font-semibold text-ink-soft">Description</th>
              </tr></thead>
              <tbody>
                {matchResult.unmatched_inventory.map((u, idx) => (
                  <tr key={idx}>
                    <td className="whitespace-nowrap border-b border-[#f1ebdf] px-2 py-1.5 align-top font-sans text-[11.5px] text-teal">{u.inventory_item.unique_dataset_id}</td>
                    <td className="border-b border-[#f1ebdf] px-2 py-1.5 align-top text-ink">{u.inventory_item.short_description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="m-0 flex justify-end gap-2 border-0 p-0">
        <Button variant="secondary" onClick={onCancel} disabled={step === 'pushing'}>Cancel</Button>
        <Button disabled={totalMatched === 0 || step === 'pushing'} onClick={handlePush}>
          {step === 'pushing' ? 'Saving…' : 'Save Metadata →'}
        </Button>
      </div>

      {toast && (
        <div
          className={`fixed right-6 top-6 z-[1200] flex items-center gap-3 rounded-[10px] py-3 pl-[18px] pr-4 font-sans text-sm font-medium leading-snug shadow-lg ${
            toast.type === 'success' ? 'bg-[#2f9e57] text-white' : 'bg-[#e2711d] text-[#111]'
          }`}
          role="alert"
        >
          <span>{toast.message}</span>
          <button type="button" className="rounded px-0.5 text-lg leading-none text-current opacity-70 hover:opacity-100" onClick={() => setToast(null)} aria-label="Dismiss">×</button>
        </div>
      )}
    </div>
  )
}