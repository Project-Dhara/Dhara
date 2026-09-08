'use client'

import { useCallback, useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { AlertTriangle, ArrowLeft, ArrowRight, Pencil, X } from 'lucide-react'
import { withAuthHeaders } from '../lib/auth'
import { withLlmKeyHeaders } from '../lib/llmKey'
import PdfConsoleLayout from './PdfConsoleLayout'
import Button from './ui/Button'
import ErrorBanner from './ui/ErrorBanner'

function GroupNameEditor({ name, onSave }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(name)

  const startEdit = () => {
    setDraft(name)
    setEditing(true)
  }
  const commit = () => {
    const next = draft.trim()
    setEditing(false)
    if (next && next !== name) onSave(next)
  }

  if (editing) {
    return (
      <input
        className="min-w-0 flex-1 rounded border border-teal px-2 py-1 text-[14px] font-semibold text-ink outline-none"
        value={draft}
        autoFocus
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') commit()
          if (e.key === 'Escape') setEditing(false)
        }}
      />
    )
  }
  return (
    <span className="flex min-w-0 flex-1 items-center gap-1.5">
      <span className="truncate text-[14px] font-semibold text-ink">{name || 'Untitled group'}</span>
      <button type="button" className="flex h-6 w-6 items-center justify-center rounded text-ink-soft hover:bg-cream hover:text-teal" onClick={startEdit} title="Edit group name" aria-label="Edit group name">
        <Pencil className="h-3.5 w-3.5" strokeWidth={1.75} />
      </button>
    </span>
  )
}

function ConfirmDialog({ title, body, onCancel, onContinue }) {
  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4">
      <div className="flex max-w-md flex-col gap-3.5 rounded-xl bg-surface p-5 shadow-dhara">
        <div className="text-[16px] font-bold text-ink">{title}</div>
        <p className="m-0 text-[14px] leading-snug text-ink-soft">{body}</p>
        <div className="flex items-center justify-end gap-2.5">
          <Button variant="secondary" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" onClick={onContinue}>Continue</Button>
        </div>
      </div>
    </div>
  )
}

function AddGroupModal({ tables, onCreate, onClose }) {
  const [name, setName] = useState('')
  const [selected, setSelected] = useState(() => new Set())
  const toggle = (id) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  const canCreate = name.trim() && selected.size > 0
  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/35 p-4">
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col gap-3.5 overflow-hidden rounded-xl bg-surface p-5 shadow-dhara">
        <div className="text-[16px] font-bold text-ink">Add group manually</div>
        <label className="flex flex-col gap-1.5 text-[13px] text-ink-soft">
          Group name
          <input
            className="rounded-lg border border-line px-3 py-2 text-[14px] text-ink"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="e.g. Population by State"
          />
        </label>
        <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-line">
          {tables.map((t) => (
            <label
              key={t.id}
              className="flex cursor-pointer items-center gap-2.5 border-b border-cream px-3 py-2 text-[13px] last:border-b-0 hover:bg-cream"
            >
              <input type="checkbox" checked={selected.has(t.id)} onChange={() => toggle(t.id)} />
              <span className="font-semibold text-teal">{t.table_id}</span>
              <span className="truncate text-ink">{t.title || '—'}</span>
            </label>
          ))}
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
    </div>
  )
}

function toClientState(grouping) {
  const groups = (grouping.groups || []).map((g) => ({
    group_id: g.group_id,
    name: g.name,
    tables: g.tables || [],
  }))
  const unmatched = grouping.unmatched_tables || []
  return { groups, unmatched, method: grouping.method }
}

