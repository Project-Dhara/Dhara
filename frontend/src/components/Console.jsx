'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import KydsSummaryCard from './KydsSummaryCard'
import TableViewer from './TableViewer'
import BatchUpload from './BatchUpload'
import BatchReview from './BatchReview'
import ReconcileIds from './ReconcileIds'
import Classify from './Classify'
import Publish from './Publish'
import Button from './ui/Button'
import Badge from './ui/Badge'
import ErrorBanner from './ui/ErrorBanner'
import { withAuthHeaders } from '../lib/auth'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { StageSidebar, stageIndexForStep } from './ConsoleStages'

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

// Inline-editable group name shown on the grouping page — lets the user
// override the auto-derived name (e.g. if it's still not quite right) without
// leaving the page.
function GroupNameEditor({ name, onSave }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(name)

  const startEdit = () => { setDraft(name); setEditing(true) }
  const cancelEdit = () => setEditing(false)
  const saveEdit = () => {
    const trimmed = draft.trim()
    if (trimmed && trimmed !== name) onSave(trimmed)
    setEditing(false)
  }
  const handleKeyDown = (e) => {
    if (e.key === 'Enter') saveEdit()
    if (e.key === 'Escape') cancelEdit()
  }

  if (editing) {
    return (
      <span className="flex min-w-0 flex-1 items-center gap-1.5">
        <input
          className="min-w-0 flex-1 rounded border border-teal px-2 py-1 text-sm"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
          spellCheck={false}
        />
        <button className="rounded bg-teal px-1.5 py-1 text-xs text-white hover:bg-teal-dark" onClick={saveEdit} title="Save">✓</button>
        <button className="rounded border border-line px-1.5 py-1 text-xs text-ink-soft hover:bg-outer-bg" onClick={cancelEdit} title="Cancel">✕</button>
      </span>
    )
  }
  return (
    <span className="flex min-w-0 flex-1 items-center gap-1.5">
      <span className="text-sm font-semibold text-ink">{name}</span>
      <button className="text-xs text-ink-soft hover:text-teal" onClick={startEdit} title="Edit group name">✎</button>
    </span>
  )
}

// Mirrors backend/catalogue_matching.py's _EMPTY_METADATA -- a manually
// created group needs the same blank catalogue fields an auto-grouped one
// gets, so downstream metadata/push steps treat it identically.
const EMPTY_GROUP_METADATA = {
  title: '', product: '', category: '', geography: '', frequency: '',
  time_period: '', data_source: '', description: '', last_updated: '',
  future_release: '', key_statistics: '', remarks: '',
}

// Ports of backend/catalogue_matching.py's `_base_title` / `build_group_name`
// / `auto_group_tables` -- needed client-side so a title correction made on
// the preview page can re-derive group membership and each group's display
// name from the *saved* title, instead of leaving both stuck on whatever the
// backend computed from the pre-correction title at upload time.
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

// Generic centered-overlay modal shell -- replaces .push-overlay, used by
// AddGroupModal and the manual/automatic-grouping confirm dialogs.
function ModalOverlay({ children, className = '' }) {
  return (
    <div className="fixed inset-0 z-[1000] flex items-center justify-center bg-[rgba(11,30,45,0.5)] p-4" role="dialog" aria-modal="true">
      <div className={`flex max-h-[85vh] w-full flex-col gap-3.5 overflow-hidden rounded-xl bg-surface p-5 shadow-dhara ${className}`}>
        {children}
      </div>
    </div>
  )
}

