'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AlertTriangle, ArrowRight, Info } from 'lucide-react'
import { withLlmKeyHeaders } from '../../lib/llmKey'
import { withAuthHeaders } from '../../lib/auth'
import { CLICK_THROUGH_ENABLED } from '../../lib/clickThrough'
import { getConceptStandardConfig } from '../../lib/metadataConcepts'
import { getMetadataRequiredFields, getMetadataStandard } from '../../lib/settingsConfig'
import { fillGroupMetadataForMatchResult } from '../../lib/postPreview'
import { onKydsChanged } from '../../lib/kydsEvents'
import { useApp } from '../../context/AppContext'
import MetadataSheetGrid, {
  METADATA_COLUMNS,
  applyRequiredFieldsToColumns,
  missingRequiredSheetFields,
} from './MetadataSheetGrid'
import NmdsGroupPanel from './NmdsGroupPanel'
import ConsoleStatusPlaceholder from './ConsoleStatusPlaceholder'
import Button from '../ui/Button'
import Combobox from '../ui/Combobox'
import ErrorBanner from '../ui/ErrorBanner'
import Toast from '../ui/Toast'
import { STATUS_TRANSITIONS } from '../../lib/consoleStatusTransitions'

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

/** Product is dataset-wide — keep every group's value identical. */
function shareProductAcrossGroups(groups) {
  if (!Array.isArray(groups) || groups.length === 0) return groups
  const shared = groups.map((g) => String(g?.metadata?.product || '').trim()).find(Boolean) || ''
  return groups.map((g) => {
    const current = String(g?.metadata?.product || '')
    if (current === shared) return g
    return { ...g, metadata: { ...(g.metadata || {}), product: shared } }
  })
}

function emptyConceptGroupState(emptyFields) {
  return { fields: emptyFields(), file: null, appliedFrom: null, appliedToAll: false, parsing: false, parseError: '', fileMismatch: false }
}

function conceptGroupLabel(group, groupIndex) {
  return group?.metadata?.title || group?.metadata?.Indicator || group?.metadata?.Goal || group?.file_name || `Group ${groupIndex + 1}`
}

