import { useEffect, useState } from 'react'
import KydsModal from './KydsModal'
import { withAuthHeaders } from '../auth'

// Shows the caller's own KYDS entry (if any), with an edit option — editing
// re-saves to Postgres via the same /api/kyds endpoint used for the initial
// submission (see backend/catalogue.py save_kyds_entry / get_own_latest_kyds_entry).
// Lives in the Dataset Inventory stage regardless of which step within it
// (mode pick, preview, grouping) is showing, so it stays visible even after
// "Change files" or a stage-nav jump straight to the preview.
export default function KydsSummaryCard() {
  const [kydsEntry, setKydsEntry] = useState(null)
  const [kydsLoading, setKydsLoading] = useState(true)
  const [editingKyds, setEditingKyds] = useState(false)

  useEffect(() => {
    fetch('/api/kyds/mine', withAuthHeaders())
      .then((r) => (r.ok ? r.json() : { entry: null }))
      .then((data) => setKydsEntry(data.entry || null))
      .catch(() => setKydsEntry(null))
      .finally(() => setKydsLoading(false))
  }, [])

  const saveKydsEdit = async (form) => {
    try {
      const res = await fetch('/api/kyds', withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ responses: form }),
      }))
      if (res.ok) {
        const data = await res.json()
        setKydsEntry({ id: data.id, responses: form })
      }
    } finally {
      setEditingKyds(false)
    }
  }

  if (kydsLoading || !kydsEntry) return null

  return (
    <>
      <div className="kyds-summary-card">
        <div className="kyds-summary-text">
          <span className="kyds-summary-label">Know Your Dataset</span>
          <span className="kyds-summary-name">{kydsEntry.responses?.datasetName?.trim() || 'Untitled dataset'}</span>
        </div>
        <button type="button" className="console-secondary-btn" onClick={() => setEditingKyds(true)}>
          Edit
        </button>
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