// Lets the user hand-pick a set of tables (by title) and bundle them into a
// new group, for cases the automatic title-based grouping didn't handle the
// way they wanted. `tables` is the full list of {id, title} candidates.
function AddGroupModal({ tables, onCreate, onClose }) {
  const [name, setName] = useState('')
  const [selected, setSelected] = useState(() => new Set())

  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const canCreate = name.trim() && selected.size > 0

  return (
    <ModalOverlay className="max-w-[560px]">
      <div className="flex items-center justify-between">
        <div className="text-[16px] font-bold text-ink">Add group manually</div>
        <button className="rounded p-1 text-lg text-ink-soft hover:bg-cream hover:text-ink" onClick={onClose} aria-label="Close">×</button>
      </div>

      <label className="flex flex-col gap-1.5 text-[13px] text-ink-soft">
        <span>Group name</span>
        <input
          className="rounded-md border border-line px-2.5 py-2 text-sm text-ink"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Infant Mortality By Age"
          autoFocus
        />
      </label>

      <div className="flex max-h-[40vh] flex-col overflow-y-auto rounded-lg border border-line">
        {tables.map((t) => (
          <label key={t.id} className="flex cursor-pointer items-center gap-2.5 border-b border-cream px-3 py-2 text-[13px] last:border-b-0 hover:bg-cream">
            <input
              type="checkbox"
              checked={selected.has(t.id)}
              onChange={() => toggle(t.id)}
            />
            <span className="flex-1 text-ink">{t.title || 'Untitled table'}</span>
            <span className="whitespace-nowrap text-[11.5px] text-ink-soft">{t.id}</span>
          </label>
        ))}
      </div>

      <div className="flex items-center justify-end gap-2.5">
        <span className="mr-auto text-[13px] text-ink-soft">{selected.size} table{selected.size !== 1 ? 's' : ''} selected</span>
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button variant="primary" disabled={!canCreate} onClick={() => onCreate(name.trim(), [...selected])}>Create group</Button>
      </div>
    </ModalOverlay>
  )
}

