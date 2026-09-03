import { useEffect, useRef, useState } from 'react'
import KydsSummaryCard from './KydsSummaryCard'
import TableViewer from './TableViewer'
import BatchUpload from './BatchUpload'
import BatchReview from './BatchReview'
import ReconcileIds from './ReconcileIds'
import Classify from './Classify'
import Publish from './Publish'

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
      <span className="group-name-edit-row">
        <input
          className="group-name-edit-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={handleKeyDown}
          autoFocus
          spellCheck={false}
        />
        <button className="id-edit-save" onClick={saveEdit} title="Save">✓</button>
        <button className="id-edit-cancel" onClick={cancelEdit} title="Cancel">✕</button>
      </span>
    )
  }
  return (
    <span className="group-name-edit-row">
      <span className="console-group-card-file">{name}</span>
      <button className="group-name-edit-btn" onClick={startEdit} title="Edit group name">✎</button>
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
    <div className="push-overlay" role="dialog" aria-modal="true">
      <div className="add-group-modal">
        <div className="add-group-modal-head">
          <div className="add-group-modal-title">Add group manually</div>
          <button className="push-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <label className="add-group-name-field">
          <span>Group name</span>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Infant Mortality By Age"
            autoFocus
          />
        </label>

        <div className="add-group-table-list">
          {tables.map((t) => (
            <label key={t.id} className="add-group-table-row">
              <input
                type="checkbox"
                checked={selected.has(t.id)}
                onChange={() => toggle(t.id)}
              />
              <span className="add-group-table-title">{t.title || 'Untitled table'}</span>
              <span className="add-group-table-id">{t.id}</span>
            </label>
          ))}
        </div>

        <div className="add-group-modal-actions">
          <span className="console-group-hint">{selected.size} table{selected.size !== 1 ? 's' : ''} selected</span>
          <button className="console-secondary-btn" onClick={onClose}>Cancel</button>
          <button
            className="console-primary-btn"
            disabled={!canCreate}
            onClick={() => onCreate(name.trim(), [...selected])}
          >
            Create group
          </button>
        </div>
      </div>
    </div>
  )
}

const STAGE_DEFS = [
  {
    name: 'Dataset Inventory', firstStep: 1, sub: 'Files, preview, grouping',
    subs: [
      { step: 1, label: 'Files' },
      { step: 2, label: 'Preview' },
      { step: 3, label: 'Grouping' },
    ],
  },
  {
    name: 'Metadata Workspace', firstStep: 4, sub: 'Title, category, coverage',
    subs: [{ step: 4, label: 'Metadata' }],
  },
  {
    name: 'Transformation & Harmonisation', firstStep: 5, sub: 'Concepts and code maps',
    subs: [{ step: 5, label: 'Classification & harmonisation' }],
  },
  {
    name: 'Dataset Publication', firstStep: 6, sub: 'API, MCP, catalogue',
    subs: [{ step: 6, label: 'Publish' }],
  },
]

function stepInfoFor(step) {
  return [
    { title: 'Dataset inventory', sub: 'Bring datasets into DHARA.' },
    {
      title: 'Select dataset and metadata files',
      sub: 'Upload the workbooks and their metadata tag files for this release.',
    },
    {
      title: 'Preview'
    },
    { title: 'Grouping' },
    { title: 'Metadata' },
    { title: 'Classification and harmonisation', sub: 'Map columns to standard concepts and code lists.' },
    { title: 'Publish this release', sub: 'Register the API and MCP endpoints for this release.' },
  ][step]
}

const BACK_LABELS = [
  '', 'Choose another method', 'Change files', 'Back to preview', 'Back to grouping', 'Back to metadata',
]

function stageIndexForStep(step) {
  if (step <= 3) return 0
  if (step === 4) return 1
  if (step === 5) return 2
  return 3
}

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

