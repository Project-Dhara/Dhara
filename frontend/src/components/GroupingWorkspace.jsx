'use client'

import { useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, ArrowRight, Check, Pencil, Trash2, X } from 'lucide-react'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'
import Toast from './ui/Toast'
import {
  allTablesFromMatchResult,
  createMatchGroup,
  deleteMatchGroup,
  finishEditingMatchGroups,
  moveMatchTable,
  renameMatchGroup,
  startManualMatchGrouping,
} from '../lib/postPreview'

function GroupNameEditor({ name, onSave }) {
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

function AddGroupModal({ tables, onCreate, onClose, idField = 'id' }) {
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
  const canCreate = name.trim() && selected.size > 0
  if (typeof document === 'undefined') return null
  return createPortal(
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4" role="dialog" aria-modal="true">
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col gap-3.5 overflow-hidden rounded-xl bg-surface p-5 shadow-dhara">
        <div className="text-[16px] font-bold text-ink">Add group manually</div>
        <label className="flex flex-col gap-1.5 text-[13px] text-ink-soft">
          <span>Group name</span>
          <input
            className="rounded-lg border border-line px-3 py-2 font-body text-[14px] text-ink"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Population by State"
          />
        </label>
        <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-line">
          {tables.map((t) => {
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
          })}
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

/**
 * Shared grouping UI for Excel / PDF / SQL (catalogue matchResult shape).
 *
 * Grouping rules come from the backend (PDF title/SDG propose for all formats).
 * This component only edits membership / names and continues to metadata.
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
  const [dragOverGroup, setDragOverGroup] = useState(null)

  const groups = matchResult?.groups || []
  const unmatched = matchResult?.unmatched_tables || []
  const groupingMode = manualGrouping ? 'manual' : 'automatic'
  const dragEnabled = manualGrouping || editingGroups
  const resolvedIdLabel = idColumnLabel || (preferTableId ? 'Table ID' : 'Dataset ID')
  const allTables = allTablesFromMatchResult(matchResult)

  const setMatch = (updater) => {
    onMatchResultChange(typeof updater === 'function' ? updater(matchResult) : updater)
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
            {groupingMode === 'automatic' ? (
              <Button
                variant="secondary"
                size="sm"
                onClick={() => (editingGroups ? finishEditing() : onEditingGroupsChange(true))}
              >
                {editingGroups ? 'Done editing' : 'Edit groups'}
              </Button>
            ) : (
              <Button variant="secondary" size="sm" onClick={() => setActiveDialog('addGroup')}>
                + Add another group
              </Button>
            )}
          </div>

          {dragEnabled && (
            <p className="m-0 text-[13px] font-medium text-[#c9610f]">
              <span className="inline-flex items-start gap-1.5">
                <AlertTriangle className="mt-0.5 h-4 w-4 flex-none" strokeWidth={2} aria-hidden />
                Every table must be assigned to a group with a group name before you continue.
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

          <div className={`flex flex-col gap-3 rounded-xl p-1 ${dragEnabled ? 'ring-2 ring-dashed ring-teal/40' : ''}`}>
            {groups.map((g, i) => (
              <div
                key={g.workbook_index ?? i}
                className={`flex flex-col gap-1.5 rounded-[10px] border bg-white p-4 transition-colors ${
                  dragEnabled && dragOverGroup === i ? 'border-teal bg-[#f2f8f7]' : 'border-line'
                }`}
                onDragOver={
                  dragEnabled
                    ? (e) => {
                        e.preventDefault()
                        setDragOverGroup(i)
                      }
                    : undefined
                }
                onDragLeave={
                  dragEnabled ? () => setDragOverGroup((d) => (d === i ? null : d)) : undefined
                }
                onDrop={
                  dragEnabled
                    ? (e) => {
                        e.preventDefault()
                        const tableId = e.dataTransfer.getData('text/plain')
                        if (tableId) setMatch(moveMatchTable(matchResult, tableId, i))
                        setDragOverGroup(null)
                      }
                    : undefined
                }
              >
                <div className="flex items-center justify-between gap-2.5">
                  <span className="text-xs font-semibold uppercase tracking-wide text-ink-soft">Group name:</span>
                  <GroupNameEditor
                    name={g.file_name}
                    onSave={(newName) => setMatch(renameMatchGroup(matchResult, i, newName))}
                  />
                  <span className="whitespace-nowrap rounded-full bg-cream px-2.5 py-0.5 text-xs text-ink-soft">
                    {(g.matched_tables || []).length} table{(g.matched_tables || []).length !== 1 ? 's' : ''}
                  </span>
                  {dragEnabled && (
                    <button
                      type="button"
                      className="flex items-center justify-center rounded border border-line px-1.5 py-1 text-xs text-ink-soft transition-colors duration-200 hover:border-coral hover:bg-error-bg hover:text-coral"
                      onClick={() => setMatch(deleteMatchGroup(matchResult, i))}
                      title="Delete group"
                      aria-label="Delete group"
                    >
                      <Trash2 className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                    </button>
                  )}
                </div>
                <table className="w-full table-fixed border-collapse text-[13px]">
                  <thead>
                    <tr>
                      <th className="w-1/2 border-b border-line py-1.5 pr-3 text-left text-xs uppercase text-ink-soft">{resolvedIdLabel}</th>
                      <th className="w-1/2 border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">{titleColumnLabel}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(g.matched_tables || []).map((mt) => {
                      const tid = tableRowId(mt.table)
                      return (
                        <tr
                          key={tid}
                          draggable={dragEnabled}
                          onDragStart={dragEnabled ? (e) => { e.dataTransfer.setData('text/plain', tid) } : undefined}
                          className={dragEnabled ? 'cursor-grab hover:bg-cream' : undefined}
                        >
                          <td className="w-1/2 break-all border-b border-line py-1.5 pr-3 align-top font-bold text-teal">
                            {displayTableId(mt.table, preferTableId)}
                          </td>
                          <td className="w-1/2 border-b border-line py-1.5 align-top">{mt.table.title || '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
                {dragEnabled && (g.matched_tables || []).length === 0 && (
                  <p className="m-0 text-xs italic text-ink-soft">Drag tables here</p>
                )}
              </div>
            ))}

            {(dragEnabled || unmatched.length > 0) && (
              <div
                className={`flex flex-col gap-1.5 rounded-[10px] border p-4 ${
                  dragEnabled && dragOverGroup === 'unmatched' ? 'border-teal bg-[#f2f8f7]' : 'border-[#f3c98b] bg-[#fffaf1]'
                }`}
                onDragOver={dragEnabled ? (e) => { e.preventDefault(); setDragOverGroup('unmatched') } : undefined}
                onDragLeave={dragEnabled ? () => setDragOverGroup((d) => (d === 'unmatched' ? null : d)) : undefined}
                onDrop={
                  dragEnabled
                    ? (e) => {
                        e.preventDefault()
                        const tableId = e.dataTransfer.getData('text/plain')
                        if (tableId) setMatch(moveMatchTable(matchResult, tableId, 'unmatched'))
                        setDragOverGroup(null)
                      }
                    : undefined
                }
              >
                <div className="flex items-center justify-between gap-2.5">
                  <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink">
                    <AlertTriangle className="h-4 w-4 text-yellow" strokeWidth={2} aria-hidden />
                    Unmatched tables
                  </span>
                  <span className="whitespace-nowrap rounded-full bg-cream px-2.5 py-0.5 text-xs text-ink-soft">{unmatched.length}</span>
                </div>
                {dragEnabled && (
                  <p className="m-0 text-xs italic text-ink-soft">Drag tables here to unassign, or onto a group above to assign</p>
                )}
                <table className="w-full table-fixed border-collapse text-[13px]">
                  <thead>
                    <tr>
                      <th className="w-1/2 border-b border-line py-1.5 pr-3 text-left text-xs uppercase text-ink-soft">{resolvedIdLabel}</th>
                      <th className="w-1/2 border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">{titleColumnLabel}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unmatched.map((u) => {
                      const tid = tableRowId(u.table)
                      return (
                        <tr
                          key={tid}
                          draggable={dragEnabled}
                          onDragStart={dragEnabled ? (e) => { e.dataTransfer.setData('text/plain', tid) } : undefined}
                          className={dragEnabled ? 'cursor-grab hover:bg-cream' : undefined}
                        >
                          <td className="w-1/2 break-all border-b border-line py-1.5 pr-3 align-top font-bold text-teal">
                            {displayTableId(u.table, preferTableId)}
                          </td>
                          <td className="w-1/2 border-b border-line py-1.5 align-top">{u.table.title || '—'}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
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
          tables={manualGrouping ? allTables : unmatched.map((u) => u.table)}
          onCreate={(name, ids) => {
            setMatch(createMatchGroup(matchResult, name, ids))
            setActiveDialog(null)
          }}
          onClose={() => setActiveDialog(null)}
        />
      )}
    </div>
  )
}
