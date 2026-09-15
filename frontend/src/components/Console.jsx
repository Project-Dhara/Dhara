'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertTriangle, ArrowLeft, Check, Sparkles } from 'lucide-react'
import KydsSummaryCard from './KydsSummaryCard'
import TableViewer from './TableViewer'
import BatchUpload from './BatchUpload'
import SqlUpload from './SqlUpload'
import ReconcileIds from './ReconcileIds'
import GroupingWorkspace from './GroupingWorkspace'
import PostPreviewLaterSteps from './PostPreviewLaterSteps'
import Button from './ui/Button'
import Badge from './ui/Badge'
import ErrorBanner from './ui/ErrorBanner'
import ConsoleStatusPlaceholder from './ConsoleStatusPlaceholder'
import { STATUS_TRANSITIONS } from '../lib/consoleStatusTransitions'
import { withAuthHeaders } from '../lib/auth'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { getMetadataStandard } from '../lib/settingsConfig'
import { StageSidebar, stageIndexForStep } from './ConsoleStages'
import {
  EMPTY_GROUP_METADATA,
  fillGroupMetadataForMatchResult,
} from '../lib/postPreview'

/** Preview review status for Source Table ID / Title. */
function previewReviewStatus(t, savedIds) {
  const saved = savedIds?.has?.(t._uid)
  if (t.id_title_mismatch && !saved) return 'fix'
  if ((t.title_repaired_by_llm || t.table_id_repaired_by_llm) && !saved) return 'ai'
  return 'ok'
}

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
  const sheet = String(table.sheet || '').trim()
  const genericSheet = !sheet || /^(catalogue|query|table|view|data|base table)$/i.test(sheet)
  if (!genericSheet) return sheet
  const title = String(table.title || '').trim()
  if (title) return title.length > 56 ? `${title.slice(0, 56)}…` : title
  return table.table_id || table.id || 'Table'
}

function tablePickerLabel(table) {
  const code = tableCode(table)
  const rows = table.row_count != null ? `${table.row_count} rows` : ''
  return rows ? `${code} — ${rows}` : code
}

// Ports of backend title-base helpers — needed client-side so a title
// correction on preview can re-home tables into shared grouping buckets.
function baseTitle(title) {
  const base = (title || '').replace(/\s*\([^)]*\)\s*$/, '').trim().replace(/\s+/g, ' ').toUpperCase()
  return base || (title || '').trim().toUpperCase()
}

const GROUP_NAME_NOISE = new Set(['sl', 'no'])

function buildGroupName(base) {
  const title = (base || '').replace(/\s+/g, ' ').trim()
  if (!title) return 'Untitled group'
  const words = title.split(' ')
  while (words.length && GROUP_NAME_NOISE.has(words[0].replace(/[.,]+$/, '').toLowerCase())) {
    words.shift()
  }
  const cleaned = words.join(' ').trim().replace(/^[\s.,-]+|[\s.,-]+$/g, '') || title
  return cleaned.replace(/\S+/g, (w) => w[0].toUpperCase() + w.slice(1).toLowerCase())
}

// Three-line header per step: name (orientation), a purpose sentence that's
// now filled in for every step (previously blank for steps 2/3/4), and a
// forward-looking cue -- "you are here, this is why, this is what happens
// next," per the redesign brief. Terminal step (6) has no "next" line.
function stepInfoFor(step) {
  return [
    null,
    {
      title: 'Select dataset and metadata files',
      purpose: 'Upload dataset files (PDF, XLSX, or SQL) and optional metadata tag workbooks for this release.',
      next: 'Next: preview the extracted tables.',
    },
    {
      title: 'Preview',
      purpose: 'Confirm the extracted tables look right, and resolve any Source Table ID / Title mismatches.',
      next: 'Next: group tables into datasets.',
    },
    {
      title: 'Grouping',
      purpose: 'Confirm which tables belong together — every table needs a group before you can add metadata.',
      next: 'Next: add metadata for each group.',
    },
    {
      title: 'Metadata',
      purpose: 'Add catalogue metadata — title, category, coverage — for each group.',
      next: 'Next: map columns to standard concepts and code lists.',
    },
    {
      title: 'Classification and harmonisation',
      purpose: 'Map columns to standard concepts and code lists.',
      next: 'Next: publish this release.',
    },
    {
      title: 'Publish this release',
      purpose: 'Register the API and MCP endpoints for this release.',
      next: null,
    },
  ][step]
}