function ConfirmDialog({ title, body, onCancel, onContinue }) {
  return (
    <ModalOverlay className="max-w-[440px]">
      <div className="text-[16px] font-bold text-ink">{title}</div>
      <p className="text-[13px] text-ink-soft">{body}</p>
      <div className="flex items-center justify-end gap-2.5">
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button variant="primary" onClick={onContinue}>Continue</Button>
      </div>
    </ModalOverlay>
  )
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
      purpose: 'Upload the workbooks and their metadata tag files for this release, or a PDF report instead.',
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

// Step 1 file-type choice. XLSX reveals the workbook uploader in the same
// content panel; PDF opens the file picker immediately and starts upload —
// no second "drop a PDF" screen that restates the same choice.
function UploadChoice({ choice, onChoose, onPdfFile, pdfUploading, pdfError, onClearPdfError }) {
  const pdfInputRef = useRef(null)
  const [pdfDragging, setPdfDragging] = useState(false)

  const takePdf = (file) => {
    if (!file || !/\.pdf$/i.test(file.name) || pdfUploading) return
    onPdfFile(file)
  }

  if (choice === 'xlsx') {
    return (
      <button type="button" className="self-start text-[13px] font-semibold text-teal hover:text-teal-dark" onClick={() => onChoose(null)}>
        ← Choose a different file type
      </button>
    )
  }

  return (
    <div className="flex flex-col gap-4">
      <input
        ref={pdfInputRef}
        type="file"
        accept=".pdf"
        className="hidden"
        disabled={pdfUploading}
        onChange={(e) => {
          takePdf(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      <div className="grid w-full grid-cols-1 gap-4 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => onChoose('xlsx')}
          disabled={pdfUploading}
          className="flex min-h-[112px] w-full flex-col items-start gap-2 rounded-xl border border-line bg-cream/40 p-5 text-left transition-colors hover:border-teal hover:bg-cream disabled:cursor-not-allowed disabled:opacity-60"
        >
          <div className="text-[16px] font-bold text-ink">Upload data workbooks (.xlsx)</div>
          <div className="text-[13px] leading-snug text-ink-soft">Matched against metadata tag files and grouped automatically.</div>
        </button>
        <button
          type="button"
          disabled={pdfUploading}
          onClick={() => !pdfUploading && pdfInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setPdfDragging(true) }}
          onDragLeave={() => setPdfDragging(false)}
          onDrop={(e) => {
            e.preventDefault()
            setPdfDragging(false)
            takePdf(e.dataTransfer.files?.[0])
          }}
          className={`flex min-h-[112px] w-full flex-col items-start gap-2 rounded-xl border border-dashed bg-cream/40 p-5 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
            pdfDragging ? 'border-teal bg-sage' : 'border-line hover:border-teal hover:bg-cream'
          }`}
        >
          <div className="text-[16px] font-bold text-ink">{pdfUploading ? 'Uploading PDF…' : 'Upload PDF reports'}</div>
          <div className="text-[13px] leading-snug text-ink-soft">
            {pdfUploading ? 'Starting extraction…' : 'Click or drop a PDF — tables are extracted and reviewed for accuracy.'}
          </div>
        </button>
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
  const [pdfUploading, setPdfUploading] = useState(false)
  const [pdfError, setPdfError] = useState('')
  const router = useRouter()

  // Consolidates the three previously-independent dialog booleans
  // (showAddGroup / showManualGroupingConfirm / showAutoGroupingConfirm)
  // into one piece of state, so at most one dialog can ever be open at a
  // time by construction. Values: null | 'addGroup' | 'manualConfirm' | 'autoConfirm'.
  const [activeDialog, setActiveDialog] = useState(null)
  // Lets the user delete a group or create a new group for unmatched tables
  // from the automatically-grouped view, without wiping the existing
  // groups the way "Group manually" does.
  const [editingGroups, setEditingGroups] = useState(false)
  const [dragOverGroup, setDragOverGroup] = useState(null) // group index the dragged table is currently over, or null
  const [groupingToast, setGroupingToast] = useState(null)

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

  const renameBatchGroup = (index, newName) => {
    setMatchResult((prev) => prev && ({
      ...prev,
      groups: prev.groups.map((g, i) => (i === index ? { ...g, file_name: newName } : g)),
    }))
  }

  // Batch groups carry their tables as {table, inventory_item, confidence}
  // entries -- deleting a group sends those back to unmatched_tables instead
  // of dropping them, so nothing silently disappears from the release.
  const deleteBatchGroup = (index) => {
    setMatchResult((prev) => {
      if (!prev) return prev
      const removed = prev.groups[index]
      const returned = removed.matched_tables.map((mt) => ({ table: mt.table, inventory_item: null, confidence: 'manual' }))
      return {
        ...prev,
        groups: prev.groups.filter((_, i) => i !== index),
        unmatched_tables: [...prev.unmatched_tables, ...returned],
      }
    })
  }

  // Drag-and-drop between the "Unmatched tables" card and any group card,
  // while editing (manual or automatic-view edit mode). `dest` is either a
  // group index or the string 'unmatched'. Finds the table wherever it
  // currently lives (a group's matched_tables, or unmatched_tables), pulls
  // it out from there, and drops it into the destination.
  const moveTable = (tableId, dest) => {
    setMatchResult((prev) => {
      if (!prev) return prev
      let movedEntry = null
      const groups = prev.groups.map((g) => {
        const [keep, take] = [[], []]
        g.matched_tables.forEach((mt) => (mt.table.id === tableId ? take : keep).push(mt))
        if (take.length > 0) movedEntry = take[0]
        return { ...g, matched_tables: keep }
      })
      let unmatched_tables = prev.unmatched_tables
      if (!movedEntry) {
        const idx = unmatched_tables.findIndex((u) => u.table.id === tableId)
        if (idx === -1) return prev
        movedEntry = unmatched_tables[idx]
        unmatched_tables = unmatched_tables.filter((_, i) => i !== idx)
      }
      const table = movedEntry.table
      if (dest === 'unmatched') {
        unmatched_tables = [...unmatched_tables, { table, confidence: 'none' }]
      } else {
        groups[dest] = {
          ...groups[dest],
          matched_tables: [...groups[dest].matched_tables, { table, inventory_item: null, confidence: 'manual' }],
        }
      }
      return { ...prev, groups, unmatched_tables }
    })
  }

  // Dragging every table out of a group (or deleting them one by one)
  // leaves an empty group card behind -- drop those automatically once the
  // user is done editing, rather than pushing empty groups downstream.
  const finishEditingGroups = () => {
    setMatchResult((prev) => prev && ({
      ...prev,
      groups: prev.groups.filter((g) => g.matched_tables.length > 0),
    }))
    setEditingGroups(false)
  }

  const revertToAutomaticBatchGrouping = () => {
    if (!autoMatchResultRef.current) return
    setMatchResult(autoMatchResultRef.current)
    setManualGrouping(false)
    setEditingGroups(false)
  }

  const createBatchGroup = (name, tableIds) => {
    setMatchResult((prev) => {
      if (!prev) return prev
      const idSet = new Set(tableIds)
      const pulled = []
      const groups = prev.groups
        .map((g) => {
          const [keep, take] = [[], []]
          g.matched_tables.forEach((mt) => (idSet.has(mt.table.id) ? take : keep).push(mt))
          pulled.push(...take)
          return { ...g, matched_tables: keep }
        })
        .filter((g) => g.matched_tables.length > 0)
      const unmatchedKeep = []
      prev.unmatched_tables.forEach((u) => {
        if (idSet.has(u.table.id)) pulled.push({ table: u.table, inventory_item: null, confidence: 'manual' })
        else unmatchedKeep.push(u)
      })
      groups.push({
        workbook_index: groups.length,
        file_name: name,
        metadata: { ...EMPTY_GROUP_METADATA },
        concepts: [],
        classifications: {},
        matched_tables: pulled,
      })
      return { ...prev, groups, unmatched_tables: unmatchedKeep }
    })
    setActiveDialog(null)
  }

  // Discards whatever grouping (automatic or partially-manual) currently
  // exists and starts a clean slate of hand-built groups -- every table
  // becomes "available" again for the first group the user creates.
  const startManualGrouping = () => {
    if (!manualGrouping) {
      setMatchResult((prev) => prev && ({
        ...prev,
        groups: [],
        unmatched_tables: batchAllTables.map((t) => ({ table: t, confidence: 'none' })),
      }))
      setManualGrouping(true)
    }
    setActiveDialog('addGroup')
  }

  // First switch into manual grouping wipes the current grouping, so confirm
  // with the user before doing it -- they can always get it back via
  // "Automatic grouping" afterwards. Once already in manual mode, adding
  // another group doesn't erase anything, so no confirmation is needed.
  const requestManualGrouping = () => {
    if (manualGrouping) {
      startManualGrouping()
    } else {
      setActiveDialog('manualConfirm')
    }
  }

  // Reverting to automatic grouping erases the hand-built groups just as
  // switching into manual grouping erases the automatic ones -- confirm
  // with the user before doing it.
  const requestAutomaticGrouping = () => {
    setActiveDialog('autoConfirm')
  }

  // Every table must end up in a named group before moving on -- block the
  // transition and warn instead of silently leaving tables unmatched,
  // whether they were left that way by manual grouping, editing, or drag-
  // and-drop.
  const requestContinueToMetadata = () => {
    if (matchResult?.unmatched_tables.length > 0) {
      setGroupingToast('All tables must be assigned to a group with a group name before continuing.')
      return
    }
    setStep(4)
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
    setStep(3)
  }

  const publishFromClassify = () => {
    setStep(6)
  }

  const handleMatched = (data) => {
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

  const back = () => setStep((s) => Math.max(1, s - 1))

  const stageIdx = stageIndexForStep(step)

  // Once a file type is chosen, drop the generic "xlsx or PDF" copy so the
  // header doesn't restate what the upload widget already says.
  const info = (() => {
    const base = stepInfoFor(step)
    if (step !== 1 || uploadChoice !== 'xlsx') return base
    return {
      title: 'Select dataset and metadata files',
      purpose: 'Upload the workbooks and their metadata tag files for this release.',
      next: base.next,
    }
  })()

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

  // Grouping step: one segmented "mode" derived from existing state, so the
  // three old separate entry points (Edit / switch-to-manual / add-group)
  // collapse into one toggle + a single contextual secondary action.
  const groupingMode = manualGrouping ? 'manual' : 'automatic'
  const dragEnabled = manualGrouping || editingGroups

  return (
    <div className="flex items-start gap-6">
      <StageSidebar
        stageIdx={stageIdx}
        step={step}
        maxStepReached={maxStepReached}
        expandedStage={expandedStage}
        setExpandedStage={setExpandedStage}
        goToStep={goToStep}
      />

      <div className="flex min-w-0 flex-1 flex-col gap-[18px]">
        {/* Page header — title / purpose stay above the content panel */}
        <div className="flex flex-col">
          {step > 1 && step < 6 && (
            <div className="mb-3.5 cursor-pointer text-[15px] font-semibold text-teal" onClick={back}>← {BACK_LABELS[step]}</div>
          )}
          <div className="flex items-center justify-between gap-6">
            <div>
              <div className="font-display text-[32px] font-medium leading-tight text-ink">{info.title}</div>
              <div className="mt-1 text-[15px] text-ink-soft">{info.purpose}</div>
              {info.next && <div className="mt-0.5 text-[13px] font-medium text-teal">{info.next}</div>}
            </div>
            {stageIdx === 0 && (step === 1 || step === 2) && <KydsSummaryCard variant="corner" />}
          </div>
        </div>

        {/* Shared content panel — choice cards, then tables / grouping / later steps */}
        <div className="flex flex-col gap-5 rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
        {step === 1 && (
          <div className="flex flex-col gap-6">
            <UploadChoice
              choice={uploadChoice}
              onChoose={setUploadChoice}
              onPdfFile={handlePdfFile}
              pdfUploading={pdfUploading}
              pdfError={pdfError}
              onClearPdfError={() => setPdfError('')}
            />
            {uploadChoice === 'xlsx' && <BatchUpload onMatched={handleMatched} />}
          </div>
        )}

        {step === 2 && previewTables.length > 0 && (
          <div className="flex flex-col gap-5">
            {previewDatasets.length > 1 && (
              <div className="flex flex-wrap items-center gap-2.5">
                <span className="font-sans text-lg font-semibold text-[#8E9398]">Dataset:</span>
                {previewDatasets.length > 2 ? (
                  <select
                    className="rounded-md border border-line px-3 py-1.5 text-sm"
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
                      className={`cursor-pointer rounded-full border px-3 py-1.5 text-sm ${name === effectiveDataset ? 'border-teal bg-teal text-white' : 'border-line text-ink hover:border-teal'}`}
                      onClick={() => selectPreviewDataset(name)}
                      title={name}
                    >
                      {name}
                    </div>
                  ))
                )}
              </div>
            )}
            {mismatchedPreviewTables.length > 0 && (
              <div className={`rounded-lg border px-4 py-3 text-sm font-medium ${unsavedMismatched.length === 0 ? 'border-green bg-[#f2f8f5] text-[#2f6b3f]' : 'border-[#d9822b] bg-[#fdf1e2] text-[#8a4a10]'}`}>
                {unsavedMismatched.length > 0
                  ? `⚠ ${unsavedMismatched.length} of ${mismatchedPreviewTables.length} flagged table${mismatchedPreviewTables.length !== 1 ? 's' : ''} still need correcting & saving — open each orange tab below.`
                  : `✓ All ${mismatchedPreviewTables.length} flagged table${mismatchedPreviewTables.length !== 1 ? 's' : ''} saved.`}
              </div>
            )}
            <div className="flex flex-wrap items-center gap-2.5">
              {visiblePreviewTables.map((t) => {
                const flagged = !!t.id_title_mismatch
                const unsaved = flagged && !savedIds.has(t._uid)
                const resolved = !unsaved
                const active = t._uid === previewSelected?._uid
                return (
                  <div
                    key={t._uid}
                    className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 ${
                      active ? 'border-teal bg-teal' : unsaved ? 'border-[#d9822b] bg-[#fdf1e2] ring-1 ring-[#d9822b]' : resolved ? 'border-green bg-[#f2f8f5]' : 'border-line bg-white'
                    }`}
                    onClick={() => selectPreviewTable(t._uid)}
                    title={flagged ? `${t.id} — Source Table ID / Title need confirmation` : `${t.id} — no validation errors`}
                  >
                    <span className={`flex h-4.5 w-4.5 items-center justify-center rounded-full text-[10px] font-bold ${
                      active ? 'bg-white text-teal' : unsaved ? 'bg-[#d9822b] text-white' : 'bg-green text-white'
                    }`}>{unsaved ? '!' : '✓'}</span>
                    <span className={`font-sans text-xs font-medium ${active ? 'text-white' : 'text-ink'}`}>{tableCode(t)}</span>
                    <span className={`text-xs ${active ? 'text-[#a9cfc9]' : 'text-[#8E9398]'}`}>{t.row_count} rows</span>
                  </div>
                )
              })}
            </div>
            {previewSelected && (
              <TableViewer table={previewSelected} compact />
            )}
            <ReconcileIds
              tables={batchAllTables}
              scopeTables={visiblePreviewTables}
              visibleId={previewSelected?._uid}
              onContinue={applyReconcile}
              onNavigate={selectPreviewTable}
              onSave={markTableSaved}
              savedIds={savedIds}
            />
          </div>
        )}

        {step === 3 && matchResult && (
          <div className="flex flex-col gap-4">
            <div className="flex flex-wrap items-center gap-3">
              <div className="inline-flex rounded-full border border-line bg-white p-0.5">
                <button
                  type="button"
                  className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${groupingMode === 'automatic' ? 'bg-teal text-white' : 'text-ink-soft hover:text-ink'}`}
                  onClick={() => groupingMode !== 'automatic' && requestAutomaticGrouping()}
                >
                  Automatic (recommended)
                </button>
                <button
                  type="button"
                  className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${groupingMode === 'manual' ? 'bg-teal text-white' : 'text-ink-soft hover:text-ink'}`}
                  onClick={() => groupingMode !== 'manual' && requestManualGrouping()}
                >
                  Manual
                </button>
              </div>
              {groupingMode === 'automatic' ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => (editingGroups ? finishEditingGroups() : setEditingGroups(true))}
                >
                  {editingGroups ? 'Done editing' : 'Edit groups'}
                </Button>
              ) : (
                <Button variant="secondary" size="sm" onClick={() => setActiveDialog('addGroup')}>+ Add another group</Button>
              )}
            </div>

            {dragEnabled && (
              <p className="m-0 text-[13px] font-medium text-[#c9610f]">
                ⚠ Every table must be assigned to a group with a group name before you continue.
              </p>
            )}

            {activeDialog === 'manualConfirm' && (
              <ConfirmDialog
                title="Switch to manual grouping?"
                body='The current grouping will be erased. You can get it back by pressing "Automatic grouping" again.'
                onCancel={() => setActiveDialog(null)}
                onContinue={() => { setActiveDialog(null); startManualGrouping() }}
              />
            )}
            {activeDialog === 'autoConfirm' && (
              <ConfirmDialog
                title="Switch to automatic grouping?"
                body="The current grouping will be erased and reverted to the automatic grouping."
                onCancel={() => setActiveDialog(null)}
                onContinue={() => { setActiveDialog(null); revertToAutomaticBatchGrouping() }}
              />
            )}

            {/* Edit mode gets a visually distinct region (dashed teal ring)
                around the whole group-card list, so it's obvious at a
                glance whether the page is in confirm-mode or edit-mode --
                not just via each button's own disabled/enabled state. */}
            <div className={`flex flex-col gap-3 rounded-xl p-1 ${dragEnabled ? 'ring-2 ring-dashed ring-teal/40' : ''}`}>
              {matchResult.groups.map((g, i) => (
                <div
                  className={`flex flex-col gap-1.5 rounded-[10px] border bg-white p-4 transition-colors ${dragEnabled && dragOverGroup === i ? 'border-teal bg-[#f2f8f7]' : 'border-line'}`}
                  key={i}
                  onDragOver={dragEnabled ? (e) => { e.preventDefault(); setDragOverGroup(i) } : undefined}
                  onDragLeave={dragEnabled ? () => setDragOverGroup((d) => (d === i ? null : d)) : undefined}
                  onDrop={dragEnabled ? (e) => {
                    e.preventDefault()
                    const tableId = e.dataTransfer.getData('text/plain')
                    if (tableId) moveTable(tableId, i)
                    setDragOverGroup(null)
                  } : undefined}
                >
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="text-xs font-semibold uppercase tracking-wide text-ink-soft">Group name:</span>
                    <GroupNameEditor name={g.file_name} onSave={(newName) => renameBatchGroup(i, newName)} />
                    <span className="whitespace-nowrap rounded-full bg-cream px-2.5 py-0.5 text-xs text-ink-soft">{g.matched_tables.length} table{g.matched_tables.length !== 1 ? 's' : ''}</span>
                    {dragEnabled && (
                      <button className="rounded border border-line px-1.5 py-1 text-xs text-ink-soft hover:border-coral hover:bg-[#fdecec] hover:text-coral" onClick={() => deleteBatchGroup(i)} title="Delete group">🗑</button>
                    )}
                  </div>
                  <table className="w-full border-collapse text-[13px]">
                    <thead>
                      <tr>
                        <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">Dataset ID</th>
                        <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">Table Title</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.matched_tables.map((mt) => (
                        <tr
                          key={mt.table.id}
                          draggable={dragEnabled}
                          onDragStart={dragEnabled ? (e) => { e.dataTransfer.setData('text/plain', mt.table.id) } : undefined}
                          className={dragEnabled ? 'cursor-grab hover:bg-cream' : undefined}
                        >
                          <td className="border-b border-line py-1.5 font-bold text-teal">{mt.table.id}</td>
                          <td className="border-b border-line py-1.5">{mt.table.title || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {dragEnabled && g.matched_tables.length === 0 && (
                    <p className="m-0 text-xs italic text-ink-soft">Drag tables here</p>
                  )}
                </div>
              ))}
              {(dragEnabled || matchResult.unmatched_tables.length > 0) && (
                <div
                  className={`flex flex-col gap-1.5 rounded-[10px] border p-4 ${dragEnabled && dragOverGroup === 'unmatched' ? 'border-teal bg-[#f2f8f7]' : 'border-[#f3c98b] bg-[#fffaf1]'}`}
                  onDragOver={dragEnabled ? (e) => { e.preventDefault(); setDragOverGroup('unmatched') } : undefined}
                  onDragLeave={dragEnabled ? () => setDragOverGroup((d) => (d === 'unmatched' ? null : d)) : undefined}
                  onDrop={dragEnabled ? (e) => {
                    e.preventDefault()
                    const tableId = e.dataTransfer.getData('text/plain')
                    if (tableId) moveTable(tableId, 'unmatched')
                    setDragOverGroup(null)
                  } : undefined}
                >
                  <div className="flex items-center justify-between gap-2.5">
                    <span className="text-sm font-semibold text-ink">⚠ Unmatched tables</span>
                    <span className="whitespace-nowrap rounded-full bg-cream px-2.5 py-0.5 text-xs text-ink-soft">{matchResult.unmatched_tables.length}</span>
                  </div>
                  {dragEnabled && (
                    <p className="m-0 text-xs italic text-ink-soft">Drag tables here to unassign, or onto a group above to assign</p>
                  )}
                  <table className="w-full border-collapse text-[13px]">
                    <thead>
                      <tr>
                        <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">Dataset ID</th>
                        <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">Table Title</th>
                      </tr>
                    </thead>
                    <tbody>
                      {matchResult.unmatched_tables.map((u) => (
                        <tr
                          key={u.table.id}
                          draggable={dragEnabled}
                          onDragStart={dragEnabled ? (e) => { e.dataTransfer.setData('text/plain', u.table.id) } : undefined}
                          className={dragEnabled ? 'cursor-grab hover:bg-cream' : undefined}
                        >
                          <td className="border-b border-line py-1.5 font-bold text-teal">{u.table.id}</td>
                          <td className="border-b border-line py-1.5">{u.table.title || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            <div className="flex items-center gap-4">
              {editingGroups ? (
                <Button variant="primary" onClick={finishEditingGroups}>Done editing</Button>
              ) : (
                <Button variant="primary" onClick={requestContinueToMetadata}>Continue to metadata →</Button>
              )}
            </div>

            {groupingToast && (
              <div className="fixed right-6 top-6 z-[1200] flex animate-toast-in items-center gap-3 rounded-[10px] border border-[#c9610f] bg-[#e2711d] px-4 py-3 pl-4.5 font-sans text-sm font-medium leading-snug text-[#111] shadow-[0_8px_24px_rgba(226,113,29,0.22)]" role="alert">
                <span>{groupingToast}</span>
                <button type="button" className="p-0.5 text-lg leading-none text-[#111] opacity-70 hover:opacity-100" onClick={() => setGroupingToast(null)} aria-label="Dismiss">×</button>
              </div>
            )}
            {activeDialog === 'addGroup' && (
              <AddGroupModal
                tables={manualGrouping ? batchAllTables : matchResult.unmatched_tables.map((u) => u.table)}
                onCreate={createBatchGroup}
                onClose={() => setActiveDialog(null)}
              />
            )}
          </div>
        )}

        {/* Kept mounted (hidden via CSS, not removed from the tree) once the
            metadata step is reached, so stepping back to Dataset Inventory
            and returning doesn't lose whatever was already filled in here. */}
        {metadataStarted && matchResult && (
          <div style={{ display: step === 4 ? 'contents' : 'none' }}>
            <BatchReview
              matchResult={matchResult}
              metadataFiles={metadataFiles}
              onDone={(label, ids) => {
                setMetaLabel(label || 'this release')
                setMetadataIds(ids || [])
                setMetadataId((ids && ids[0]) || null)
                setPendingGroups(null)
                setStep(5)
              }}
              onCancel={() => setStep(3)}
            />
          </div>
        )}

        {step === 5 && (
          <Classify
            metadataIds={metadataIds}
            datasetLabel={metaLabel || 'This dataset'}
            onContinue={publishFromClassify}
          />
        )}

        {step === 6 && (
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
    </div>
  )
}
