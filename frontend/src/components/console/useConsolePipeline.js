'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { STATUS_TRANSITIONS } from '../../lib/consoleStatusTransitions'
import { withAuthHeaders } from '../../lib/auth'
import { withLlmKeyHeaders } from '../../lib/llmKey'
import { getMetadataStandard } from '../../lib/settingsConfig'
import { stageIndexForStep } from './ConsoleStages'
import {
  EMPTY_GROUP_METADATA,
  fillGroupMetadataForMatchResult,
  previewReviewStatus,
  baseTitle,
  buildGroupName,
} from '../../lib/postPreview'
import { loadPersistedConsoleState, CONSOLE_STORAGE_KEY } from '../../lib/consolePersist'
import { subscribeConsoleTableEdits } from '../../lib/consoleTableEdit'
import { stepInfoFor } from './ConsoleUploadChoice'

export function useConsolePipeline() {
  const persisted = loadPersistedConsoleState()

  const [step, setStep] = useState(persisted?.step ?? 1)
  const [uploadChoice, setUploadChoice] = useState(() => {
    if (persisted?.uploadChoice) return persisted.uploadChoice
    // Older sessions didn't store the choice — if we're past Files, assume workbook.
    if ((persisted?.step ?? 1) >= 2 && persisted?.matchResult) return 'xlsx'
    return null
  })
  const [step1MetadataFiles, setStep1MetadataFiles] = useState([])
  const [pendingDatasetFiles, setPendingDatasetFiles] = useState([])
  const [pdfUploading, setPdfUploading] = useState(false)
  const [pdfError, setPdfError] = useState('')
  // Full-page status between stages (same look as PDF processing).
  // { key, title, subtitle, steps, work?, after, msPerStep? }
  const [statusPage, setStatusPage] = useState(null)
  const router = useRouter()

  // Shared GroupingWorkspace owns dialogs; Console tracks mode + autofill.
  const [editingGroups, setEditingGroups] = useState(false)
  const [groupingToast, setGroupingToast] = useState(null)
  const [metadataFilling, setMetadataFilling] = useState(false)

  useEffect(() => {
    if (!groupingToast) return undefined
    const timer = setTimeout(() => setGroupingToast(null), 6000)
    return () => clearTimeout(timer)
  }, [groupingToast])
  // Snapshot of the last auto-computed grouping, so "Automatic grouping" can
  // restore it after the user has renamed/deleted/hand-built groups, without
  // re-hitting the backend.
  const autoMatchResultRef = useRef(persisted?.autoMatchResult ?? null)
  // True once the user has discarded the automatic grouping in favor of
  // building groups by hand -- lets "+ Add group manually" clear the slate
  // exactly once, then keep appending on every later use instead of wiping
  // groups the user just built.
  const [manualGrouping, setManualGrouping] = useState(false)

  // ── batch flow state (ported from BatchFlow.jsx) ──
  const [matchResult, setMatchResult] = useState(persisted?.matchResult ?? null)
  const [metadataFiles, setMetadataFiles] = useState([])
  const [batchPreviewId, setBatchPreviewId] = useState(persisted?.batchPreviewId ?? null)
  // Which uploaded dataset file's tables are shown in the preview tab row
  // below — null means "all datasets", so a single-file upload (the common
  // case) sees no change in behavior.
  const [selectedDataset, setSelectedDataset] = useState(persisted?.selectedDataset ?? null)
  // Preview tab filter: all | fix (needs fixing) | ai (AI review) | ok
  const [previewReviewFilter, setPreviewReviewFilter] = useState('all')

  // ── carried into Classify / Publish after the metadata save ──
  const [metaLabel, setMetaLabel] = useState(persisted?.metaLabel ?? '')
  const [metadataId, setMetadataId] = useState(persisted?.metadataId ?? null)
  const [metadataIds, setMetadataIds] = useState(persisted?.metadataIds ?? [])
  const [pendingGroups, setPendingGroups] = useState(persisted?.pendingGroups ?? null)

  // Tracks which flagged (id_title_mismatch) tables have actually had their
  // "Save details" button clicked in ReconcileIds — not merely opened — so
  // Stage 2's continue button and the tab badges reflect real corrections,
  // not just tabs the user happened to click through.
  const [savedIds, setSavedIds] = useState(() => new Set(persisted?.savedIds ?? []))

  // Tracks whether the metadata step (BatchReview) has ever been
  // reached for the current dataset, so it can stay mounted (see render
  // below) instead of being torn down whenever the user steps back to
  // Dataset Inventory to check the upload.
  const [metadataStarted, setMetadataStarted] = useState(persisted?.metadataStarted ?? false)
  useEffect(() => {
    if (step === 4) setMetadataStarted(true)
  }, [step])

  // The furthest step reached so far — separate from `step` itself, which
  // drops back down when the user steps back to Dataset Inventory. Stage nav
  // must stay enabled for a stage the user already reached, even after
  // going back; comparing against plain `step` disabled it as soon as it
  // dropped, blocking the way forward again.
  const [maxStepReached, setMaxStepReached] = useState(persisted?.maxStepReached ?? 0)
  useEffect(() => {
    setMaxStepReached((m) => Math.max(m, step))
  }, [step])

  // Peek at another stage's substeps without navigating — expand follows the
  // active stage, but a click can temporarily open a different one.
  const [expandedStage, setExpandedStage] = useState(() => stageIndexForStep(persisted?.step ?? 1))
  useEffect(() => {
    setExpandedStage(stageIndexForStep(step))
  }, [step])

  useEffect(() => {
    const toSave = {
      step,
      uploadChoice,
      matchResult,
      batchPreviewId,
      selectedDataset,
      metaLabel,
      metadataId,
      metadataIds,
      pendingGroups,
      savedIds: [...savedIds],
      metadataStarted,
      maxStepReached,
      autoMatchResult: autoMatchResultRef.current,
    }
    try {
      sessionStorage.setItem(CONSOLE_STORAGE_KEY, JSON.stringify(toSave))
    } catch {
      // best-effort — e.g. storage full or unavailable
    }
  }, [step, uploadChoice, matchResult, batchPreviewId, selectedDataset, metaLabel, metadataId, metadataIds, pendingGroups, savedIds, metadataStarted, maxStepReached])

  // Flush before the page is hidden (sidebar nav / refresh) so the latest
  // step is always what comes back — don't rely only on the effect above.
  useEffect(() => {
    const flush = () => {
      try {
        const raw = sessionStorage.getItem(CONSOLE_STORAGE_KEY)
        const prev = raw ? JSON.parse(raw) : {}
        sessionStorage.setItem(CONSOLE_STORAGE_KEY, JSON.stringify({
          ...prev,
          step,
          uploadChoice,
          matchResult,
          batchPreviewId,
          selectedDataset,
          metaLabel,
          metadataId,
          metadataIds,
          pendingGroups,
          savedIds: [...savedIds],
          metadataStarted,
          maxStepReached,
          autoMatchResult: autoMatchResultRef.current,
        }))
      } catch {
        // best-effort
      }
    }
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') flush()
    }
    window.addEventListener('pagehide', flush)
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      flush()
      window.removeEventListener('pagehide', flush)
      document.removeEventListener('visibilitychange', onVisibility)
    }
  }, [step, uploadChoice, matchResult, batchPreviewId, selectedDataset, metaLabel, metadataId, metadataIds, pendingGroups, savedIds, metadataStarted, maxStepReached])

  const revertToAutomaticBatchGrouping = () => {
    if (!autoMatchResultRef.current) return
    setMatchResult(autoMatchResultRef.current)
    setManualGrouping(false)
    setEditingGroups(false)
  }

  const handleRequestAutomatic = () => {
    revertToAutomaticBatchGrouping()
  }

  // Every table must end up in a named group before moving on. Stage 4
  // metadata autofill runs here (shared with PDF via fillGroupMetadataForMatchResult).
  const requestContinueToMetadata = async () => {
    if (matchResult?.unmatched_tables.length > 0) {
      setGroupingToast('All tables must be assigned to a group with a group name before continuing.')
      return
    }
    if (!matchResult?.groups?.length) {
      setGroupingToast('Create at least one group before continuing to metadata.')
      return
    }
    if (metadataFilling || statusPage) return

    setMetadataFilling(true)
    setGroupingToast(null)

    const fillWork = async () => {
      try {
        const filled = await fillGroupMetadataForMatchResult(matchResult, {
          withAuthHeaders,
          withLlmKeyHeaders,
          getMetadataStandard,
        })
        setMatchResult(filled.matchResult)
        if (filled.toast) setGroupingToast(filled.toast)
      } catch (e) {
        const detail = e.message || 'Could not auto-fill metadata'
        setMatchResult((prev) => (prev ? {
          ...prev,
          autofill_errors: [{ group: 'all', error: detail }],
        } : prev))
        setGroupingToast(`${detail} — continuing so you can fill metadata manually.`)
      } finally {
        setMetadataFilling(false)
      }
    }

    setStatusPage({
      ...STATUS_TRANSITIONS.groupingToMetadata,
      key: 'groupingToMetadata',
      work: fillWork,
      after: () => {
        setStatusPage(null)
        setStep(4)
      },
    })
  }

  // Applies { tableId: { table_id, title } } corrections onto the live
  // batch match result — used both for a single save (so the preview
  // updates immediately) and the final "continue" step.
  const patchTables = (corrections) => {
    const patchTable = (t) => (corrections[t._uid] ? { ...t, ...corrections[t._uid] } : t)
    setMatchResult((prev) => {
      if (!prev) return prev
      const findTable = (uid) => {
        for (const g of prev.groups) {
          const mt = g.matched_tables.find((m) => m.table._uid === uid)
          if (mt) return mt.table
        }
        return (prev.unmatched_tables.find((u) => u.table._uid === uid) || {}).table
      }
      const patched = {
        ...prev,
        groups: prev.groups.map((g) => ({
          ...g,
          matched_tables: g.matched_tables.map((mt) => ({ ...mt, table: patchTable(mt.table) })),
        })),
        unmatched_tables: prev.unmatched_tables.map((u) => ({ ...u, table: patchTable(u.table) })),
      }
      if (metadataFiles.length !== 0 || manualGrouping) return patched

      // Grouping without a metadata workbook derives both group membership
      // and each group's display name from table titles alone. Re-derive
      // the display name of every existing group from its own (possibly
      // just-corrected) members -- safe, since it never changes who's in
      // which group -- and re-home only the tables whose *base* title
      // actually changed, rather than rebuilding every group from scratch:
      // a wholesale rebuild would re-key every table by its current title
      // on every single save, and any two tables that happen to reduce to
      // the same base title (or share a still-blank title) would collapse
      // into one group even though neither of their titles changed.
      const changedUids = Object.keys(corrections).filter((uid) => {
        const before = findTable(uid)
        return before && corrections[uid].title !== undefined
          && baseTitle(corrections[uid].title) !== baseTitle(before.title)
      })

      let groups = patched.groups.map((g) => ({
        ...g,
        file_name: buildGroupName(baseTitle(g.matched_tables[0]?.table.title || g.file_name)),
      }))
      let unmatched_tables = patched.unmatched_tables

      if (changedUids.length > 0) {
        const changed = new Set(changedUids)
        const pulled = []
        groups = groups
          .map((g) => {
            const [keep, take] = [[], []]
            g.matched_tables.forEach((mt) => (changed.has(mt.table._uid) ? take : keep).push(mt))
            pulled.push(...take)
            return { ...g, matched_tables: keep }
          })
          .filter((g) => g.matched_tables.length > 0)
        const unmatchedKeep = []
        unmatched_tables.forEach((u) => (changed.has(u.table._uid) ? pulled.push(u) : unmatchedKeep.push(u)))
        unmatched_tables = unmatchedKeep

        pulled.forEach((mt) => {
          const key = baseTitle(mt.table.title)
          const dest = groups.find((g) => baseTitle(g.matched_tables[0].table.title) === key)
          if (dest) {
            dest.matched_tables.push(mt)
          } else {
            groups.push({
              workbook_index: groups.length,
              file_name: buildGroupName(key),
              metadata: { ...EMPTY_GROUP_METADATA },
              concepts: [],
              classifications: {},
              matched_tables: [mt],
            })
          }
        })
      }

      return { ...patched, groups, unmatched_tables }
    })
  }

  // Apply structure/title edits saved from the full-page View/Edit table tab.
  const patchTablesRef = useRef(patchTables)
  patchTablesRef.current = patchTables
  useEffect(() => subscribeConsoleTableEdits(({ uid, edits }) => {
    if (!uid || !edits) return
    patchTablesRef.current({ [uid]: edits })
  }), [])

  const applyReconcile = (corrections) => {
    patchTables(corrections)
    setManualGrouping(false)
    setEditingGroups(false)
    setStatusPage({
      ...STATUS_TRANSITIONS.previewToGrouping,
      key: 'previewToGrouping',
      after: () => {
        setStatusPage(null)
        setStep(3)
      },
    })
  }

  const publishFromClassify = () => {
    setStatusPage({
      ...STATUS_TRANSITIONS.classifyToPublish,
      key: 'classifyToPublish',
      after: () => {
        setStatusPage(null)
        setStep(6)
      },
    })
  }

  const finishMatched = (data) => {
    setMetadataFiles(data.metadataFiles)
    setMatchResult(data)
    autoMatchResultRef.current = data
    setManualGrouping(false)
    setEditingGroups(false)
    const all = data.groups.flatMap((g) => g.matched_tables.map((mt) => mt.table))
      .concat(data.unmatched_tables.map((u) => u.table))
    if (all.length > 0) setBatchPreviewId(all[0]._uid)
    setSelectedDataset(null)
    setSavedIds(new Set())
    setMetadataStarted(false)
    setMaxStepReached(2)
    setUploadChoice((c) => c || 'xlsx')
    setStep(2)
  }

  // Show the Files→Preview status page only AFTER extract/match succeeds,
  // so the upload fetch is never racing a hidden/remounted BatchUpload.
  const handleMatched = (data) => {
    setStatusPage({
      ...STATUS_TRANSITIONS.filesToPreview,
      key: 'filesToPreview',
      msPerStep: 550,
      after: () => {
        setStatusPage(null)
        finishMatched(data)
      },
    })
  }

  const back = () => setStep((s) => Math.max(1, s - 1))

  const stageIdx = stageIndexForStep(step)

  // Once a source type is chosen, tailor the step-1 header copy.
  const info = (() => {
    const base = stepInfoFor(step)
    if (step !== 1) return base
    if (uploadChoice === 'xlsx') {
      return {
        title: 'Select dataset and metadata files',
        purpose: 'Upload the workbooks and their metadata tag files for this release.',
        next: base.next,
      }
    }
    if (uploadChoice === 'sql') {
      return {
        title: 'Connect a PostgreSQL database',
        purpose: 'Paste a connection URL. Catalogue DBs expand each dataset; otherwise every table is extracted (custom SQL optional).',
        next: base.next,
      }
    }
    return base
  })()

  const handleDatasetFile = (type, file) => {
    if (type === 'xlsx' && file) {
      setPendingDatasetFiles((prev) => {
        const exists = prev.some((f) => f.name === file.name && f.size === file.size)
        return exists ? prev : [...prev, file]
      })
      setUploadChoice('xlsx')
    }
  }

  const addStep1MetadataFiles = (files) => {
    setStep1MetadataFiles((prev) => [...prev, ...files])
  }

  const removeStep1MetadataFile = (index) => {
    setStep1MetadataFiles((prev) => prev.filter((_, i) => i !== index))
  }

  const resetUploadChoice = () => {
    setUploadChoice(null)
    setPendingDatasetFiles([])
  }

  const handlePdfFile = async (file) => {
    setPdfError('')
    setPdfUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/pdf/upload', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })))
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
        throw new Error(err.detail || 'Upload failed')
      }
      const { job_id } = await res.json()
      router.push(`/console/processing/${job_id}`)
    } catch (e) {
      setPdfError(e.message)
      setPdfUploading(false)
    }
  }

  // A substep can only be jumped to once the user has actually reached it
  // before.
  const goToStep = (targetStep) => {
    if (targetStep <= maxStepReached) setStep(targetStep)
  }

  // ── step 2: preview ──
  const batchAllTables = matchResult
    ? matchResult.groups.flatMap((g) => g.matched_tables.map((mt) => mt.table))
      .concat(matchResult.unmatched_tables.map((u) => u.table))
    : []
  const previewTables = batchAllTables
  // Dataset (uploaded file) names in upload order, deduped — the chips
  // shown above the table tab row so a multi-file upload can be narrowed
  // down to one dataset at a time.
  const previewDatasets = [...new Set(previewTables.map((t) => t.filename))]
  // With more than 2 datasets the picker becomes a dropdown, which always
  // has one dataset selected (no "all" option) — default it to the first
  // dataset rather than leaving the filter off.
  const effectiveDataset = selectedDataset || (previewDatasets.length > 2 ? previewDatasets[0] : null)
  const visiblePreviewTables = effectiveDataset
    ? previewTables.filter((t) => t.filename === effectiveDataset)
    : previewTables
  // `_uid` (assigned per-file/per-position by the backend) — not the
  // catalog `id`, which is derived from a table's own content and so can
  // collide between two physically different tables (e.g. the same table
  // title showing up in two different uploaded workbooks). Selecting,
  // saving and patching all have to key off something that's unique per
  // physical table regardless of that collision.
  const previewSelected = previewTables.find((t) => t._uid === batchPreviewId) || previewTables[0]
  const selectPreviewTable = (uid) => {
    setBatchPreviewId(uid)
    // Keep the dataset filter in sync so a table jumped to from elsewhere
    // (e.g. ReconcileIds' "next flagged table") stays visible in the tab row.
    const t = previewTables.find((pt) => pt._uid === uid)
    if (t && effectiveDataset && t.filename !== effectiveDataset) setSelectedDataset(t.filename)
  }
  const selectPreviewDataset = (name) => {
    setSelectedDataset(name)
    // Jump the active table tab to one within the newly chosen dataset so
    // the preview below always matches what the tab row shows.
    const firstInDataset = previewTables.find((t) => t.filename === name)
    if (firstInDataset && previewSelected?.filename !== name) setBatchPreviewId(firstInDataset._uid)
  }
  const markTableSaved = (uid, correction) => {
    setSavedIds((prev) => (prev.has(uid) ? prev : new Set(prev).add(uid)))
    if (correction) patchTables({ [uid]: correction })
  }
  // Scoped to the currently selected dataset (falls back to all tables when
  // no filter is applied) so the banner only warns about the dataset in view.
  const mismatchedPreviewTables = visiblePreviewTables.filter((t) => t.id_title_mismatch)
  const unsavedMismatched = mismatchedPreviewTables.filter((t) => !savedIds.has(t._uid))
  const aiFilledPreviewTables = visiblePreviewTables.filter(
    (t) => (t.title_repaired_by_llm || t.table_id_repaired_by_llm) && !t.id_title_mismatch,
  )
  const unsavedAiFilled = aiFilledPreviewTables.filter((t) => !savedIds.has(t._uid))
  const okPreviewCount = visiblePreviewTables.filter((t) => previewReviewStatus(t, savedIds) === 'ok').length
  const filteredPreviewTables = visiblePreviewTables.filter((t) => {
    if (previewReviewFilter === 'all') return true
    return previewReviewStatus(t, savedIds) === previewReviewFilter
  })
  const filteredPreviewUidKey = filteredPreviewTables.map((t) => t._uid).join('|')

  // Drop empty status filters so the chip row never shows "Needs fixing (0)" /
  // "AI review (0)" and the user isn't stuck on an empty view.
  useEffect(() => {
    if (previewReviewFilter === 'fix' && unsavedMismatched.length === 0) {
      setPreviewReviewFilter('all')
    } else if (previewReviewFilter === 'ai' && unsavedAiFilled.length === 0) {
      setPreviewReviewFilter('all')
    }
  }, [previewReviewFilter, unsavedMismatched.length, unsavedAiFilled.length])

  useEffect(() => {
    if (step !== 2 || !filteredPreviewUidKey) return
    const uids = filteredPreviewUidKey.split('|')
    if (!uids.includes(batchPreviewId)) setBatchPreviewId(uids[0])
  }, [step, previewReviewFilter, filteredPreviewUidKey, batchPreviewId])

  // Grouping step: one segmented "mode" derived from existing state, so the
  // three old separate entry points (Edit / switch-to-manual / add-group)
  // collapse into one toggle + a single contextual secondary action.

  return {
    STATUS_TRANSITIONS,
    addStep1MetadataFiles,
    applyReconcile,
    autoMatchResultRef,
    back,
    batchAllTables,
    editingGroups,
    effectiveDataset,
    expandedStage,
    filteredPreviewTables,
    goToStep,
    groupingToast,
    handleDatasetFile,
    handleMatched,
    handlePdfFile,
    handleRequestAutomatic,
    info,
    manualGrouping,
    markTableSaved,
    matchResult,
    maxStepReached,
    metaLabel,
    metadataFiles,
    metadataFilling,
    metadataId,
    metadataIds,
    metadataStarted,
    mismatchedPreviewTables,
    okPreviewCount,
    pdfError,
    pdfUploading,
    pendingDatasetFiles,
    previewDatasets,
    previewReviewFilter,
    previewReviewStatus,
    previewSelected,
    previewTables,
    publishFromClassify,
    removeStep1MetadataFile,
    requestContinueToMetadata,
    resetUploadChoice,
    savedIds,
    selectPreviewDataset,
    selectPreviewTable,
    setEditingGroups,
    setExpandedStage,
    setGroupingToast,
    setManualGrouping,
    setMatchResult,
    setMetaLabel,
    setMetadataId,
    setMetadataIds,
    setPdfError,
    setPendingGroups,
    setPreviewReviewFilter,
    setStatusPage,
    setStep,
    setStep1MetadataFiles,
    setUploadChoice,
    stageIdx,
    statusPage,
    step,
    step1MetadataFiles,
    unsavedAiFilled,
    unsavedMismatched,
    uploadChoice,
    visiblePreviewTables,
  }
}