const BACK_LABELS = [
  '', 'Choose another method', 'Change files', 'Back to preview', 'Back to grouping', 'Back to metadata',
]

// Serializable slice of the flow state, persisted so it survives a page
// refresh or a detour to another screen — File objects can't survive either
// (browsers won't let a File be reconstructed from storage), so
// metadataFiles is deliberately excluded; the user just re-adds files if
// they refresh mid-upload-step.
const STORAGE_KEY = 'dhara_console_state_v1'

function loadPersisted() {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function MetadataFileList({ files, onRemove }) {
  if (files.length === 0) return null
  return (
    <ul className="mt-3 flex w-full list-none flex-col gap-1.5 text-left">
      {files.map((f, i) => (
        <li key={`${f.name}-${i}`} className="flex items-center justify-between gap-2 rounded-md bg-cream/95 px-2.5 py-1.5 text-[12.5px] text-ink">
          <span className="min-w-0 truncate">{f.name}</span>
          <button
            type="button"
            className="flex h-6 w-6 flex-none items-center justify-center rounded text-ink-soft hover:bg-white hover:text-[#b91c1c]"
            onClick={(e) => {
              e.stopPropagation()
              onRemove(i)
            }}
            title="Remove"
            aria-label="Remove file"
          >
            <X className="h-3.5 w-3.5" strokeWidth={2} />
          </button>
        </li>
      ))}
    </ul>
  )
}

// Step 1: two equal cards — dataset (PDF / XLSX / SQL tabs) and metadata tag files.
function UploadChoice({
  choice,
  onChoose,
  onDatasetFile,
  onPdfFile,
  pdfUploading,
  pdfError,
  onClearPdfError,
  metadataFiles,
  onMetadataFilesAdd,
  onMetadataFileRemove,
  sqlPanel,
}) {
  const datasetInputRef = useRef(null)
  const metadataInputRef = useRef(null)
  const [datasetDragging, setDatasetDragging] = useState(false)
  const [metadataDragging, setMetadataDragging] = useState(false)

  const routeDatasetFile = (file) => {
    if (!file || pdfUploading) return
    if (/\.pdf$/i.test(file.name)) {
      onPdfFile(file)
      return
    }
    if (/\.(xlsx|xls)$/i.test(file.name)) {
      onDatasetFile('xlsx', file)
      return
    }
  }

  const takeMetadataFiles = (fileList) => {
    const files = Array.from(fileList || []).filter((f) => /\.(xlsx|xls)$/i.test(f.name))
    if (files.length) onMetadataFilesAdd(files)
  }

  const fileTab = choice !== 'sql'
  const dropZoneClass = (dragging) =>
    `flex min-h-[168px] flex-1 cursor-pointer flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-5 py-6 text-center transition-colors ${
      dragging
        ? 'border-teal/40 bg-sage'
        : 'border-line bg-white hover:border-line hover:bg-mist/80'
    }`

  const datasetCardClass = 'dhara-surface flex min-h-[240px] w-full flex-col overflow-hidden rounded-card border border-teal/20 bg-white'
  const metadataCardClass = 'dhara-surface flex min-h-[240px] w-full flex-col overflow-hidden rounded-card border border-line bg-white'
  const selectorBarClass = 'border-b border-line bg-mist'
  const tabBase = 'dhara-tab relative px-3 text-[13px] font-semibold disabled:cursor-not-allowed disabled:opacity-60'
  const tabActive = 'dhara-tab-on'
  const tabIdle = 'dhara-tab-off'

  return (
    <div className="flex flex-col gap-4">
      <input
        ref={datasetInputRef}
        type="file"
        accept=".pdf,.xlsx,.xls"
        className="hidden"
        disabled={pdfUploading}
        onChange={(e) => {
          routeDatasetFile(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      <input
        ref={metadataInputRef}
        type="file"
        accept=".xlsx,.xls"
        multiple
        className="hidden"
        disabled={pdfUploading}
        onChange={(e) => {
          takeMetadataFiles(e.target.files)
          e.target.value = ''
        }}
      />
      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2 sm:items-stretch">
        <div className={datasetCardClass}>
          <div
            className={`grid h-[45px] grid-cols-2 ${selectorBarClass}`}
            role="tablist"
            aria-label="Dataset source"
          >
            <button
              type="button"
              role="tab"
              aria-selected={fileTab}
              disabled={pdfUploading}
              className={`${tabBase} ${fileTab ? tabActive : tabIdle}`}
              onClick={() => choice === 'sql' && onChoose(null)}
            >
              File upload
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={!fileTab}
              disabled={pdfUploading}
              className={`${tabBase} ${!fileTab ? tabActive : tabIdle}`}
              onClick={() => fileTab && onChoose('sql')}
            >
              Connect SQL database
            </button>
          </div>
          {fileTab ? (
            <div key="file-tab" className="dhara-tab-panel flex flex-1 flex-col p-3">
              <div
                role="button"
                tabIndex={0}
                onClick={() => !pdfUploading && datasetInputRef.current?.click()}
                onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); !pdfUploading && datasetInputRef.current?.click() } }}
                onDragOver={(e) => { e.preventDefault(); setDatasetDragging(true) }}
                onDragLeave={() => setDatasetDragging(false)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDatasetDragging(false)
                  routeDatasetFile(e.dataTransfer.files?.[0])
                }}
                className={`${dropZoneClass(datasetDragging)} ${pdfUploading ? 'pointer-events-none opacity-60' : ''}`}
              >
                <div className="text-[15px] font-semibold tracking-tight text-ink">
                  {pdfUploading ? 'Uploading PDF…' : 'Upload dataset files'}
                </div>
                <div className="max-w-[280px] text-[13px] leading-snug text-ink-soft">
                  {pdfUploading
                    ? 'Starting extraction…'
                    : 'Click or drop PDF reports or XLSX workbooks — the matching pipeline runs automatically.'}
                </div>
              </div>
            </div>
          ) : (
            <div key="sql-tab" className="dhara-tab-panel flex flex-1 flex-col p-3">
              <div className="flex min-h-0 flex-1 flex-col rounded-lg bg-white p-4">
                {sqlPanel}
              </div>
            </div>
          )}
        </div>

        <div className={metadataCardClass}>
          <div className={`flex h-[45px] items-center justify-center px-3 ${selectorBarClass}`}>
            <span className="text-[13px] font-semibold text-ink-soft">Metadata (optional)</span>
          </div>
          <div className="flex flex-1 flex-col p-3">
            <div
              role="button"
              tabIndex={0}
              onClick={() => !pdfUploading && metadataInputRef.current?.click()}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); !pdfUploading && metadataInputRef.current?.click() } }}
              onDragOver={(e) => { e.preventDefault(); setMetadataDragging(true) }}
              onDragLeave={() => setMetadataDragging(false)}
              onDrop={(e) => {
                e.preventDefault()
                setMetadataDragging(false)
                takeMetadataFiles(e.dataTransfer.files)
              }}
              className={`${dropZoneClass(metadataDragging)} ${pdfUploading ? 'pointer-events-none opacity-60' : ''}`}
            >
              <div className="text-[15px] font-semibold tracking-tight text-ink">Upload metadata tag files</div>
              <div className="max-w-[280px] text-[13px] leading-snug text-ink-soft">
                Optional XLSX metadata workbooks — matched against your dataset tables during grouping.
              </div>
              {metadataFiles.length > 0 && (
                <div className="w-full max-w-[280px]">
                  <MetadataFileList files={metadataFiles} onRemove={onMetadataFileRemove} />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      {pdfError && (
        <div className="flex flex-col gap-2">
          <ErrorBanner>{pdfError}</ErrorBanner>
          <Button variant="secondary" size="sm" className="self-start" onClick={onClearPdfError}>Try again</Button>
        </div>
      )}
    </div>
  )
}

