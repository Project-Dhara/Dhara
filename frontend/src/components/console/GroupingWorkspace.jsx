'use client'

import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, ArrowRight, Check, Pencil, Search, Trash2, X } from 'lucide-react'
import Button from '../ui/Button'
import Combobox from '../ui/Combobox'
import ErrorBanner from '../ui/ErrorBanner'
import Toast from '../ui/Toast'
import {
  allTablesFromMatchResult,
  createMatchGroup,
  deleteMatchGroup,
  finishEditingMatchGroups,
  moveMatchTable,
  renameMatchGroup,
  startManualMatchGrouping,
} from '../../lib/postPreview'

function GroupNameEditor({ name, onSave, iconOnly = false }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(name)

  const startEdit = () => {
    setDraft(name)
    setEditing(true)
  }
  const cancelEdit = () => setEditing(false)
  const saveEdit = () => {
    const trimmed = draft.trim()
    if (trimmed && trimmed !== name) onSave(trimmed)
    setEditing(false)
  }

  if (editing) {
    return (
      <span className="flex min-w-0 flex-1 items-center gap-1.5">
        <input
          className="min-w-0 flex-1 rounded border border-teal px-2 py-1 text-sm"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') saveEdit()
            if (e.key === 'Escape') cancelEdit()
          }}
          autoFocus
          spellCheck={false}
        />
        <button type="button" className="inline-flex items-center justify-center rounded bg-teal px-1.5 py-1 text-xs text-white hover:bg-teal-dark" onClick={saveEdit} title="Save" aria-label="Save">
          <Check className="h-3.5 w-3.5" strokeWidth={2.5} />
        </button>
        <button type="button" className="inline-flex items-center justify-center rounded border border-line px-1.5 py-1 text-xs text-ink-soft hover:bg-outer-bg" onClick={cancelEdit} title="Cancel" aria-label="Cancel">
          <X className="h-3.5 w-3.5" strokeWidth={2} />
        </button>
      </span>
    )
  }
  if (iconOnly) {
    return (
      <button type="button" className="inline-flex h-7 w-7 items-center justify-center rounded border border-line text-ink-soft hover:border-teal hover:bg-cream hover:text-teal" onClick={startEdit} title="Edit group name" aria-label="Edit group name">
        <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />
      </button>
    )
  }
  return (
    <span className="flex min-w-0 flex-1 items-center gap-1.5">
      <span className="truncate text-sm font-semibold text-ink">{name || 'Untitled group'}</span>
      <button type="button" className="inline-flex h-6 w-6 items-center justify-center rounded text-ink-soft hover:bg-cream hover:text-teal" onClick={startEdit} title="Edit group name" aria-label="Edit group name">
        <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />
      </button>
    </span>
  )
}

