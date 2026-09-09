'use client'

import { useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Check, Info, X } from 'lucide-react'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { withAuthHeaders } from '../lib/auth'
import { CLICK_THROUGH_ENABLED } from '../lib/clickThrough'
import { getConceptStandardConfig } from '../lib/metadataConcepts'
import { getMetadataStandard } from '../lib/settingsConfig'
import MetadataSheetGrid, { METADATA_COLUMNS } from './MetadataSheetGrid'
import NmdsGroupPanel from './NmdsGroupPanel'
import ConsoleStatusPlaceholder from './ConsoleStatusPlaceholder'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'
import { STATUS_TRANSITIONS } from '../lib/consoleStatusTransitions'

// A group whose auto-fill left every catalogue field blank (e.g. no metadata
// workbook covered it) needs the same by-hand entry as the "no LLM key at
// all" case -- just scoped to that one group instead of the whole page, so
// the "Review auto-mapped" framing at the top doesn't mislead the user into
// thinking this group's blank fields are the reviewed (correct) result.
function isMetadataAutoMapped(metadata, fieldKeys) {
  const entries = Object.entries(metadata || {})
  if (fieldKeys?.length) {
    return fieldKeys.some((key) => String(metadata?.[key] || '').trim())
  }
  return entries.some(([key, value]) => key !== 'title' && String(value || '').trim())
}

function emptyConceptGroupState(emptyFields) {
  return { fields: emptyFields(), file: null, appliedFrom: null, appliedToAll: false, parsing: false, parseError: '', fileMismatch: false }
}

function conceptGroupLabel(group, groupIndex) {
  return group?.metadata?.title || group?.metadata?.Indicator || group?.metadata?.Goal || group?.file_name || `Group ${groupIndex + 1}`
}

function seedConceptFieldsFromGroup(group, emptyFields, mergeConcepts) {
  const base = emptyFields()
  const conceptMeta = group?.concept_metadata
  if (conceptMeta && typeof conceptMeta === 'object') {
    for (const key of Object.keys(base)) {
      if (conceptMeta[key]) base[key] = String(conceptMeta[key])
    }
  }
  // SDG mode stores indicator fields directly on metadata for the sheet grid.
  for (const key of Object.keys(base)) {
    if (group?.metadata?.[key]) base[key] = String(group.metadata[key])
  }
  if (Array.isArray(group?.concepts) && group.concepts.length) {
    return mergeConcepts(base, group.concepts)
  }
  return base
}