/** Keep steward overlays only — full rows are hydrated server-side from staging / pdf_store. */
function slimTableForPush(table) {
  if (!table || typeof table !== 'object') return table
  const out = {}
  ;[
    '_uid', 'id', 'table_id', 'title', 'sheet',
    'source_file', 'source_type', 'original_excel_url', 'source_excel_url',
  ].forEach((key) => {
    if (table[key] != null && table[key] !== '') out[key] = table[key]
  })
  return out
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

export default function BatchReview({
  matchResult,
  metadataFiles,
  onDone,
  onCancel,
  pdfJobId = null,
  onMatchResultChange,
  onGoSettings,
}) {
  const { keySaved } = useApp()
  const hasLlmKey = keySaved
  const conceptConfig = useMemo(() => getConceptStandardConfig(getMetadataStandard()), [])
  const sheetColumns = useMemo(() => {
    const base = conceptConfig.sheetColumns || METADATA_COLUMNS
    // SDG sheet already marks every concept required; NMDS merges Settings → Metadata configuration.
    if (conceptConfig.usesSdgSheet) return base
    return applyRequiredFieldsToColumns(base, getMetadataRequiredFields())
  }, [conceptConfig])
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

  const [groups, setGroups] = useState(() => shareProductAcrossGroups(matchResult.groups))
  const [assignments, setAssignments] = useState({}) // unmatchedTableIndex -> groupIndex ('' = skip)
  const [step, setStep] = useState('review') // review | pushing | error
  const [error, setError] = useState('')

  // One concept upload/fields state per metadata group, keyed by group index.
  const [nmdsByGroup, setNmdsByGroup] = useState(() => groups.map((g) => ({
    ...emptyConceptGroupState(emptyFields),
    fields: seedConceptFieldsFromGroup(g, emptyFields, mergeConcepts),
  })))
  const [nmdsModalGroup, setNmdsModalGroup] = useState(null) // group index whose fields modal is open, or null
  const [toast, setToast] = useState(null) // { type: 'warn' | 'success', message } | null
  const [refilling, setRefilling] = useState(false)
  const [autofillKick, setAutofillKick] = useState(0)
  // Avoid re-running autofill in a loop for the same blocker state (e.g. still
  // missing KYDS). Cleared when the steward saves KYDS or clicks Retry.
  const autofillAttemptTokenRef = useRef('')
  // Last kick value we already auto-ran for — used to skip a redundant second
  // Stage 4 call after continue-to-metadata already filled, while still
  // allowing KYDS-save / Retry kicks to re-run.
  const lastAutofillKickRef = useRef(0)
  // Per-group field keys still carrying an AI autofill value (cleared when the steward edits).
  const [aiFilledByGroup, setAiFilledByGroup] = useState(() => {
    const fromResult = matchResult?.ai_filled_fields_by_group
    if (fromResult && typeof fromResult === 'object') {
      return Object.fromEntries(
        Object.entries(fromResult).map(([k, fields]) => [Number(k), new Set(fields || [])]),
      )
    }
    const next = {}
    ;(matchResult?.groups || []).forEach((g, i) => {
      if (g?.llm_filled && Array.isArray(g.llm_filled_fields)) next[i] = new Set(g.llm_filled_fields)
    })
    return next
  })

  useEffect(() => {
    if (!toast) return undefined
    const timer = setTimeout(() => setToast(null), 6000)
    return () => clearTimeout(timer)
  }, [toast])

  // Re-attempt Stage 4 fill after the steward submits/edits KYDS (common case:
  // land on metadata → fill KYDS → fields were still empty because fill ran
  // before KYDS existed).
  useEffect(() => onKydsChanged(() => {
    autofillAttemptTokenRef.current = ''
    setAutofillKick((n) => n + 1)
  }), [])

  // BatchReview stays mounted across a trip back to the grouping step (step
  // 3) so metadata already typed in isn't lost -- but that also means its
  // own `groups` state, seeded once from the initial matchResult, never
  // picked up a regrouping made after that. Re-sync whenever the parent
  // hands down a new matchResult (which only happens on a grouping change),
  // so the metadata page reflects the current groups without a refresh.
  useEffect(() => {
    setGroups(shareProductAcrossGroups(matchResult.groups))
    setNmdsByGroup(matchResult.groups.map((g) => ({
      ...emptyConceptGroupState(emptyFields),
      fields: seedConceptFieldsFromGroup(g, emptyFields, mergeConcepts),
    })))
    setAssignments({})
    const fromResult = matchResult?.ai_filled_fields_by_group
    if (fromResult && typeof fromResult === 'object') {
      setAiFilledByGroup(
        Object.fromEntries(
          Object.entries(fromResult).map(([k, fields]) => [Number(k), new Set(fields || [])]),
        ),
      )
    } else {
      const next = {}
      ;(matchResult.groups || []).forEach((g, i) => {
        if (g?.llm_filled && Array.isArray(g.llm_filled_fields)) next[i] = new Set(g.llm_filled_fields)
      })
      setAiFilledByGroup(next)
    }
  }, [matchResult, emptyFields, mergeConcepts])

  const groupsNeedAiFill = useMemo(() => {
    const list = matchResult?.groups || []
    if (!list.length) return false
    return list.some((g) => {
      if (g?.llm_filled) return false
      return !isMetadataAutoMapped(g.metadata, usesSdgSheet ? sheetFieldKeys : null)
    })
  }, [matchResult, usesSdgSheet, sheetFieldKeys])

  const retryAutofill = useCallback(async ({ force = false } = {}) => {
    if (refilling || !hasLlmKey || !onMatchResultChange) return null
    if (!force && !groupsNeedAiFill) return null
    setRefilling(true)
    setToast(null)
    try {
      const filled = await fillGroupMetadataForMatchResult(matchResult, {
        withAuthHeaders,
        withLlmKeyHeaders,
        getMetadataStandard,
      })
      onMatchResultChange(filled.matchResult)
      const llmCount = Number(filled.matchResult.autofill_llm_filled_count) || 0
      if (filled.matchResult.llm_autofill_skipped_no_key) {
        setToast({ type: 'warn', message: filled.toast || 'LLM key not configured — autofill did not run.' })
      } else if (filled.matchResult.kyds_missing) {
        setToast({ type: 'warn', message: filled.toast || 'Know Your Dataset is missing — fill KYDS, then retry autofill.' })
      } else if (filled.toast) {
        setToast({ type: llmCount > 0 ? 'success' : 'warn', message: filled.toast })
      } else if (llmCount > 0) {
        setToast({ type: 'success', message: 'Metadata auto-fill completed with your saved LLM key.' })
      } else {
        setToast({ type: 'warn', message: 'Autofill ran but no catalogue fields were filled. You can still enter them manually.' })
      }
      return filled.matchResult
    } catch (e) {
      setToast({ type: 'warn', message: e.message || 'Could not auto-fill metadata' })
      return null
    } finally {
      setRefilling(false)
    }
  }, [refilling, hasLlmKey, onMatchResultChange, groupsNeedAiFill, matchResult])

  // Auto-run Stage 4 fill when the steward has a key and groups are still
  // empty — including after they add a key or save KYDS (not only the old
  // "skipped_no_key" path). Skip when continue-to-metadata already ran fill
  // for this group set (autofill_attempted) unless a kick bumps retry.
  useEffect(() => {
    if (!hasLlmKey || !onMatchResultChange || !groupsNeedAiFill || refilling) return
    const token = [
      hasLlmKey ? 'key' : 'nokey',
      matchResult?.llm_autofill_skipped_no_key ? 'skipped' : 'ok',
      matchResult?.kyds_missing ? 'nokyds' : 'kyds',
      `kick:${autofillKick}`,
      `groups:${(matchResult?.groups || []).length}`,
    ].join('|')
    if (autofillAttemptTokenRef.current === token) return

    // Stage 4 already completed (success, empty, or per-group errors) during
    // the grouping → metadata transition. Don't immediately re-call the LLM
    // for the same outcome. Still auto-run when key/KYDS blockers clear, or
    // when kick advances (KYDS save / Retry button).
    const alreadyAttempted = Boolean(matchResult?.autofill_attempted)
      && !matchResult?.llm_autofill_skipped_no_key
    if (alreadyAttempted && autofillKick === lastAutofillKickRef.current) {
      autofillAttemptTokenRef.current = token
      return
    }

    autofillAttemptTokenRef.current = token
    lastAutofillKickRef.current = autofillKick
    void retryAutofill({ force: true })
  }, [
    hasLlmKey,
    onMatchResultChange,
    groupsNeedAiFill,
    refilling,
    matchResult?.llm_autofill_skipped_no_key,
    matchResult?.kyds_missing,
    matchResult?.autofill_attempted,
    matchResult?.groups,
    autofillKick,
    retryAutofill,
  ])

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

  const setAppliedToAll = (groupIndex, checked) => {
    if (checked) {
      applyNmdsToAll(groupIndex)
      return
    }
    setNmdsByGroup((prev) => prev.map((g) => ({ ...g, appliedToAll: false })))
  }

  const updateMetadata = (groupIndex, metadata, { syncProduct = false } = {}) => {
    setGroups((prev) => prev.map((g, i) => {
      if (syncProduct) {
        return {
          ...g,
          metadata: {
            ...(i === groupIndex ? metadata : (g.metadata || {})),
            product: metadata?.product ?? '',
          },
        }
      }
      return i === groupIndex ? { ...g, metadata } : g
    }))
    if (usesSdgSheet) {
      const nextFields = { ...emptyFields() }
      for (const key of Object.keys(nextFields)) {
        if (metadata?.[key] != null) nextFields[key] = String(metadata[key])
      }
      patchNmdsGroup(groupIndex, { fields: nextFields })
    }
  }

  const updateMetadataField = (groupIndex, key, value) => {
    const prevMeta = groups[groupIndex]?.metadata || {}
    updateMetadata(
      groupIndex,
      { ...prevMeta, [key]: value },
      { syncProduct: key === 'product' },
    )
    // Steward edit replaces the AI value for this field.
    setAiFilledByGroup((prev) => {
      const current = prev[groupIndex]
      if (!current?.has(key)) return prev
      const nextSet = new Set(current)
      nextSet.delete(key)
      return { ...prev, [groupIndex]: nextSet }
    })
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
  // Prefer live client key state over a stale backend flag from when fill ran.
  const keyNotConfigured = !hasLlmKey
  const showFillInHeading = keyNotConfigured || matchResult.llm_autofill_skipped_no_key || matchResult.kyds_missing || noneAutoMapped
  const llmFilledGroupCount = Number(matchResult.autofill_llm_filled_count)
    || Object.keys(aiFilledByGroup).filter((k) => (aiFilledByGroup[k]?.size || 0) > 0).length
  const totalAiFieldCount = Object.values(aiFilledByGroup).reduce((sum, set) => sum + (set?.size || 0), 0)

  const autofillStatus = (() => {
    if (refilling) {
      return {
        tone: 'pending',
        title: 'AI autofill in progress',
        body: 'Auto-filling metadata with your saved LLM key…',
      }
    }
    if (keyNotConfigured || matchResult.llm_autofill_skipped_no_key) {
      return {
        tone: 'missing',
        title: 'AI autofill did not run',
        body: keyNotConfigured
          ? 'LLM key not configured — no fields were AI-filled. Set an API key in Settings, or fill every field below by hand.'
          : 'Previous auto-fill was skipped because no LLM key was set. Retry with your saved key, or fill the fields below by hand.',
      }
    }
    if (matchResult.kyds_missing) {
      return {
        tone: 'warn',
        title: 'AI autofill did not run',
        body: 'Know Your Dataset is missing — fill KYDS first for better auto-mapping, or enter fields below by hand.',
      }
    }
    if (autofillErrors.length > 0 && llmFilledGroupCount > 0) {
      return {
        tone: 'partial',
        title: 'AI autofill partially completed',
        body: `AI filled ${totalAiFieldCount} field${totalAiFieldCount !== 1 ? 's' : ''} across ${llmFilledGroupCount} group${llmFilledGroupCount !== 1 ? 's' : ''}. ${autofillErrors.length} group${autofillErrors.length !== 1 ? 's' : ''} still need manual entry (marked below).`,
      }
    }
    if (autofillErrors.length > 0) {
      const sample = autofillErrors.slice(0, 2).map((e) => {
        const group = e.group && e.group !== 'all' ? `${e.group}: ` : ''
        return `${group}${e.error}`
      })
      return {
        tone: 'warn',
        title: 'AI autofill failed',
        body: `Auto-fill failed for ${autofillErrors.length} group${autofillErrors.length !== 1 ? 's' : ''}: ${sample.join(' · ')}. You can still fill every field below manually.`,
      }
    }
    if (llmFilledGroupCount > 0) {
      return {
        tone: 'ok',
        title: 'AI autofill completed',
        body: `AI filled ${totalAiFieldCount} field${totalAiFieldCount !== 1 ? 's' : ''} across ${llmFilledGroupCount} group${llmFilledGroupCount !== 1 ? 's' : ''}. Fields marked AI below came from the model — review them before pushing.`,
      }
    }
    if (noneAutoMapped) {
      return {
        tone: 'warn',
        title: 'AI autofill did not fill any fields',
        body: usesSdgSheet
          ? 'No SDG indicator fields were auto-mapped for these groups. Fill them in manually below.'
          : 'No catalogue fields were auto-mapped for these groups. Fill them in manually below.',
      }
    }
    return {
      tone: 'ok',
      title: 'Metadata ready for review',
      body: 'Review the fields below. Empty fields still need a value before you continue.',
    }
  })()

  const autofillStatusClass = {
    missing: 'border-[#f3c98b] bg-[#fffaf1] text-[#8a5a12]',
    warn: 'border-[#f3c98b] bg-[#fffaf1] text-[#8a5a12]',
    partial: 'border-[#f3c98b] bg-[#fffaf1] text-[#8a5a12]',
    pending: 'border-line bg-mist text-ink-soft',
    ok: 'border-green/35 bg-[#eef6e6] text-[#2f5d22]',
  }[autofillStatus.tone]

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
    const missingSheet = missingRequiredSheetFields(groups[groupIndex]?.metadata, sheetColumns)
    if (missingSheet.length > 0) {
      setToast({
        type: 'warn',
        message: `Required metadata fields not filled: ${missingSheet.map((c) => c.label).join(', ')}.`,
      })
      return
    }
    const complete = isComplete(nmdsByGroup[groupIndex]?.fields || emptyFields())
    if (!complete) {
      setToast({ type: 'warn', message: `${standardName} fields not filled. Fill all ${standardName} details for this group.` })
      return
    }
    setToast({ type: 'success', message: 'Group data saved.' })
  }

  const handlePush = async () => {
    const incompleteSheet = groups.findIndex((g) => missingRequiredSheetFields(g.metadata, sheetColumns).length > 0)
    if (incompleteSheet !== -1) {
      const missing = missingRequiredSheetFields(groups[incompleteSheet].metadata, sheetColumns)
      setToast({
        type: 'warn',
        message: `Required metadata fields not filled in group ${incompleteSheet + 1}: ${missing.map((c) => c.label).join(', ')}.`,
      })
      return
    }
    const allComplete = nmdsByGroup.every((g) => isComplete(g?.fields || emptyFields()))
    if (!allComplete) {
      setToast({ type: 'warn', message: `${standardName} fields not filled. Fill all ${standardName} details.` })
      return
    }

    setStep('pushing')
    setError('')
    setToast(null)

    const finish = (ids = []) => {
      const label = groups[0]?.metadata?.title || groups[0]?.file_name || ''
      onDone(label, ids)
    }

    // Click-through mode (VITE_ENABLE_CLICK_THROUGH=true): skip the real
    // push and continue as if it succeeded. Leave this off to write
    // catalogue rows (GCS is optional via ENABLE_GCS).
    if (CLICK_THROUGH_ENABLED) {
      finish([])
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

      const batchId = matchResult.batch_id || null
      const jobId = pdfJobId || matchResult.pdf_job_id || null
      // Always slim groups_json so we stay under Starlette's 1MB form-part
      // limit. Full rows come from staging / pdf_store, or a tables_blob file
      // part (files are not subject to max_part_size).
      const finalGroups = groups.map((g, gi) => {
        const conceptFields = nmdsByGroup[gi]?.fields || emptyFields()
        const conceptList = fieldsToList(conceptFields)
        let metadata = { ...(g.metadata || {}) }
        // Catalogue title is the group name (not an editable sheet field).
        metadata.title = g.file_name || metadata.title || ''
        if (usesSdgSheet) {
          const catalogue = g.catalogue_metadata || {}
          metadata = {
            ...catalogue,
            title: g.file_name || catalogue.title || conceptFields.Indicator || conceptFields.Goal || '',
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
            table: slimTableForPush(tablesByUid[mt.table?._uid] || mt.table),
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
            table: slimTableForPush(tablesByUid[u.table?._uid] || u.table),
            confidence: 'manual',
          })
        }
      })

      const fd = new FormData()
      fd.append('groups_json', JSON.stringify(finalGroups))
      if (batchId) fd.append('batch_id', batchId)
      if (jobId) fd.append('pdf_job_id', jobId)
      if (!batchId && !jobId) {
        // In-progress sessions extracted before staging existed: ship full
        // tables as a file part so hydration still works without re-extract.
        const blob = new Blob([JSON.stringify(tablesByUid)], { type: 'application/json' })
        fd.append('tables_blob', blob, 'tables.json')
      }
      metadataFiles.forEach((f) => fd.append('metadata_files', f))

      const res = await fetch('/api/catalogue/batch-push', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })))
      if (!res.ok) {
        const err = await res.json().catch(() => ({}))
        const detail = typeof err.detail === 'string'
          ? err.detail
          : (Array.isArray(err.detail) ? err.detail.map((d) => d?.msg || d).filter(Boolean).join('; ') : '')
        throw new Error(detail || `Push failed (HTTP ${res.status})`)
      }
      const data = await res.json()
      finish((data.results || []).map((r) => r.metadata_id).filter(Boolean))
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

  return (
    <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-6">
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

      {step === 'review' && autofillStatus && (
        <div className={`rounded-lg border px-4 py-3 text-sm leading-relaxed ${autofillStatusClass}`}>
          <strong>{autofillStatus.title}</strong>
          <div className="mt-1 [overflow-wrap:anywhere]">{autofillStatus.body}</div>
          {(keyNotConfigured || matchResult.llm_autofill_skipped_no_key || llmFilledGroupCount > 0 || noneAutoMapped) && (
            <div className="mt-2 flex flex-wrap gap-2 text-[12px]">
              <span className="inline-flex items-center rounded-md border border-current/20 bg-white/50 px-2 py-0.5 font-semibold">
                {keyNotConfigured || matchResult.llm_autofill_skipped_no_key
                  ? 'Autofill: did not run'
                  : llmFilledGroupCount > 0
                    ? `Autofill: ran (${llmFilledGroupCount} group${llmFilledGroupCount !== 1 ? 's' : ''})`
                    : 'Autofill: ran, no fields filled'}
              </span>
              {totalAiFieldCount > 0 && (
                <span className="inline-flex items-center rounded-md border border-teal/30 bg-white/70 px-2 py-0.5 font-semibold text-teal-deep">
                  {totalAiFieldCount} AI-filled field{totalAiFieldCount !== 1 ? 's' : ''}
                </span>
              )}
            </div>
          )}
          {keyNotConfigured && onGoSettings && (
            <div className="mt-3 flex flex-wrap items-center gap-2.5">
              <Button type="button" onClick={onGoSettings}>Open Settings</Button>
              <span className="text-[13px] opacity-90">Add your LLM API key, then return here — auto-fill will retry.</span>
            </div>
          )}
          {!keyNotConfigured && onMatchResultChange && groupsNeedAiFill && (
            <div className="mt-3 flex flex-wrap items-center gap-2.5">
              <Button
                type="button"
                disabled={refilling}
                onClick={() => {
                  autofillAttemptTokenRef.current = ''
                  setAutofillKick((n) => {
                    const next = n + 1
                    // Keep the effect from immediately scheduling a second run;
                    // this click already invokes retryAutofill below.
                    lastAutofillKickRef.current = next
                    return next
                  })
                  void retryAutofill({ force: true })
                }}
              >
                {refilling ? 'Auto-filling…' : 'Run AI autofill'}
              </Button>
              {matchResult.kyds_missing && (
                <span className="text-[13px] opacity-90">If this fails, fill Know Your Dataset first, then click again.</span>
              )}
            </div>
          )}
        </div>
      )}

      {step !== 'done' && (
        <MetadataSheetGrid
          columns={sheetColumns}
          rows={groups.map((g, gi) => {
            const aiKeys = aiFilledByGroup[gi] || new Set()
            const aiFilled = !keyNotConfigured && !matchResult.llm_autofill_skipped_no_key && (g.llm_filled || aiKeys.size > 0)
            const notAiFilled = keyNotConfigured || matchResult.llm_autofill_skipped_no_key || groupFailedAutofill(g, gi) || (!aiFilled && !isMetadataAutoMapped(g.metadata, usesSdgSheet ? sheetFieldKeys : null))
            return {
              id: gi,
              label: g.file_name,
              values: g.metadata,
              manual: notAiFilled && !aiFilled,
              aiFilled,
              aiFilledKeys: [...aiKeys],
              autofillSkippedNoKey: keyNotConfigured || Boolean(matchResult.llm_autofill_skipped_no_key),
            }
          })}
          onChange={(gi, key, value) => updateMetadataField(gi, key, value)}
          renderGroupHeaderActions={(row, gi) => {
            if (usesSdgSheet) return null
            const nmdsState = nmdsByGroup[gi] || emptyConceptGroupState(emptyFields)
            const filledCount = fieldsToList(nmdsState.fields).length
            const complete = isComplete(nmdsState.fields || emptyFields())
            return (
              <button
                type="button"
                className={`rounded-lg border px-3 py-1.5 font-sans text-[12.5px] font-semibold transition-colors ${
                  complete
                    ? 'border-green/40 bg-[#eef6e6] text-green hover:border-green hover:bg-green hover:text-white'
                    : 'border-coral/50 bg-[rgba(217,91,104,0.1)] text-coral hover:border-coral hover:bg-coral hover:text-white'
                }`}
                onClick={() => setNmdsModalGroup(gi)}
              >
                View/Fill {standardName} details
                {filledCount > 0 ? ` (${filledCount})` : ''}
              </button>
            )
          }}
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
                onCloseModal={() => setNmdsModalGroup(null)}
                groupLabel={row.label || row.values?.title}
                onSaveGroup={() => handleSaveGroup(gi)}
                canApplyToAll={groups.length > 1}
                appliedToAll={!!nmdsState.appliedToAll}
                onApplyToAllChange={(checked) => setAppliedToAll(gi, checked)}
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
              <AlertTriangle className="h-4 w-4 text-yellow" strokeWidth={2} aria-hidden />
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
                      <Combobox
                        className="min-w-[220px]"
                        options={[
                          { value: '', label: "Skip (don't push)" },
                          ...groups.map((g, gi) => ({
                            value: String(gi),
                            label: g.metadata.title || g.file_name,
                          })),
                        ]}
                        value={assignments[idx] ?? ''}
                        onChange={(next) => setAssignments((prev) => ({ ...prev, [idx]: next }))}
                        placeholder="Select a group"
                        ariaLabel={`Assign ${u.table.id || 'table'} to group`}
                      />
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
        <Toast
          message={toast.message}
          tone={toast.type === 'success' ? 'success' : 'warn'}
          onDismiss={() => setToast(null)}
        />
      )}
    </div>
  )
}