function ConfirmDialog({ title, body, onCancel, onContinue }) {
  if (typeof document === 'undefined') return null
  return createPortal(
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true">
      <div className="flex max-w-md flex-col gap-3.5 rounded-xl bg-surface p-5 shadow-dhara">
        <div className="text-[16px] font-bold text-ink">{title}</div>
        <p className="m-0 text-[14px] leading-snug text-ink-soft">{body}</p>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" onClick={onContinue}>Continue</Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function AddGroupModal({ tables, onCreate, onClose, idField = 'id', allowEmpty = false }) {
  const [name, setName] = useState('')
  const [selected, setSelected] = useState(() => new Set())
  const tableKey = (t) => t[idField] || t.id || t._uid || t.table_id
  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const canCreate = Boolean(name.trim()) && (allowEmpty || selected.size > 0)
  if (typeof document === 'undefined') return null
  return createPortal(
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true">
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col gap-3.5 overflow-hidden rounded-xl bg-surface p-5 shadow-dhara">
        <div className="text-[16px] font-bold text-ink">Add group</div>
        <label className="flex flex-col gap-1.5 text-[13px] text-ink-soft">
          <span>Group name</span>
          <input
            className="rounded-lg border border-line px-3 py-2 font-body text-[14px] text-ink"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Population by State"
          />
        </label>
        <div className="flex min-h-0 flex-1 flex-col gap-1.5">
          <span className="text-[13px] text-ink-soft">
            {allowEmpty
              ? 'Optionally pick from ungrouped tables (or leave empty and use Move to later)'
              : 'Select ungrouped tables to include'}
          </span>
          <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-line">
            {tables.length === 0 ? (
              <p className="m-0 px-3 py-4 text-[13px] text-ink-soft">No ungrouped tables remaining.</p>
            ) : (
              tables.map((t) => {
                const key = tableKey(t)
                return (
                  <label
                    key={key}
                    className="flex cursor-pointer items-center gap-2.5 border-b border-cream px-3 py-2 text-[13px] last:border-b-0 hover:bg-cream"
                  >
                    <input type="checkbox" checked={selected.has(key)} onChange={() => toggle(key)} />
                    <span className="font-semibold text-teal">{t.table_id || t.id}</span>
                    <span className="truncate text-ink">{t.title || '—'}</span>
                  </label>
                )
              })
            )}
          </div>
        </div>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button
            variant="primary"
            disabled={!canCreate}
            onClick={() => onCreate(name.trim(), [...selected])}
          >
            Create group
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

function tableRowId(table) {
  return table.id || table._uid || table.table_id
}

function displayTableId(table, preferTableId) {
  if (preferTableId) return table.table_id || table.id || '—'
  return table.id || table.table_id || '—'
}

function groupSearchBlob(group) {
  const parts = [group?.file_name || '']
  for (const mt of group?.matched_tables || []) {
    parts.push(mt?.table?.title || '', mt?.table?.id || '', mt?.table?.table_id || '', mt?.table?._uid || '')
  }
  return parts.join(' ').toLowerCase()
}

function TablesPanel({
  rows,
  editEnabled,
  preferTableId,
  resolvedIdLabel,
  titleColumnLabel,
  emptyHint,
  moveOptions,
  selectedIds,
  onToggleSelected,
  onToggleAll,
  onMoveTables,
  panelClassName = '',
}) {
  const allIds = rows.map((row) => tableRowId(row.table))
  const allSelected = allIds.length > 0 && allIds.every((id) => selectedIds.has(id))
  const someSelected = allIds.some((id) => selectedIds.has(id))
  const selectedCount = allIds.filter((id) => selectedIds.has(id)).length

  return (
    <div className={`flex flex-col gap-2 ${panelClassName}`}>
      {editEnabled && rows.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-line bg-cream/70 px-3 py-2">
          <span className="text-[12.5px] font-semibold text-ink-soft">
            {selectedCount > 0 ? `${selectedCount} selected` : 'Select tables to move'}
          </span>
          <div className="min-w-[220px] flex-1 sm:max-w-sm sm:flex-none">
            <Combobox
              options={moveOptions}
              value=""
              onChange={(target) => {
                if (selectedCount === 0) return
                const ids = allIds.filter((id) => selectedIds.has(id))
                onMoveTables(ids, target === 'unmatched' ? 'unmatched' : Number(target))
              }}
              placeholder={selectedCount > 0 ? 'Move selected to group…' : 'Select tables first'}
              ariaLabel="Move selected tables to group"
              disabled={selectedCount === 0 || moveOptions.length === 0}
              menuMinWidth={480}
            />
          </div>
        </div>
      )}

      <div className="overflow-x-auto rounded-lg border border-line bg-white">
        <table className="w-full table-fixed border-collapse text-[13px]">
          <thead className="bg-cream/95">
            <tr>
              {editEnabled && (
                <th className="w-10 border-b border-line px-2 py-2 text-left">
                  <input
                    type="checkbox"
                    className="accent-teal"
                    checked={allSelected}
                    ref={(el) => {
                      if (el) el.indeterminate = someSelected && !allSelected
                    }}
                    onChange={() => onToggleAll(allIds, !allSelected)}
                    aria-label="Select all tables in this group"
                  />
                </th>
              )}
              <th className={`${editEnabled ? 'w-[28%]' : 'w-1/2'} border-b border-line px-3 py-2 text-left text-xs uppercase text-ink-soft`}>
                {resolvedIdLabel}
              </th>
              <th className={`${editEnabled ? 'w-[40%]' : 'w-1/2'} border-b border-line px-3 py-2 text-left text-xs uppercase text-ink-soft`}>
                {titleColumnLabel}
              </th>
              {editEnabled && (
                <th className="w-[28%] border-b border-line px-3 py-2 text-left text-xs uppercase text-ink-soft">
                  Move to
                </th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const tid = tableRowId(row.table)
              const checked = selectedIds.has(tid)
              return (
                <tr key={tid} className={editEnabled && checked ? 'bg-sage/40' : undefined}>
                  {editEnabled && (
                    <td className="border-b border-line px-2 py-2 align-top">
                      <input
                        type="checkbox"
                        className="accent-teal"
                        checked={checked}
                        onChange={() => onToggleSelected(tid)}
                        aria-label={`Select ${displayTableId(row.table, preferTableId)}`}
                      />
                    </td>
                  )}
                  <td className="break-all border-b border-line px-3 py-2 align-top font-bold text-teal">
                    {displayTableId(row.table, preferTableId)}
                  </td>
                  <td className="border-b border-line px-3 py-2 align-top">{row.table.title || '—'}</td>
                  {editEnabled && (
                    <td className="border-b border-line px-3 py-2 align-top">
                      <Combobox
                        options={moveOptions}
                        value=""
                        onChange={(target) => {
                          onMoveTables(
                            [tid],
                            target === 'unmatched' ? 'unmatched' : Number(target),
                          )
                        }}
                        placeholder="Choose group…"
                        ariaLabel={`Move ${displayTableId(row.table, preferTableId)} to group`}
                        disabled={moveOptions.length === 0}
                        menuMinWidth={480}
                      />
                    </td>
                  )}
                </tr>
              )
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <p className="m-0 px-3 py-6 text-center text-xs italic text-ink-soft">
            {emptyHint || 'No tables in this group'}
          </p>
        )}
      </div>
    </div>
  )
}

/**
 * Shared grouping UI for Excel / PDF / SQL (catalogue matchResult shape).
 *
 * Master–detail: searchable group list on the left, selected group tables on the right.
 */
export default function GroupingWorkspace({
  matchResult,
  onMatchResultChange,
  manualGrouping,
  onManualGroupingChange,
  editingGroups,
  onEditingGroupsChange,
  autoSnapshot,
  onRequestAutomatic,
  onContinueToMetadata,
  metadataFilling = false,
  loading = false,
  error = '',
  toast = null,
  onDismissToast,
  preferTableId = false,
  idColumnLabel = null,
  titleColumnLabel = 'Table Title',
  continueDisabled = false,
}) {
  const [activeDialog, setActiveDialog] = useState(null)
  const [selectedKey, setSelectedKey] = useState(null) // number index | 'unmatched'
  const [query, setQuery] = useState('')
  const [selectedIds, setSelectedIds] = useState(() => new Set())

  const groups = matchResult?.groups || []
  const unmatched = matchResult?.unmatched_tables || []
  const groupingMode = manualGrouping ? 'manual' : 'automatic'
  const editEnabled = manualGrouping || editingGroups
  const resolvedIdLabel = idColumnLabel || (preferTableId ? 'Table ID' : 'Dataset ID')
  const allTables = allTablesFromMatchResult(matchResult)
  const showUnmatched = editEnabled || unmatched.length > 0

  const filteredGroupIndexes = useMemo(() => {
    const q = query.trim().toLowerCase()
    return groups
      .map((g, i) => ({ g, i }))
      .filter(({ g }) => !q || groupSearchBlob(g).includes(q))
      .map(({ i }) => i)
  }, [groups, query])

  const unmatchedMatchesQuery = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return true
    return unmatched.some((u) => {
      const blob = [u?.table?.title || '', u?.table?.id || '', u?.table?.table_id || ''].join(' ').toLowerCase()
      return blob.includes(q) || 'unmatched'.includes(q)
    })
  }, [unmatched, query])

  const moveOptions = useMemo(() => {
    const opts = groups.map((g, i) => {
      const name = g.file_name || g.metadata?.title || g.name || `Group ${i + 1}`
      return {
        value: String(i),
        label: `${i + 1}. ${name}`,
      }
    })
    if (selectedKey === 'unmatched') {
      return opts
    }
    if (typeof selectedKey === 'number') {
      return [
        ...opts.filter((o) => Number(o.value) !== selectedKey),
        { value: 'unmatched', label: 'Unmatched tables' },
      ]
    }
    return opts
  }, [groups, selectedKey])

  // Keep selection valid as groups change / filters apply.
  useEffect(() => {
    if (selectedKey === 'unmatched') {
      if (showUnmatched && unmatchedMatchesQuery) return
      setSelectedKey(filteredGroupIndexes[0] ?? null)
      return
    }
    if (typeof selectedKey === 'number' && filteredGroupIndexes.includes(selectedKey)) return
    if (filteredGroupIndexes.length > 0) {
      setSelectedKey(filteredGroupIndexes[0])
      return
    }
    if (showUnmatched && unmatchedMatchesQuery) {
      setSelectedKey('unmatched')
      return
    }
    setSelectedKey(null)
  }, [filteredGroupIndexes, selectedKey, showUnmatched, unmatchedMatchesQuery])

  // Clear row checkboxes when switching groups or leaving edit mode.
  useEffect(() => {
    setSelectedIds(new Set())
  }, [selectedKey, editEnabled])

  const setMatch = (updater) => {
    onMatchResultChange(typeof updater === 'function' ? updater(matchResult) : updater)
  }

  const moveTables = (tableIds, target) => {
    if (!tableIds?.length) return
    let next = matchResult
    for (const tableId of tableIds) {
      next = moveMatchTable(next, tableId, target)
    }
    setMatch(next)
    setSelectedIds(new Set())
    if (target === 'unmatched' || typeof target === 'number') {
      setSelectedKey(target)
    }
  }

  const toggleSelected = (tid) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(tid)) next.delete(tid)
      else next.add(tid)
      return next
    })
  }

  const toggleAll = (ids, selectAll) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (selectAll) ids.forEach((id) => next.add(id))
      else ids.forEach((id) => next.delete(id))
      return next
    })
  }

  const requestManual = () => {
    if (manualGrouping) {
      setActiveDialog('addGroup')
      return
    }
    setActiveDialog('manualConfirm')
  }

  const startManual = () => {
    setMatch(startManualMatchGrouping(matchResult, allTables))
    onManualGroupingChange(true)
    onEditingGroupsChange(false)
    setActiveDialog('addGroup')
  }

  const requestAutomatic = () => {
    if (manualGrouping || editingGroups) {
      setActiveDialog('autoConfirm')
      return
    }
    onRequestAutomatic?.()
  }

  const finishEditing = () => {
    setMatch(finishEditingMatchGroups(matchResult))
    onEditingGroupsChange(false)
  }

  const activeGroup = typeof selectedKey === 'number' ? groups[selectedKey] : null
  const activeTables = selectedKey === 'unmatched'
    ? unmatched
    : (activeGroup?.matched_tables || [])

  const totalGrouped = groups.reduce((n, g) => n + (g.matched_tables || []).length, 0)

  if (!matchResult && !loading) {
    return <div className="py-10 text-center text-ink-soft">No tables to group.</div>
  }

  return (
    <div className="flex flex-col gap-4">
      {error && <ErrorBanner>{error}</ErrorBanner>}
      {loading ? (
        <div className="py-10 text-center text-ink-soft">Preparing grouping…</div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <div className="inline-flex rounded-full border border-line bg-white p-0.5">
              <button
                type="button"
                className={`dhara-tab rounded-full px-3.5 py-1.5 text-[13px] font-semibold ${
                  groupingMode === 'automatic'
                    ? 'border-transparent bg-teal-deep text-cream'
                    : 'border-transparent text-ink-soft hover:bg-sage hover:text-teal-deep'
                }`}
                onClick={() => groupingMode !== 'automatic' && requestAutomatic()}
                disabled={metadataFilling}
              >
                Automatic (recommended)
              </button>
              <button
                type="button"
                className={`dhara-tab rounded-full px-3.5 py-1.5 text-[13px] font-semibold ${
                  groupingMode === 'manual'
                    ? 'border-transparent bg-teal-deep text-cream'
                    : 'border-transparent text-ink-soft hover:bg-sage hover:text-teal-deep'
                }`}
                onClick={() => groupingMode !== 'manual' && requestManual()}
              >
                Manual
              </button>
            </div>
            {groupingMode === 'automatic' && (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => (editingGroups ? finishEditing() : onEditingGroupsChange(true))}
              >
                {editingGroups ? 'Done editing' : 'Edit groups'}
              </Button>
            )}
            <span className="ml-auto text-[13px] text-ink-soft">
              {groups.length} group{groups.length !== 1 ? 's' : ''} · {totalGrouped} table{totalGrouped !== 1 ? 's' : ''}
              {unmatched.length > 0 ? ` · ${unmatched.length} unmatched` : ''}
            </span>
          </div>

          {editEnabled && (
            <p className="m-0 text-[13px] font-medium text-[#c9610f]">
              <span className="inline-flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2} aria-hidden />
                Every table must be assigned to a group with a group name before you continue. Use + Add group for a new group, then Move to assign tables.
              </span>
            </p>
          )}

          {activeDialog === 'manualConfirm' && (
            <ConfirmDialog
              title="Switch to manual grouping?"
              body='The current grouping will be erased. You can get it back by pressing "Automatic grouping" again.'
              onCancel={() => setActiveDialog(null)}
              onContinue={() => {
                setActiveDialog(null)
                startManual()
              }}
            />
          )}
          {activeDialog === 'autoConfirm' && (
            <ConfirmDialog
              title="Switch to automatic grouping?"
              body="The current grouping will be erased and reverted to the automatic title-based grouping."
              onCancel={() => setActiveDialog(null)}
              onContinue={() => {
                setActiveDialog(null)
                onRequestAutomatic?.({ fromConfirm: true, autoSnapshot })
                onManualGroupingChange(false)
                onEditingGroupsChange(false)
              }}
            />
          )}

          <div className="relative">
            {/* Left list height tracks the right panel; scrolls on its own and does not inflate page height */}
            <aside className="mb-3 flex max-h-[min(420px,55vh)] w-full flex-col overflow-hidden rounded-[10px] border border-line bg-white lg:absolute lg:bottom-0 lg:left-0 lg:top-0 lg:mb-0 lg:w-[360px] lg:max-h-none">
              <div className="flex h-full min-h-0 flex-col overflow-hidden lg:sticky lg:top-4 lg:max-h-[calc(100vh-10rem)]">
                <div className="border-b border-line p-3">
                  <label className="flex items-center gap-2 rounded-lg border border-line bg-cream px-2.5 py-2 focus-within:border-teal focus-within:shadow-focus-ring">
                    <Search className="h-4 w-4 flex-none text-ink-soft" strokeWidth={2} aria-hidden />
                    <input
                      type="search"
                      value={query}
                      onChange={(e) => setQuery(e.target.value)}
                      placeholder="Search groups or tables…"
                      className="min-w-0 flex-1 bg-transparent text-[13.5px] text-ink placeholder:text-ink-soft focus:outline-none"
                      aria-label="Search groups or tables"
                    />
                    {query ? (
                      <button
                        type="button"
                        className="text-ink-soft hover:text-teal"
                        onClick={() => setQuery('')}
                        aria-label="Clear search"
                      >
                        <X className="h-3.5 w-3.5" strokeWidth={2} />
                      </button>
                    ) : null}
                  </label>
                  <div className="mt-2 flex items-center gap-2">
                    <div className="min-w-0 flex-1 text-[12px] text-ink-soft">
                      {filteredGroupIndexes.length} of {groups.length} group{groups.length !== 1 ? 's' : ''}
                      {query.trim() ? ' match' : ''}
                    </div>
                    {editEnabled && (
                      <Button variant="secondary" size="sm" onClick={() => setActiveDialog('addGroup')}>
                        + Add group
                      </Button>
                    )}
                  </div>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto p-1.5" role="listbox" aria-label="Groups">
                  {filteredGroupIndexes.length === 0 && !(showUnmatched && unmatchedMatchesQuery) ? (
                    <p className="m-0 px-3 py-8 text-center text-[13px] text-ink-soft">No groups match “{query.trim()}”.</p>
                  ) : null}

                  {filteredGroupIndexes.map((i) => {
                    const g = groups[i]
                    const count = (g.matched_tables || []).length
                    const selected = selectedKey === i
                    return (
                      <button
                        key={g.workbook_index ?? i}
                        type="button"
                        role="option"
                        aria-selected={selected}
                        className={`mb-1 flex w-full items-start gap-2 rounded-lg px-3 py-2.5 text-left transition-colors ${
                          selected
                            ? 'bg-teal-deep text-cream'
                            : 'text-ink hover:bg-cream'
                        }`}
                        onClick={() => setSelectedKey(i)}
                      >
                        <span className="min-w-0 flex-1">
                          <span className={`block truncate text-[13.5px] font-semibold leading-snug ${selected ? 'text-cream' : 'text-ink'}`}>
                            {g.file_name || 'Untitled group'}
                          </span>
                          <span className={`mt-0.5 block text-[11.5px] ${selected ? 'text-cream/75' : 'text-ink-soft'}`}>
                            Group {i + 1}
                          </span>
                        </span>
                        <span className={`mt-0.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                          selected ? 'bg-cream/20 text-cream' : 'bg-cream text-ink-soft'
                        }`}>
                          {count}
                        </span>
                      </button>
                    )
                  })}

                  {showUnmatched && unmatchedMatchesQuery && (
                    <button
                      type="button"
                      role="option"
                      aria-selected={selectedKey === 'unmatched'}
                      className={`mb-1 flex w-full items-start gap-2 rounded-lg px-3 py-2.5 text-left transition-colors ${
                        selectedKey === 'unmatched'
                          ? 'bg-[#a15c00] text-cream'
                          : 'bg-[#fffaf1] text-ink hover:bg-[#fff3d9]'
                      }`}
                      onClick={() => setSelectedKey('unmatched')}
                    >
                      <AlertTriangle className={`mt-0.5 h-4 w-4 flex-none ${selectedKey === 'unmatched' ? 'text-cream' : 'text-yellow'}`} strokeWidth={2} aria-hidden />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[13.5px] font-semibold">Unmatched tables</span>
                        <span className={`mt-0.5 block text-[11.5px] ${selectedKey === 'unmatched' ? 'text-cream/75' : 'text-ink-soft'}`}>
                          Not assigned to a group
                        </span>
                      </span>
                      <span className={`mt-0.5 whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                        selectedKey === 'unmatched' ? 'bg-cream/20 text-cream' : 'bg-cream text-ink-soft'
                      }`}>
                        {unmatched.length}
                      </span>
                    </button>
                  )}
                </div>
              </div>
            </aside>

            {/* Right panel sizes to its rows and drives overall page height */}
            <section className="flex min-w-0 flex-col rounded-[10px] border border-line bg-white lg:ml-[372px]">
              {selectedKey === null ? (
                <div className="px-6 py-10 text-center text-[14px] text-ink-soft">
                  Select a group to review its tables.
                </div>
              ) : selectedKey === 'unmatched' ? (
                <>
                  <div className="flex flex-wrap items-center gap-2 border-b border-[#f0d6a3] bg-[#fffaf1] px-4 py-3">
                    <AlertTriangle className="h-4 w-4 flex-none text-yellow" strokeWidth={2} aria-hidden />
                    <div className="min-w-0 flex-1">
                      <div className="text-[15px] font-semibold text-ink">Unmatched tables</div>
                      <div className="text-[12.5px] text-ink-soft">
                        {unmatched.length} table{unmatched.length !== 1 ? 's' : ''} not assigned
                        {editEnabled ? ' — use Move to to assign them' : ''}
                      </div>
                    </div>
                  </div>
                  <div className="p-3">
                    <TablesPanel
                      rows={activeTables}
                      editEnabled={editEnabled}
                      preferTableId={preferTableId}
                      resolvedIdLabel={resolvedIdLabel}
                      titleColumnLabel={titleColumnLabel}
                      emptyHint="No unmatched tables"
                      moveOptions={moveOptions}
                      selectedIds={selectedIds}
                      onToggleSelected={toggleSelected}
                      onToggleAll={toggleAll}
                      onMoveTables={moveTables}
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="flex flex-wrap items-center gap-2 border-b border-line px-4 py-3">
                    <div className="min-w-0 flex-1">
                      <div className="text-[12px] font-semibold uppercase tracking-wide text-ink-soft">
                        Group {selectedKey + 1}
                      </div>
                      <div className="mt-0.5 flex min-w-0 items-center gap-2">
                        <GroupNameEditor
                          name={activeGroup?.file_name}
                          onSave={(newName) => setMatch(renameMatchGroup(matchResult, selectedKey, newName))}
                        />
                      </div>
                    </div>
                    <span className="whitespace-nowrap rounded-full bg-cream px-2.5 py-0.5 text-xs text-ink-soft">
                      {(activeGroup?.matched_tables || []).length} table{(activeGroup?.matched_tables || []).length !== 1 ? 's' : ''}
                    </span>
                    {editEnabled && (
                      <button
                        type="button"
                        className="flex items-center justify-center rounded border border-line px-1.5 py-1 text-xs text-ink-soft transition-colors duration-200 hover:border-coral hover:bg-error-bg hover:text-coral"
                        onClick={() => {
                          setMatch(deleteMatchGroup(matchResult, selectedKey))
                          setSelectedKey(null)
                        }}
                        title="Delete group"
                        aria-label="Delete group"
                      >
                        <Trash2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                      </button>
                    )}
                  </div>
                  <div className="p-3">
                    <TablesPanel
                      rows={activeTables}
                      editEnabled={editEnabled}
                      preferTableId={preferTableId}
                      resolvedIdLabel={resolvedIdLabel}
                      titleColumnLabel={titleColumnLabel}
                      emptyHint="No tables in this group"
                      moveOptions={moveOptions}
                      selectedIds={selectedIds}
                      onToggleSelected={toggleSelected}
                      onToggleAll={toggleAll}
                      onMoveTables={moveTables}
                    />
                  </div>
                </>
              )}
            </section>
          </div>

          <div className="flex items-center gap-4">
            {editingGroups ? (
              <Button variant="primary" onClick={finishEditing}>Done editing</Button>
            ) : (
              <Button
                variant="primary"
                onClick={onContinueToMetadata}
                disabled={metadataFilling || continueDisabled}
                className="inline-flex items-center gap-1.5"
              >
                {metadataFilling && <span className="inline-block h-[13px] w-[13px] animate-spin rounded-full border-2 border-white/50 border-t-white" />}
                {metadataFilling ? 'Filling metadata…' : 'Continue to metadata'}
                {!metadataFilling && <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />}
              </Button>
            )}
          </div>
        </>
      )}

      {toast && (
        <Toast message={toast} tone="warn" onDismiss={onDismissToast} />
      )}
      {activeDialog === 'addGroup' && (
        <AddGroupModal
          tables={unmatched.map((u) => u.table)}
          allowEmpty={editEnabled}
          onCreate={(name, ids) => {
            const nextIndex = groups.length
            setMatch(createMatchGroup(matchResult, name, ids))
            setActiveDialog(null)
            setSelectedKey(nextIndex)
          }}
          onClose={() => setActiveDialog(null)}
        />
      )}
    </div>
  )
}