export default function PdfGrouping({ jobId }) {
  const router = useRouter()
  const [filename, setFilename] = useState('')
  const [grouping, setGrouping] = useState({ groups: [], unmatched: [] })
  const [method, setMethod] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [manualGrouping, setManualGrouping] = useState(false)
  const [editingGroups, setEditingGroups] = useState(false)
  const [dragOverGroup, setDragOverGroup] = useState(null)
  const [activeDialog, setActiveDialog] = useState(null)
  const [autoSnapshot, setAutoSnapshot] = useState(null)
  const [toast, setToast] = useState(null)

  const groups = grouping.groups
  const unmatched = grouping.unmatched
  const groupingMode = manualGrouping ? 'manual' : 'automatic'
  const dragEnabled = manualGrouping || editingGroups

  const applyGrouping = useCallback((data) => {
    const next = toClientState(data)
    setGrouping({ groups: next.groups, unmatched: next.unmatched })
    if (next.method) setMethod(next.method)
    if (data.filename) setFilename(data.filename)
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      setLoading(true)
      setError('')
      try {
        const res = await fetch(`/api/pdf/jobs/${jobId}/grouping`, withAuthHeaders())
        if (res.status === 409) {
          // Not persisted yet — run persist-approved then reload
          const persistRes = await fetch(
            `/api/pdf/jobs/${jobId}/persist-approved`,
            withLlmKeyHeaders(withAuthHeaders({ method: 'POST' })),
          )
          if (!persistRes.ok) {
            const body = await persistRes.json().catch(() => ({}))
            throw new Error(body.detail || 'Could not persist tables for grouping')
          }
          const persisted = await persistRes.json()
          if (cancelled) return
          applyGrouping(persisted.grouping || persisted)
          setAutoSnapshot(toClientState(persisted.grouping || persisted))
          setToast('Tables saved to Postgres and grouped by similarity.')
          return
        }
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || 'Could not load grouping')
        }
        const data = await res.json()
        if (cancelled) return
        applyGrouping(data)
        setAutoSnapshot(toClientState(data))
      } catch (e) {
        if (!cancelled) setError(e.message || 'Failed to load grouping')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [jobId, applyGrouping])

  useEffect(() => {
    if (!toast) return undefined
    const t = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(t)
  }, [toast])

  const renameGroup = (index, newName) => {
    setGrouping((prev) => ({
      ...prev,
      groups: prev.groups.map((g, i) => (i === index ? { ...g, name: newName } : g)),
    }))
  }

  const deleteGroup = (index) => {
    setGrouping((prev) => {
      const removed = prev.groups[index]
      return {
        groups: prev.groups.filter((_, i) => i !== index),
        unmatched: [...prev.unmatched, ...(removed.tables || [])],
      }
    })
  }

  const moveTable = (tablePk, dest) => {
    setGrouping((prev) => {
      let moved = null
      const nextGroups = prev.groups.map((g) => {
        const keep = []
        for (const t of g.tables || []) {
          if (t.id === tablePk) moved = t
          else keep.push(t)
        }
        return { ...g, tables: keep }
      })
      let nextUnmatched = prev.unmatched
      if (!moved) {
        const idx = nextUnmatched.findIndex((t) => t.id === tablePk)
        if (idx === -1) return prev
        moved = nextUnmatched[idx]
        nextUnmatched = nextUnmatched.filter((_, i) => i !== idx)
      } else {
        nextUnmatched = nextUnmatched.filter((t) => t.id !== tablePk)
      }
      if (dest === 'unmatched') {
        return { groups: nextGroups, unmatched: [...nextUnmatched, moved] }
      }
      const copy = [...nextGroups]
      if (dest < 0 || dest >= copy.length) return prev
      copy[dest] = { ...copy[dest], tables: [...(copy[dest].tables || []), moved] }
      return { groups: copy, unmatched: nextUnmatched }
    })
  }

  const finishEditing = () => {
    setGrouping((prev) => ({
      ...prev,
      groups: prev.groups.filter((g) => (g.tables || []).length > 0),
    }))
    setEditingGroups(false)
  }

  const createGroup = (name, tablePks) => {
    const idSet = new Set(tablePks)
    setGrouping((prev) => {
      const pulled = []
      const nextGroups = prev.groups
        .map((g) => {
          const keep = []
          for (const t of g.tables || []) {
            if (idSet.has(t.id)) pulled.push(t)
            else keep.push(t)
          }
          return { ...g, tables: keep }
        })
        .filter((g) => g.tables.length > 0)
      const nextUnmatched = []
      for (const t of prev.unmatched) {
        if (idSet.has(t.id)) pulled.push(t)
        else nextUnmatched.push(t)
      }
      return {
        groups: [...nextGroups, { name, tables: pulled }],
        unmatched: nextUnmatched,
      }
    })
    setActiveDialog(null)
  }

  const startManual = () => {
    setGrouping((prev) => ({
      groups: [],
      unmatched: [...prev.groups.flatMap((g) => g.tables || []), ...prev.unmatched],
    }))
    setManualGrouping(true)
    setEditingGroups(false)
    setActiveDialog('addGroup')
  }

  const requestAutomatic = async () => {
    if (manualGrouping || editingGroups) {
      setActiveDialog('autoConfirm')
      return
    }
    await runPropose(false)
  }

  const runPropose = async (reindex) => {
    setSaving(true)
    setError('')
    try {
      const res = await fetch(
        `/api/pdf/jobs/${jobId}/grouping/propose`,
        withLlmKeyHeaders(
          withAuthHeaders({
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ reindex }),
          }),
        ),
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || 'Could not propose groups')
      }
      const data = await res.json()
      applyGrouping(data)
      setAutoSnapshot(toClientState(data))
      setManualGrouping(false)
      setEditingGroups(false)
      setToast(`Automatic grouping updated (${data.method || 'pgvector'}).`)
    } catch (e) {
      setError(e.message || 'Propose failed')
    } finally {
      setSaving(false)
    }
  }

  const revertAutomatic = () => {
    if (autoSnapshot) {
      setGrouping({ groups: autoSnapshot.groups, unmatched: autoSnapshot.unmatched })
    }
    setManualGrouping(false)
    setEditingGroups(false)
    setActiveDialog(null)
  }

  const saveAndContinue = async () => {
    if (unmatched.length > 0) {
      setToast('Assign every table to a group before continuing.')
      return
    }
    if (groups.length === 0) {
      setToast('Create at least one group before continuing.')
      return
    }
    setSaving(true)
    setError('')
    try {
      const res = await fetch(
        `/api/pdf/jobs/${jobId}/grouping`,
        withAuthHeaders({
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            groups: groups.map((g) => ({
              name: g.name,
              table_pks: (g.tables || []).map((t) => t.id),
            })),
          }),
        }),
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || 'Could not save grouping')
      }
      setToast('Grouping saved. Metadata for PDF groups is coming next.')
    } catch (e) {
      setError(e.message || 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  const allTablesForModal = manualGrouping
    ? [...groups.flatMap((g) => g.tables || []), ...unmatched]
    : unmatched

  return (
    <PdfConsoleLayout jobId={jobId} step={3} maxStepReached={3}>
      <div className="flex flex-col gap-[18px]">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <button
              type="button"
              className="mb-3.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-teal hover:text-teal-dark"
              onClick={() => router.push(`/console/review/${jobId}`)}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              Back to preview
            </button>
            <div className="font-display text-[32px] font-medium leading-tight text-ink">Group tables</div>
            <div className="mt-1 text-[15px] text-ink-soft">
              Confirm which tables belong together — proposals use semantic similarity (pgvector).
            </div>
            <div className="mt-1.5 text-[13px] font-medium text-ink">
              {filename || 'PDF report'}
              <span className="font-normal text-ink-soft">
                {' '}
                · {groups.reduce((n, g) => n + (g.tables?.length || 0), 0) + unmatched.length} table(s)
                {method ? ` · ${method}` : ''}
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-col gap-5 rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
          {error && <ErrorBanner>{error}</ErrorBanner>}
          {loading ? (
            <div className="py-10 text-center text-ink-soft">Preparing grouping…</div>
          ) : (
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex rounded-full border border-line bg-white p-0.5">
                  <button
                    type="button"
                    className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${
                      groupingMode === 'automatic' ? 'bg-teal text-white' : 'text-ink-soft hover:text-ink'
                    }`}
                    onClick={() => groupingMode !== 'automatic' && requestAutomatic()}
                    disabled={saving}
                  >
                    Automatic (recommended)
                  </button>
                  <button
                    type="button"
                    className={`rounded-full px-3.5 py-1.5 text-[13px] font-semibold transition-colors ${
                      groupingMode === 'manual' ? 'bg-teal text-white' : 'text-ink-soft hover:text-ink'
                    }`}
                    onClick={() => groupingMode !== 'manual' && setActiveDialog('manualConfirm')}
                  >
                    Manual
                  </button>
                </div>
                {groupingMode === 'automatic' ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() => (editingGroups ? finishEditing() : setEditingGroups(true))}
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
                  body="The current grouping will be erased and reverted to the automatic similarity grouping."
                  onCancel={() => setActiveDialog(null)}
                  onContinue={() => {
                    setActiveDialog(null)
                    if (autoSnapshot) revertAutomatic()
                    else runPropose(false)
                  }}
                />
              )}

              <div className={`flex flex-col gap-3 rounded-xl p-1 ${dragEnabled ? 'ring-2 ring-dashed ring-teal/40' : ''}`}>
                {groups.map((g, i) => (
                  <div
                    key={g.group_id || `g-${i}`}
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
                            const pk = e.dataTransfer.getData('text/plain')
                            if (pk) moveTable(pk, i)
                            setDragOverGroup(null)
                          }
                        : undefined
                    }
                  >
                    <div className="flex items-center justify-between gap-2.5">
                      <span className="text-xs font-semibold uppercase tracking-wide text-ink-soft">
                        Group name:
                      </span>
                      <GroupNameEditor name={g.name} onSave={(n) => renameGroup(i, n)} />
                      <span className="whitespace-nowrap rounded-full bg-cream px-2.5 py-0.5 text-xs text-ink-soft">
                        {(g.tables || []).length} table{(g.tables || []).length !== 1 ? 's' : ''}
                      </span>
                      {dragEnabled && (
                        <button
                          type="button"
                          className="rounded border border-line px-1.5 py-1 text-xs text-ink-soft hover:border-coral hover:bg-[#fdecec] hover:text-coral"
                          onClick={() => deleteGroup(i)}
                          title="Delete group"
                        >
                          🗑
                        </button>
                      )}
                    </div>
                    <table className="w-full border-collapse text-[13px]">
                      <thead>
                        <tr>
                          <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">
                            Table ID
                          </th>
                          <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">
                            Title
                          </th>
                          <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">
                            Subject
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {(g.tables || []).map((t) => (
                          <tr
                            key={t.id}
                            draggable={dragEnabled}
                            onDragStart={
                              dragEnabled
                                ? (e) => e.dataTransfer.setData('text/plain', t.id)
                                : undefined
                            }
                            className={dragEnabled ? 'cursor-grab hover:bg-cream' : undefined}
                          >
                            <td className="border-b border-line py-1.5 font-bold text-teal">{t.table_id}</td>
                            <td className="border-b border-line py-1.5">{t.title || '—'}</td>
                            <td className="border-b border-line py-1.5 text-ink-soft">{t.subject || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {dragEnabled && (g.tables || []).length === 0 && (
                      <p className="m-0 text-xs italic text-ink-soft">Drag tables here</p>
                    )}
                  </div>
                ))}

                {(dragEnabled || unmatched.length > 0) && (
                  <div
                    className={`flex flex-col gap-1.5 rounded-[10px] border p-4 ${
                      dragEnabled && dragOverGroup === 'unmatched'
                        ? 'border-teal bg-[#f2f8f7]'
                        : 'border-[#f3c98b] bg-[#fffaf1]'
                    }`}
                    onDragOver={
                      dragEnabled
                        ? (e) => {
                            e.preventDefault()
                            setDragOverGroup('unmatched')
                          }
                        : undefined
                    }
                    onDragLeave={
                      dragEnabled
                        ? () => setDragOverGroup((d) => (d === 'unmatched' ? null : d))
                        : undefined
                    }
                    onDrop={
                      dragEnabled
                        ? (e) => {
                            e.preventDefault()
                            const pk = e.dataTransfer.getData('text/plain')
                            if (pk) moveTable(pk, 'unmatched')
                            setDragOverGroup(null)
                          }
                        : undefined
                    }
                  >
                    <div className="flex items-center justify-between gap-2.5">
                      <span className="inline-flex items-center gap-1.5 text-sm font-semibold text-ink">
                        <AlertTriangle className="h-4 w-4 text-[#c9610f]" strokeWidth={2} aria-hidden />
                        Unmatched tables
                      </span>
                      <span className="whitespace-nowrap rounded-full bg-cream px-2.5 py-0.5 text-xs text-ink-soft">
                        {unmatched.length}
                      </span>
                    </div>
                    {dragEnabled && (
                      <p className="m-0 text-xs italic text-ink-soft">
                        Drag tables here to unassign, or onto a group above to assign
                      </p>
                    )}
                    <table className="w-full border-collapse text-[13px]">
                      <thead>
                        <tr>
                          <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">
                            Table ID
                          </th>
                          <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">
                            Title
                          </th>
                          <th className="border-b border-line py-1.5 text-left text-xs uppercase text-ink-soft">
                            Subject
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {unmatched.map((t) => (
                          <tr
                            key={t.id}
                            draggable={dragEnabled}
                            onDragStart={
                              dragEnabled
                                ? (e) => e.dataTransfer.setData('text/plain', t.id)
                                : undefined
                            }
                            className={dragEnabled ? 'cursor-grab hover:bg-cream' : undefined}
                          >
                            <td className="border-b border-line py-1.5 font-bold text-teal">{t.table_id}</td>
                            <td className="border-b border-line py-1.5">{t.title || '—'}</td>
                            <td className="border-b border-line py-1.5 text-ink-soft">{t.subject || '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-4">
                {editingGroups ? (
                  <Button variant="primary" onClick={finishEditing}>
                    Done editing
                  </Button>
                ) : (
                  <Button variant="primary" disabled={saving} onClick={saveAndContinue} className="inline-flex items-center gap-1.5">
                    {saving ? 'Saving…' : (
                      <>
                        Save grouping
                        <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
                      </>
                    )}
                  </Button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {toast && (
        <div
          className="fixed right-6 top-6 z-[1200] flex animate-toast-in items-center gap-3 rounded-[10px] border border-[#c9610f] bg-[#e2711d] px-4 py-3 font-sans text-sm font-medium text-[#111] shadow-[0_8px_24px_rgba(226,113,29,0.22)]"
          role="alert"
        >
          <span>{toast}</span>
          <button
            type="button"
            className="flex h-6 w-6 items-center justify-center rounded p-0.5 opacity-70 hover:opacity-100"
            onClick={() => setToast(null)}
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" strokeWidth={1.75} />
          </button>
        </div>
      )}

      {activeDialog === 'addGroup' && (
        <AddGroupModal
          tables={allTablesForModal}
          onCreate={createGroup}
          onClose={() => setActiveDialog(null)}
        />
      )}
    </PdfConsoleLayout>
  )
}
