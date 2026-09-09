'use client'

import { useEffect, useState } from 'react'
import KydsModal from './KydsModal'
import Button from './ui/Button'
import { withAuthHeaders } from '../lib/auth'
import { notifyKydsChanged, onKydsChanged } from '../lib/kydsEvents'

// Shows the caller's own KYDS entry (if any), with an edit option — editing
// re-saves to Postgres via the same /api/kyds endpoint used for the initial
// submission (see backend/catalogue.py save_kyds_entry / get_own_latest_kyds_entry).
// Lives in the Dataset Inventory stage regardless of which step within it
// (mode pick, preview, grouping) is showing, so it stays visible even after
// "Change files" or a stage-nav jump straight to the preview.
// `variant="corner"` renders a compact, top-right-corner form of this same
// widget -- a "Create KYDS" button when the caller skipped the initial form,
// or a small pill (name + Edit) once an entry exists -- for pages that show
// the KYDS state alongside their header instead of as a full-width card.
export default function KydsSummaryCard({ variant = 'card' }) {
  const [kydsEntry, setKydsEntry] = useState(null)
  const [kydsLoading, setKydsLoading] = useState(true)
  const [editingKyds, setEditingKyds] = useState(false)
  const [creatingKyds, setCreatingKyds] = useState(false)

  useEffect(() => {
    let cancelled = false
    const load = () => {
      fetch('/api/kyds/mine', withAuthHeaders())
        .then((r) => (r.ok ? r.json() : { entry: null }))
        .then((data) => {
          if (!cancelled) setKydsEntry(data.entry || null)
        })
        .catch(() => {
          if (!cancelled) setKydsEntry(null)
        })
        .finally(() => {
          if (!cancelled) setKydsLoading(false)
        })
    }
    load()
    const off = onKydsChanged(load)
    return () => {
      cancelled = true
      off()
    }
  }, [])

  const saveKydsEdit = async (form) => {
    const res = await fetch('/api/kyds', withAuthHeaders({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ responses: form }),
    }))
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || 'Could not save KYDS entry — please try again.')
    }
    const data = await res.json()
    setKydsEntry({ id: data.id, responses: form })
    setEditingKyds(false)
    setCreatingKyds(false)
    notifyKydsChanged()
  }

  if (kydsLoading) return null

  if (!kydsEntry) {
    if (variant !== 'corner') return null
    return (
      <>
        <Button variant="secondary" size="sm" onClick={() => setCreatingKyds(true)}>
          + Create KYDS
        </Button>
        {creatingKyds && (
          <KydsModal
            onSkip={() => setCreatingKyds(false)}
            onSave={saveKydsEdit}
          />
        )}
      </>
    )
  }

  if (variant === 'corner') {
    return (
      <>
        <div className="flex max-w-[280px] items-center gap-2 rounded-lg border border-line bg-white px-3 py-1.5">
          <div className="min-w-0 flex-1">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-[#8E9398]">KYDS</div>
            <div className="truncate text-[13px] font-semibold text-ink">
              {kydsEntry.responses?.datasetName?.trim() || 'Untitled dataset'}
            </div>
          </div>
          <Button variant="secondary" size="sm" onClick={() => setEditingKyds(true)}>
            Edit
          </Button>
        </div>
        {editingKyds && (
          <KydsModal
            editing
            initialForm={kydsEntry?.responses}
            onSkip={() => setEditingKyds(false)}
            onSave={saveKydsEdit}
          />
        )}
      </>
    )
  }

  return (
    <>
      <div className="flex items-center justify-between gap-4 rounded-lg border border-line bg-white px-4 py-3">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs uppercase tracking-wide text-[#8E9398]">Know Your Dataset</span>
          <span className="text-[15px] font-semibold text-ink">{kydsEntry.responses?.datasetName?.trim() || 'Untitled dataset'}</span>
        </div>
        <Button variant="secondary" size="sm" onClick={() => setEditingKyds(true)}>
          Edit
        </Button>
      </div>

      {editingKyds && (
        <KydsModal
          editing
          initialForm={kydsEntry?.responses}
          onSkip={() => setEditingKyds(false)}
          onSave={saveKydsEdit}
        />
      )}
    </>
  )
}