export default function BatchReview({ matchResult, metadataFiles, onDone, onCancel }) {
  const conceptConfig = useMemo(() => getConceptStandardConfig(getMetadataStandard()), [])
  const sheetColumns = conceptConfig.sheetColumns || METADATA_COLUMNS
  const sheetFieldKeys = useMemo(() => sheetColumns.map((c) => c.key), [sheetColumns])

  const {
    shortName: standardName,
    topics,
    placeholders,
    emptyFields,
    isComplete,
    fieldsToList,
    mergeConcepts,
    standard,
    usesSdgSheet,
  } = conceptConfig

  const [groups, setGroups] = useState(matchResult.groups)
  const [assignments, setAssignments] = useState({}) // unmatchedTableIndex -> groupIndex ('' = skip)
  const [step, setStep] = useState('review') // review | pushing | done | error
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  // One concept upload/fields state per metadata group, keyed by group index.
  const [nmdsByGroup, setNmdsByGroup] = useState(() => groups.map((g) => ({
    ...emptyConceptGroupState(emptyFields),
    fields: seedConceptFieldsFromGroup(g, emptyFields, mergeConcepts),
  })))
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
    setNmdsByGroup(matchResult.groups.map((g) => ({
      ...emptyConceptGroupState(emptyFields),
      fields: seedConceptFieldsFromGroup(g, emptyFields, mergeConcepts),
    })))
    setAssignments({})
  }, [matchResult, emptyFields, mergeConcepts])

  const patchNmdsGroup = (groupIndex, patch) => {
    setNmdsByGroup((prev) => prev.map((g, i) => (i === groupIndex ? { ...g, ...patch } : g)))
  }

  const applyNmdsToAll = (groupIndex) => {
    const sourceState = nmdsByGroup[groupIndex] || emptyConceptGroupState(emptyFields)
    const copy = { ...sourceState.fields }
    const appliedFrom = {
      groupLabel: conceptGroupLabel(groups[groupIndex], groupIndex),
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
    if (usesSdgSheet) {
      setGroups((prev) => prev.map((g, i) => (
        i === groupIndex ? g : { ...g, metadata: { ...(g.metadata || {}), ...copy }, concept_metadata: { ...copy } }
      )))
    }
    setToast({ type: 'success', message: `${standardName} fields applied to all other groups.` })
  }

  const updateMetadata = (groupIndex, metadata) => {
    setGroups((prev) => prev.map((g, i) => (i === groupIndex ? { ...g, metadata } : g)))
    if (usesSdgSheet) {
      const nextFields = { ...emptyFields() }
      for (const key of Object.keys(nextFields)) {
        if (metadata?.[key] != null) nextFields[key] = String(metadata[key])
      }
      patchNmdsGroup(groupIndex, { fields: nextFields })
    }
  }

  const updateConceptField = (groupIndex, concept, value) => {
    const current = nmdsByGroup[groupIndex] || emptyConceptGroupState(emptyFields)
    const nextFields = { ...current.fields, [concept]: value }
    patchNmdsGroup(groupIndex, { fields: nextFields })
    if (usesSdgSheet) {
      setGroups((prev) => prev.map((g, i) => (
        i === groupIndex
          ? { ...g, metadata: { ...(g.metadata || {}), [concept]: value }, concept_metadata: nextFields }
          : g
      )))
    }
  }

  const assignedCount = Object.values(assignments).filter((v) => v !== '' && v !== undefined).length
  const totalMatched = groups.reduce((sum, g) => sum + g.matched_tables.length, 0) + assignedCount
  // Nothing got auto-mapped anywhere -- same "fill it in yourself" framing
  // as the no-LLM-key case, just for a different reason (e.g. no metadata
  // workbook covered any group), so the heading doesn't claim a review of
  // an auto-mapping that never happened.
  const noneAutoMapped = groups.length > 0 && groups.every((g) => !isMetadataAutoMapped(g.metadata, usesSdgSheet ? sheetFieldKeys : null))
  const someAutoMapped = groups.some((g) => isMetadataAutoMapped(g.metadata, usesSdgSheet ? sheetFieldKeys : null))
  const autofillErrors = Array.isArray(matchResult.autofill_errors) ? matchResult.autofill_errors : []
  const failedGroupIndexes = new Set(
    autofillErrors.map((e) => e.index).filter((i) => Number.isInteger(i)),
  )
  const failedGroupNames = new Set(
    autofillErrors.map((e) => String(e.group || '').trim().toLowerCase()).filter((n) => n && n !== 'all'),
  )
  const groupFailedAutofill = (g, gi) => {
    if (failedGroupIndexes.has(gi)) return true
    const name = String(g?.file_name || g?.metadata?.title || g?.metadata?.Indicator || '').trim().toLowerCase()
    return Boolean(name && failedGroupNames.has(name))
  }
  // Only treat the whole page as "fill everything" when nothing was mapped.
  // Partial autofill success should keep the review framing for filled groups.
  const showFillInHeading = matchResult.llm_autofill_skipped_no_key || matchResult.kyds_missing || noneAutoMapped

  const autofillReasonSummary = (() => {
    if (matchResult.llm_autofill_skipped_no_key) {
      return 'LLM key not configured — set an API key in Settings, or fill the fields below by hand.'
    }
    if (matchResult.kyds_missing) {
      return 'Know Your Dataset is missing — fill KYDS first for better auto-mapping, or enter fields below by hand.'
    }
    if (autofillErrors.length > 0 && someAutoMapped) {
      const sample = autofillErrors.slice(0, 3).map((e) => e.group || e.error).filter(Boolean)
      const more = autofillErrors.length > 3 ? ` (+${autofillErrors.length - 3} more)` : ''
      return `Auto-fill succeeded for other groups. Failed for ${autofillErrors.length}: ${sample.join(' · ')}${more}. Only those groups need manual entry (marked below).`
    }
    if (autofillErrors.length > 0) {
      const sample = autofillErrors.slice(0, 3).map((e) => {
        const group = e.group && e.group !== 'all' ? `${e.group}: ` : ''
        return `${group}${e.error}`
      })
      const more = autofillErrors.length > 3 ? ` (+${autofillErrors.length - 3} more)` : ''
      return `Auto-fill failed for ${autofillErrors.length} group${autofillErrors.length !== 1 ? 's' : ''}: ${sample.join(' · ')}${more}. You can still fill every field below manually.`
    }
    if (noneAutoMapped) {
      return usesSdgSheet
        ? 'No SDG indicator fields were auto-mapped for these groups. Fill them in manually below.'
        : 'No catalogue fields were auto-mapped for these groups. Fill them in manually below.'
    }
    return null
  })()

  const handleNmdsFileSelected = async (groupIndex, file) => {
    patchNmdsGroup(groupIndex, { file, appliedFrom: null, appliedToAll: false, parseError: '', fileMismatch: false })
    if (!file) {
      patchNmdsGroup(groupIndex, { fields: emptyFields(), appliedFrom: null })
      if (usesSdgSheet) {
        setGroups((prev) => prev.map((g, i) => (
          i === groupIndex
            ? { ...g, metadata: { ...(g.catalogue_metadata || {}) }, concept_metadata: emptyFields() }
            : g
        )))
      }
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
      const mergePreview = mergeConcepts(emptyFields(), rows)
      const filledFromFile = Object.values(mergePreview).filter((v) => String(v || '').trim()).length
      const fieldCount = Object.keys(emptyFields()).length
      // A wrong file most often has no matching concept/code rows at all.
      const mismatch = rows.length === 0 || filledFromFile / Math.max(fieldCount, 1) < 0.5
      // Reset before merging so a re-upload doesn't carry over values left
      // behind by a previous (possibly wrong) file.
      const merged = mergePreview
      patchNmdsGroup(groupIndex, {
        fileMismatch: mismatch,
        fields: merged,
      })
      if (usesSdgSheet) {
        setGroups((prev) => prev.map((g, i) => (
          i === groupIndex
            ? { ...g, metadata: { ...(g.metadata || {}), ...merged }, concept_metadata: merged }
            : g
        )))
      }
    } catch (e) {
      patchNmdsGroup(groupIndex, { parseError: e.message })
    } finally {
      patchNmdsGroup(groupIndex, { parsing: false })
      if (!usesSdgSheet) setNmdsModalGroup(groupIndex)
    }
  }

  const handleSaveGroup = (groupIndex) => {
    const complete = isComplete(nmdsByGroup[groupIndex]?.fields || emptyFields())
    if (!complete) {
      setToast({ type: 'warn', message: `${standardName} fields not filled. Fill all ${standardName} details for this group.` })
      return
    }
    setToast({ type: 'success', message: 'Group data saved.' })
  }

  const handlePush = async () => {
    const allComplete = nmdsByGroup.every((g) => isComplete(g?.fields || emptyFields()))
    if (!allComplete) {
      setToast({ type: 'warn', message: `${standardName} fields not filled. Fill all ${standardName} details.` })
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
      ;(matchResult.unmatched_tables || []).forEach((u) => {
        if (u?.table?._uid) tablesByUid[u.table._uid] = u.table
      })

      const finalGroups = groups.map((g, gi) => {
        const conceptFields = nmdsByGroup[gi]?.fields || emptyFields()
        const conceptList = fieldsToList(conceptFields)
        let metadata = g.metadata || {}
        if (usesSdgSheet) {
          const catalogue = g.catalogue_metadata || {}
          metadata = {
            ...catalogue,
            title: catalogue.title || conceptFields.Indicator || conceptFields.Goal || g.file_name || '',
            description: catalogue.description || conceptFields.Target || '',
            data_source: catalogue.data_source || conceptFields['International organisations(s) responsible for global monitoring'] || '',
            last_updated: catalogue.last_updated || conceptFields['Metadata update'] || '',
            remarks: catalogue.remarks || conceptFields['Related indicators'] || '',
          }
        }
        return {
          ...g,
          metadata,
          matched_tables: g.matched_tables.map((mt) => ({
            ...mt,
            table: tablesByUid[mt.table?._uid] || mt.table,
          })),
          metadata_standard: standard,
          nmds_concepts: {
            standard,
            concepts: conceptList,
          },
        }
      })
      ;(matchResult.unmatched_tables || []).forEach((u, idx) => {
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

  if (step === 'pushing') {
    return (
      <ConsoleStatusPlaceholder
        title={STATUS_TRANSITIONS.metadataToClassify.title}
        subtitle={STATUS_TRANSITIONS.metadataToClassify.subtitle}
        steps={STATUS_TRANSITIONS.metadataToClassify.steps}
        msPerStep={1200}
        onComplete={() => {}}
      />
    )
  }

  if (step === 'done' && result) {
    const label = groups[0]?.metadata?.title || groups[0]?.file_name || ''
    return (
      <div className="mx-auto flex max-w-[920px] flex-col gap-6">
        <div className="flex flex-col items-center gap-2.5 px-5 py-10 text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-full bg-[#e6f7f3] text-[#0a6e57]">
            <Check className="h-8 w-8" strokeWidth={2.5} aria-hidden />
          </div>
          <div className="text-base font-bold text-ink">
            {result.groups_pushed} metadata group{result.groups_pushed !== 1 ? 's' : ''} pushed
          </div>
          <Button
            size="sm"
            onClick={() => onDone(label, (result.results || []).map((r) => r.metadata_id).filter(Boolean))}
          >
            Continue to classification
            <ArrowRight className="ml-1.5 inline h-4 w-4" strokeWidth={2} aria-hidden />
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
                Please fill them in groupwise below, including the NMDS fields for each group. Your entries are kept as you move between groups. Nothing is pushed to the catalogue until you confirm below.
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

      {step === 'review' && autofillReasonSummary && (
        <div className="rounded-lg border border-[#f3c98b] bg-[#fffaf1] px-4 py-3 text-sm leading-relaxed text-[#8a5a12]">
          <strong>Why auto-fill didn’t complete</strong>
          <div className="mt-1 [overflow-wrap:anywhere]">{autofillReasonSummary}</div>
        </div>
      )}

      {step !== 'done' && (
        <MetadataSheetGrid
          columns={sheetColumns}
          rows={groups.map((g, gi) => ({
            id: gi,
            label: g.file_name,
            values: g.metadata,
            manual: groupFailedAutofill(g, gi) || (!isMetadataAutoMapped(g.metadata, usesSdgSheet ? sheetFieldKeys : null) && !matchResult.llm_autofill_skipped_no_key),
          }))}
          onChange={(gi, key, value) => updateMetadata(gi, { ...groups[gi].metadata, [key]: value })}
          renderGroupFooter={(row, gi) => {
            const nmdsState = nmdsByGroup[gi] || emptyConceptGroupState(emptyFields)
            return (
              <NmdsGroupPanel
                fields={nmdsState.fields}
                onFieldChange={(concept, value) => updateConceptField(gi, concept, value)}
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
                standardName={standardName}
                topics={topics}
                placeholders={placeholders}
                fieldsToList={fieldsToList}
                hideFieldEditor={usesSdgSheet}
              />
            )
          }}
        />
      )}

      {matchResult.unmatched_tables?.length > 0 && (
        <div className="flex flex-col gap-2 rounded-[10px] border border-[#f3c98b] bg-[#fffaf1] p-4">
          <div className="flex items-center justify-between gap-2.5">
            <span className="inline-flex items-center gap-1.5 text-[13.5px] font-bold text-ink">
              <AlertTriangle className="h-4 w-4 text-[#c9610f]" strokeWidth={2} aria-hidden />
              Extracted tables with no metadata match ({matchResult.unmatched_tables.length})
            </span>
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
                        className="rounded-md border border-line bg-surface px-2.5 py-1.5 text-[13px] text-ink transition-shadow duration-200 focus:border-teal focus:shadow-focus-ring focus:outline-none"
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

      {matchResult.unmatched_inventory?.length > 0 && (
        <div className="flex flex-col gap-2 rounded-[10px] border border-line bg-[#F7F3EA] p-4">
          <div className="flex items-center justify-between gap-2.5">
            <span className="inline-flex items-center gap-1.5 text-[13.5px] font-bold text-ink">
              <Info className="h-4 w-4 text-teal" strokeWidth={2} aria-hidden />
              Metadata entries with no matching table ({matchResult.unmatched_inventory.length})
            </span>
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
          {step === 'pushing' ? 'Saving…' : (
            <span className="inline-flex items-center gap-1.5">
              Save Metadata
              <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
            </span>
          )}
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
          <button type="button" className="flex h-6 w-6 items-center justify-center rounded px-0.5 text-current opacity-70 hover:opacity-100" onClick={() => setToast(null)} aria-label="Dismiss">
            <X className="h-4 w-4" strokeWidth={1.75} />
          </button>
        </div>
      )}
    </div>
  )
}