export default function Console({ hasKey, onGoSettings, onGoDashboard, onGoCatalogue, onUploadAnother }) {
  const persisted = loadPersisted()

  const [step, setStep] = useState(persisted?.step ?? 1)
  const mode = 'batch'

  const [showAddGroup, setShowAddGroup] = useState(false)
  const [showManualGroupingConfirm, setShowManualGroupingConfirm] = useState(false)
  const [showAutoGroupingConfirm, setShowAutoGroupingConfirm] = useState(false)
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

  useEffect(() => {
    const toSave = {
      step, matchResult, batchPreviewId, selectedDataset,
      metaLabel, metadataId, metadataIds, savedIds: [...savedIds], metadataStarted, maxStepReached,
      autoMatchResult: autoMatchResultRef.current,
    }
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(toSave))
    } catch {
      // best-effort — e.g. storage full or unavailable
    }
  }, [step, matchResult, batchPreviewId, selectedDataset, metaLabel, metadataId, metadataIds, savedIds, metadataStarted, maxStepReached])

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
    setShowAddGroup(false)
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
    setShowAddGroup(true)
  }

  // First switch into manual grouping wipes the current grouping, so confirm
  // with the user before doing it -- they can always get it back via
  // "Automatic grouping" afterwards. Once already in manual mode, adding
  // another group doesn't erase anything, so no confirmation is needed.
  const requestManualGrouping = () => {
    if (manualGrouping) {
      startManualGrouping()
    } else {
      setShowManualGroupingConfirm(true)
    }
  }

  // Reverting to automatic grouping erases the hand-built groups just as
  // switching into manual grouping erases the automatic ones -- confirm
  // with the user before doing it.
  const requestAutomaticGrouping = () => {
    setShowAutoGroupingConfirm(true)
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
  const info = stepInfoFor(step)

  // Which stage's substeps are expanded in the sidebar — defaults to
  // whichever stage the user is currently in, but clicking another stage's
  // header expands that one (and collapses the rest) without navigating,
  // so the user can peek at a stage's substeps before jumping into one.
  const [expandedStage, setExpandedStage] = useState(stageIdx)
  useEffect(() => {
    setExpandedStage(stageIdx)
  }, [stageIdx])

  // A substep can only be jumped to once the user has actually reached it
  // before — same rule as the old goStage, just applied per substep now
  // that each one is individually clickable.
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

  return (
    <div className="console">
      <aside className="console-stages">
        <div className="console-stages-label">Console stages</div>
        {STAGE_DEFS.map((s, i) => {
          const expanded = i === expandedStage
          return (
            <div key={s.name} className="console-stage-block">
              <div
                className={`console-stage${i === stageIdx ? ' console-stage-active' : ''}${i < stageIdx ? ' console-stage-done' : ''}${expanded ? ' console-stage-expanded' : ''}`}
                onClick={() => setExpandedStage(i)}
              >
                <div className="console-stage-mark">{i < stageIdx ? '✓' : i + 1}</div>
                <div className="console-stage-text">
                  <div className="console-stage-name">{s.name}</div>
                  <div className="console-stage-sub">{s.sub}</div>
                </div>
              </div>
              {expanded && (
                <div className="console-substeps">
                  {s.subs.map((sub) => {
                    const active = sub.step === step
                    const done = sub.step < step
                    const reachable = sub.step <= maxStepReached
                    return (
                      <div
                        key={sub.step}
                        className={`console-substep${active ? ' console-substep-active' : ''}${done ? ' console-substep-done' : ''}${!reachable ? ' console-substep-disabled' : ''}`}
                        onClick={() => reachable && goToStep(sub.step)}
                      >
                        <span className="console-substep-dot" />
                        <span className="console-substep-label">{sub.label}</span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </aside>

      <div className="console-main">
        <div className="console-header-block">
          {step > 1 && step < 6 && (
            <div className="console-back" onClick={back}>← {BACK_LABELS[step]}</div>
          )}
          <div className="console-header">
            <div>
              <div className="console-step-title">{info.title}</div>
              <div className="console-step-sub">{info.sub}</div>
            </div>
            <div className="console-header-right">
              {stageIdx === 0 && (step === 1 || step === 2) && <KydsSummaryCard variant="corner" />}
            </div>
          </div>
        </div>

        {step === 1 && (
          <BatchUpload onMatched={handleMatched} />
        )}

        {step === 2 && previewTables.length > 0 && (
          <div className="console-preview-step">
            {previewDatasets.length > 1 && (
              <div className="console-preview-datasets">
                <span className="console-preview-datasets-label">Dataset:</span>
                {previewDatasets.length > 2 ? (
                  <select
                    className="console-preview-dataset-select"
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
                      className={`console-preview-dataset${name === effectiveDataset ? ' console-preview-dataset-active' : ''}`}
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
              <div className={`console-preview-flag-banner${unsavedMismatched.length === 0 ? ' console-preview-flag-banner-resolved' : ''}`}>
                {unsavedMismatched.length > 0
                  ? `⚠ ${unsavedMismatched.length} of ${mismatchedPreviewTables.length} flagged table${mismatchedPreviewTables.length !== 1 ? 's' : ''} still need correcting & saving — open each orange tab below.`
                  : `✓ All ${mismatchedPreviewTables.length} flagged table${mismatchedPreviewTables.length !== 1 ? 's' : ''} saved.`}
              </div>
            )}
            <div className="console-preview-tabs">
              {visiblePreviewTables.map((t, i) => {
                const flagged = !!t.id_title_mismatch
                const unsaved = flagged && !savedIds.has(t._uid)
                const resolved = !unsaved
                return (
                  <div
                    key={t._uid}
                    className={`console-preview-tab${t._uid === previewSelected?._uid ? ' console-preview-tab-active' : ''}${unsaved ? ' console-preview-tab-flagged console-preview-tab-unreviewed' : ''}${resolved ? ' console-preview-tab-resolved' : ''}`}
                    onClick={() => selectPreviewTable(t._uid)}
                    title={flagged ? `${t.id} — Source Table ID / Title need confirmation` : `${t.id} — no validation errors`}
                  >
                    <span className="console-preview-tab-badge">{unsaved ? '!' : '✓'}</span>
                    <span className="console-preview-tab-id">{tableCode(t)}</span>
                    <span className="console-preview-tab-meta">{t.row_count} rows</span>
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
          <div className="console-grouping-step">
            <div className="console-grouping-step-header">
              {manualGrouping ? (
                <>
                  {autoMatchResultRef.current && (
                    <button className="console-secondary-btn" onClick={requestAutomaticGrouping}>Group automatically</button>
                  )}
                  <button className="console-secondary-btn" onClick={requestManualGrouping}>+ Add another group</button>
                </>
              ) : editingGroups ? (
                <>
                  {autoMatchResultRef.current && (
                    <button className="console-secondary-btn" onClick={requestAutomaticGrouping}>Group automatically</button>
                  )}
                  <button className="console-secondary-btn" onClick={() => setShowAddGroup(true)}>+ Add group</button>
                </>
              ) : (
                <button className="console-secondary-btn" onClick={() => setEditingGroups(true)}>Edit</button>
              )}
            </div>
            {(manualGrouping || editingGroups) && (
              <p className="console-group-manual-warning">
                ⚠ Every table must be assigned to a group with a group name before you continue.
              </p>
            )}
            {showManualGroupingConfirm && (
              <div className="push-overlay" role="dialog" aria-modal="true">
                <div className="add-group-modal manual-grouping-confirm-modal">
                  <div className="add-group-modal-head">
                    <div className="add-group-modal-title">Switch to manual grouping?</div>
                  </div>
                  <p className="console-group-hint">
                    The current grouping will be erased. You can get it back by pressing "Automatic grouping" again.
                  </p>
                  <div className="add-group-modal-actions">
                    <button className="console-secondary-btn" onClick={() => setShowManualGroupingConfirm(false)}>Cancel</button>
                    <button
                      className="console-primary-btn"
                      onClick={() => {
                        setShowManualGroupingConfirm(false)
                        startManualGrouping()
                      }}
                    >
                      Continue
                    </button>
                  </div>
                </div>
              </div>
            )}
            {showAutoGroupingConfirm && (
              <div className="push-overlay" role="dialog" aria-modal="true">
                <div className="add-group-modal manual-grouping-confirm-modal">
                  <div className="add-group-modal-head">
                    <div className="add-group-modal-title">Switch to automatic grouping?</div>
                  </div>
                  <p className="console-group-hint">
                    The current grouping will be erased and reverted to the automatic grouping.
                  </p>
                  <div className="add-group-modal-actions">
                    <button className="console-secondary-btn" onClick={() => setShowAutoGroupingConfirm(false)}>Cancel</button>
                    <button
                      className="console-primary-btn"
                      onClick={() => {
                        setShowAutoGroupingConfirm(false)
                        revertToAutomaticBatchGrouping()
                      }}
                    >
                      Continue
                    </button>
                  </div>
                </div>
              </div>
            )}
            <div className="console-group-summary">
              {(() => {
                const dragEnabled = manualGrouping || editingGroups
                return (
                  <>
                    {matchResult.groups.map((g, i) => (
                      <div
                        className={`console-group-card${dragEnabled && dragOverGroup === i ? ' console-group-card-drop-target' : ''}`}
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
                        <div className="console-group-card-head">
                          <span className="console-group-name-label">Group name:</span>
                          <GroupNameEditor name={g.file_name} onSave={(newName) => renameBatchGroup(i, newName)} />
                          <span className="console-group-card-count">{g.matched_tables.length} table{g.matched_tables.length !== 1 ? 's' : ''}</span>
                          {dragEnabled && (
                            <button className="group-delete-btn" onClick={() => deleteBatchGroup(i)} title="Delete group">🗑</button>
                          )}
                        </div>
                        <table className="console-group-table">
                          <thead>
                            <tr>
                              <th>Dataset ID</th>
                              <th>Table Title</th>
                            </tr>
                          </thead>
                          <tbody>
                            {g.matched_tables.map((mt) => (
                              <tr
                                key={mt.table.id}
                                draggable={dragEnabled}
                                onDragStart={dragEnabled ? (e) => { e.dataTransfer.setData('text/plain', mt.table.id) } : undefined}
                                className={dragEnabled ? 'console-group-table-row-draggable' : undefined}
                              >
                                <td>{mt.table.id}</td>
                                <td>{mt.table.title || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {dragEnabled && g.matched_tables.length === 0 && (
                          <p className="console-group-drop-hint">Drag tables here</p>
                        )}
                      </div>
                    ))}
                    {(dragEnabled || matchResult.unmatched_tables.length > 0) && (
                      <div
                        className={`console-group-card console-group-card-warn${dragEnabled && dragOverGroup === 'unmatched' ? ' console-group-card-drop-target' : ''}`}
                        onDragOver={dragEnabled ? (e) => { e.preventDefault(); setDragOverGroup('unmatched') } : undefined}
                        onDragLeave={dragEnabled ? () => setDragOverGroup((d) => (d === 'unmatched' ? null : d)) : undefined}
                        onDrop={dragEnabled ? (e) => {
                          e.preventDefault()
                          const tableId = e.dataTransfer.getData('text/plain')
                          if (tableId) moveTable(tableId, 'unmatched')
                          setDragOverGroup(null)
                        } : undefined}
                      >
                        <div className="console-group-card-head">
                          <span className="console-group-card-file">⚠ Unmatched tables</span>
                          <span className="console-group-card-count">{matchResult.unmatched_tables.length}</span>
                        </div>
                        {dragEnabled && (
                          <p className="console-group-drop-hint">Drag tables here to unassign, or onto a group above to assign</p>
                        )}
                        <table className="console-group-table">
                          <thead>
                            <tr>
                              <th>Dataset ID</th>
                              <th>Table Title</th>
                            </tr>
                          </thead>
                          <tbody>
                            {matchResult.unmatched_tables.map((u) => (
                              <tr
                                key={u.table.id}
                                draggable={dragEnabled}
                                onDragStart={dragEnabled ? (e) => { e.dataTransfer.setData('text/plain', u.table.id) } : undefined}
                                className={dragEnabled ? 'console-group-table-row-draggable' : undefined}
                              >
                                <td>{u.table.id}</td>
                                <td>{u.table.title || '—'}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </>
                )
              })()}
            </div>
            <div className="console-step-actions">
              {editingGroups ? (
                <button className="console-primary-btn" onClick={finishEditingGroups}>Done editing</button>
              ) : (
                <button className="console-primary-btn" onClick={requestContinueToMetadata}>Continue to metadata →</button>
              )}
            </div>
            {groupingToast && (
              <div className="app-toast app-toast-warn" role="alert">
                <span>{groupingToast}</span>
                <button type="button" className="app-toast-close" onClick={() => setGroupingToast(null)} aria-label="Dismiss">×</button>
              </div>
            )}
            {showAddGroup && (
              <AddGroupModal
                tables={manualGrouping ? batchAllTables : matchResult.unmatched_tables.map((u) => u.table)}
                onCreate={createBatchGroup}
                onClose={() => setShowAddGroup(false)}
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
                setStep(5)
              }}
              onCancel={() => setStep(3)}
            />
          </div>
        )}

        {step === 5 && (
          <Classify metadataIds={metadataIds} datasetLabel={metaLabel || 'This dataset'} onContinue={() => setStep(6)} />
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
  )
}