export default function Console({ hasKey, onGoSettings, onGoDashboard, onGoCatalogue, onUploadAnother }) {
  const persisted = loadPersisted()

  const [step, setStep] = useState(persisted?.step ?? 1)
  const [uploadChoice, setUploadChoice] = useState(null)
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
      step, matchResult, batchPreviewId, selectedDataset,
      metaLabel, metadataId, metadataIds, pendingGroups, savedIds: [...savedIds], metadataStarted, maxStepReached,
      autoMatchResult: autoMatchResultRef.current,
    }
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(toSave))
    } catch {
      // best-effort — e.g. storage full or unavailable
    }
  }, [step, matchResult, batchPreviewId, selectedDataset, metaLabel, metadataId, metadataIds, pendingGroups, savedIds, metadataStarted, maxStepReached])

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

  useEffect(() => {
    if (step !== 2 || !filteredPreviewUidKey) return
    const uids = filteredPreviewUidKey.split('|')
    if (!uids.includes(batchPreviewId)) setBatchPreviewId(uids[0])
  }, [step, previewReviewFilter, filteredPreviewUidKey, batchPreviewId])

  // Grouping step: one segmented "mode" derived from existing state, so the
  // three old separate entry points (Edit / switch-to-manual / add-group)
  // collapse into one toggle + a single contextual secondary action.

  return (
    <div className="flex flex-col gap-5">
      <StageSidebar
        stageIdx={stageIdx}
        step={step}
        maxStepReached={maxStepReached}
        expandedStage={expandedStage}
        setExpandedStage={setExpandedStage}
        goToStep={goToStep}
      />

      <div key={step} className="dhara-page-enter flex min-w-0 flex-1 flex-col gap-[18px]">
        {/* Page header — title / purpose stay above the content panel */}
        {!statusPage && (
        <div className="flex flex-col">
          {step > 1 && step < 6 && (
            <div className="mb-3.5 inline-flex cursor-pointer items-center gap-1.5 text-[14px] font-medium text-teal transition-colors duration-dhara ease-dhara hover:text-teal-dark" onClick={back}>
              <ArrowLeft className="h-4 w-4" strokeWidth={1.75} aria-hidden />
              {BACK_LABELS[step]}
            </div>
          )}
          <div className="flex items-center justify-between gap-6">
            <div>
              <div className="dhara-page-title">{info.title}</div>
            </div>
            {stageIdx === 0 && (step === 1 || step === 2) && <KydsSummaryCard variant="corner" />}
          </div>
        </div>
        )}

        {/* Shared content panel — choice cards, then tables / grouping / later steps */}
        <div className="flex flex-col gap-5 rounded-2xl border border-line/90 bg-white p-5 sm:p-6">
        {statusPage && (
          <ConsoleStatusPlaceholder
            key={statusPage.key}
            title={statusPage.title}
            subtitle={statusPage.subtitle}
            steps={statusPage.steps}
            work={statusPage.work || null}
            msPerStep={statusPage.msPerStep || 850}
            onComplete={statusPage.after}
          />
        )}
        <div style={{ display: statusPage ? 'none' : undefined }}>
        {step === 1 && (
          <div className="flex flex-col gap-6">
            <UploadChoice
              choice={uploadChoice}
              onChoose={setUploadChoice}
              onDatasetFile={handleDatasetFile}
              onPdfFile={handlePdfFile}
              pdfUploading={pdfUploading}
              pdfError={pdfError}
              onClearPdfError={() => setPdfError('')}
              metadataFiles={step1MetadataFiles}
              onMetadataFilesAdd={addStep1MetadataFiles}
              onMetadataFileRemove={removeStep1MetadataFile}
              sqlPanel={(
                <SqlUpload
                  onMatched={handleMatched}
                  metadataFiles={step1MetadataFiles}
                  onMetadataFilesChange={setStep1MetadataFiles}
                  hideMetadataSection
                />
              )}
            />
            {uploadChoice === 'xlsx' && (
              <>
                <button
                  type="button"
                  className="inline-flex items-center gap-1.5 self-start text-[13px] font-semibold text-teal hover:text-teal-dark"
                  onClick={resetUploadChoice}
                >
                  <ArrowLeft className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                  Back to file upload
                </button>
                <BatchUpload
                  onMatched={handleMatched}
                  initialDatasetFiles={pendingDatasetFiles}
                  metadataFiles={step1MetadataFiles}
                  onMetadataFilesChange={setStep1MetadataFiles}
                  hideMetadataSection
                />
              </>
            )}
          </div>
        )}

        {step === 2 && previewTables.length > 0 && (
          <div className="flex flex-col gap-5">
            {previewDatasets.length > 1 && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Dataset</span>
                {previewDatasets.length > 2 ? (
                  <select
                    className="rounded-md border border-line-strong bg-white px-3 py-1.5 text-[13px] text-ink outline-none focus:border-teal"
                    value={effectiveDataset}
                    onChange={(e) => selectPreviewDataset(e.target.value)}
                  >
                    {previewDatasets.map((name) => (
                      <option key={name} value={name}>{name}</option>
                    ))}
                  </select>
                ) : (
                  previewDatasets.map((name) => (
                    <div
                      key={name}
                      className={`dhara-tab cursor-pointer rounded-full border px-3 py-1.5 text-sm ${
                        name === effectiveDataset
                          ? 'border-transparent bg-teal-deep text-cream'
                          : 'border-line bg-white text-ink hover:bg-sage hover:text-teal-deep'
                      }`}
                      onClick={() => selectPreviewDataset(name)}
                      title={name}
                    >
                      {name}
                    </div>
                  ))
                )}
              </div>
            )}
            {(unsavedMismatched.length > 0 || unsavedAiFilled.length > 0) && (
              <div className="flex flex-col gap-2 sm:flex-row sm:flex-wrap">
                {unsavedMismatched.length > 0 && (
                  <div className="flex-1 rounded-lg border border-coral/40 bg-error-bg px-4 py-3 text-sm font-medium text-ink">
                    <span className="inline-flex items-start gap-1.5">
                      <AlertTriangle className="mt-0.5 h-4 w-4 flex-none text-coral" strokeWidth={2} aria-hidden />
                      <span>
                        <span className="font-semibold text-coral">Needs fixing:</span>{' '}
                        {unsavedMismatched.length} of {mismatchedPreviewTables.length} table{mismatchedPreviewTables.length !== 1 ? 's' : ''} still need correcting & saving.
                      </span>
                    </span>
                  </div>
                )}
                {unsavedAiFilled.length > 0 && (
                  <div className="flex-1 rounded-lg border border-[#5B8DEF]/45 bg-[#EEF4FF] px-4 py-3 text-sm font-medium text-ink">
                    <span className="inline-flex items-start gap-1.5">
                      <Sparkles className="mt-0.5 h-4 w-4 flex-none text-[#2F6FED]" strokeWidth={2} aria-hidden />
                      <span>
                        <span className="font-semibold text-[#2F6FED]">AI review:</span>{' '}
                        {unsavedAiFilled.length} table{unsavedAiFilled.length !== 1 ? 's' : ''} had Source Table ID / Title filled by AI — confirm they look right.
                      </span>
                    </span>
                  </div>
                )}
              </div>
            )}
            {mismatchedPreviewTables.length > 0 && unsavedMismatched.length === 0 && (
              <div className="rounded-lg border border-green bg-sage px-4 py-3 text-sm font-medium text-teal">
                <span className="inline-flex items-start gap-1.5">
                  <Check className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2.5} aria-hidden />
                  All {mismatchedPreviewTables.length} flagged table{mismatchedPreviewTables.length !== 1 ? 's' : ''} saved.
                </span>
              </div>
            )}

            {(unsavedMismatched.length > 0 || unsavedAiFilled.length > 0 || previewReviewFilter !== 'all') && (
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] font-semibold uppercase tracking-wide text-ink-soft">Show</span>
                {[
                  { id: 'all', label: 'All', count: visiblePreviewTables.length, activeClass: 'bg-teal-deep text-cream' },
                  { id: 'fix', label: 'Needs fixing', count: unsavedMismatched.length, activeClass: 'bg-coral text-white', idleClass: 'border-coral/35 text-coral hover:bg-error-bg' },
                  { id: 'ai', label: 'AI review', count: unsavedAiFilled.length, activeClass: 'bg-[#2F6FED] text-white', idleClass: 'border-[#5B8DEF]/40 text-[#2F6FED] hover:bg-[#EEF4FF]' },
                  { id: 'ok', label: 'Reviewed / OK', count: okPreviewCount, activeClass: 'bg-green text-white', idleClass: 'border-green/40 text-green hover:bg-sage' },
                ].map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] font-semibold transition-colors ${
                      previewReviewFilter === f.id
                        ? `border-transparent ${f.activeClass}`
                        : `border-line bg-white text-ink-soft ${f.idleClass || 'hover:bg-sage hover:text-teal-deep'}`
                    }`}
                    onClick={() => setPreviewReviewFilter(f.id)}
                  >
                    {f.label}
                    <span className={`rounded-full px-1.5 py-0.5 text-[10.5px] font-semibold ${
                      previewReviewFilter === f.id ? 'bg-white/20' : 'bg-cream text-ink-soft'
                    }`}>
                      {f.count}
                    </span>
                  </button>
                ))}
              </div>
            )}

            {filteredPreviewTables.length === 0 ? (
              <div className="rounded-lg border border-dashed border-line px-4 py-6 text-center text-sm text-ink-soft">
                No tables in this filter. Choose another status above.
              </div>
            ) : filteredPreviewTables.length > 10 ? (
              <label className="flex min-w-0 max-w-3xl flex-col gap-1.5">
                <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
                  Table
                  <span className="rounded bg-cream px-1.5 py-0.5 text-[10.5px] font-semibold normal-case tracking-normal text-ink-soft">
                    {filteredPreviewTables.length}
                  </span>
                </span>
                <select
                  className="w-full rounded-md border border-line-strong bg-white px-3 py-2 text-[13px] text-ink outline-none focus:border-teal"
                  value={previewSelected?._uid || ''}
                  onChange={(e) => selectPreviewTable(e.target.value)}
                >
                  {filteredPreviewTables.map((t) => {
                    const status = previewReviewStatus(t, savedIds)
                    const mark = status === 'fix' ? '⚠ Needs fixing — ' : status === 'ai' ? '✦ AI review — ' : ''
                    return (
                      <option key={t._uid} value={t._uid}>
                        {mark}{tablePickerLabel(t)}
                      </option>
                    )
                  })}
                </select>
              </label>
            ) : (
              <div className="flex flex-wrap items-center gap-2.5">
                {filteredPreviewTables.map((t) => {
                  const status = previewReviewStatus(t, savedIds)
                  const active = t._uid === previewSelected?._uid
                  return (
                    <div
                      key={t._uid}
                      className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 transition-colors duration-dhara ease-dhara ${
                        active
                          ? 'border-transparent bg-teal-deep'
                          : status === 'fix'
                            ? 'border-coral/50 bg-error-bg ring-1 ring-coral/30 hover:border-coral'
                            : status === 'ai'
                              ? 'border-[#5B8DEF]/50 bg-[#EEF4FF] ring-1 ring-[#5B8DEF]/25 hover:border-[#2F6FED]'
                              : 'border-green bg-sage hover:border-teal/35'
                      }`}
                      onClick={() => selectPreviewTable(t._uid)}
                      title={
                        status === 'fix'
                          ? `${t.id} — Needs fixing`
                          : status === 'ai'
                            ? `${t.id} — AI filled — please review`
                            : `${t.id} — Reviewed / OK`
                      }
                    >
                      <span className={`flex h-4.5 w-4.5 items-center justify-center rounded-full ${
                        active
                          ? 'bg-cream/20 text-cream'
                          : status === 'fix'
                            ? 'bg-coral text-white'
                            : status === 'ai'
                              ? 'bg-[#2F6FED] text-white'
                              : 'bg-green text-white'
                      }`}>
                        {status === 'fix' ? (
                          <AlertTriangle className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
                        ) : status === 'ai' ? (
                          <Sparkles className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
                        ) : (
                          <Check className="h-2.5 w-2.5" strokeWidth={2.5} aria-hidden />
                        )}
                      </span>
                      <span className={`font-sans text-xs font-medium ${active ? 'text-cream' : 'text-ink'}`}>{tableCode(t)}</span>
                      <span className={`text-[10.5px] font-semibold uppercase tracking-wide ${
                        active
                          ? 'text-cream/70'
                          : status === 'fix'
                            ? 'text-coral'
                            : status === 'ai'
                              ? 'text-[#2F6FED]'
                              : 'text-ink-soft'
                      }`}>
                        {status === 'fix' ? 'Fix' : status === 'ai' ? 'AI' : 'OK'}
                      </span>
                    </div>
                  )
                })}
              </div>
            )}
            {previewSelected && filteredPreviewTables.some((t) => t._uid === previewSelected._uid) && (
              <TableViewer table={previewSelected} compact />
            )}
            <ReconcileIds
              tables={batchAllTables}
              scopeTables={visiblePreviewTables}
              visibleId={
                filteredPreviewTables.some((t) => t._uid === previewSelected?._uid)
                  ? previewSelected?._uid
                  : filteredPreviewTables[0]?._uid
              }
              onContinue={applyReconcile}
              onNavigate={selectPreviewTable}
              onSave={markTableSaved}
              savedIds={savedIds}
            />
          </div>
        )}

        {step === 3 && matchResult && (
          <GroupingWorkspace
            matchResult={matchResult}
            onMatchResultChange={setMatchResult}
            manualGrouping={manualGrouping}
            onManualGroupingChange={setManualGrouping}
            editingGroups={editingGroups}
            onEditingGroupsChange={setEditingGroups}
            autoSnapshot={autoMatchResultRef.current}
            onRequestAutomatic={handleRequestAutomatic}
            onContinueToMetadata={requestContinueToMetadata}
            metadataFilling={metadataFilling}
            toast={groupingToast}
            onDismissToast={() => setGroupingToast(null)}
          />
        )}

        <PostPreviewLaterSteps
          step={step}
          matchResult={matchResult}
          metadataFiles={metadataFiles}
          metadataStarted={metadataStarted}
          metaLabel={metaLabel}
          metadataId={metadataId}
          metadataIds={metadataIds}
          datasetLabel="This dataset"
          hasKey={hasKey}
          onBackToGrouping={() => setStep(3)}
          onMetadataDone={(label, ids) => {
            setMetaLabel(label || 'this release')
            setMetadataIds(ids || [])
            setMetadataId((ids && ids[0]) || null)
            setPendingGroups(null)
            setStatusPage({
              ...STATUS_TRANSITIONS.metadataToClassify,
              key: 'metadataToClassify',
              msPerStep: 550,
              after: () => {
                setStatusPage(null)
                setStep(5)
              },
            })
          }}
          onClassifyContinue={publishFromClassify}
          onGoSettings={onGoSettings}
          onGoDashboard={onGoDashboard}
          onGoCatalogue={onGoCatalogue}
          onUploadAnother={onUploadAnother}
        />

        </div>
        </div>
      </div>
    </div>
  )
}
