'use client'

import { useEffect, useState } from 'react'
import { useParams } from 'next/navigation'
import { Loader2 } from 'lucide-react'
import Button from '@/components/ui/Button'
import { TableDetail } from '@/components/pdf/TableDetail'
import { loadPersistedConsoleState } from '@/lib/consolePersist'
import {
  applyEditorEditsToConsoleTable,
  clearStashedConsoleTable,
  closeConsoleEditorWindow,
  loadStashedConsoleTable,
  notifyConsoleTableEdited,
  toEditorTable,
} from '@/lib/consoleTableEdit'

function findTableInConsoleState(uid) {
  const state = loadPersistedConsoleState()
  const mr = state?.matchResult
  if (!mr) return null
  for (const g of mr.groups || []) {
    for (const mt of g.matched_tables || []) {
      if (mt.table?._uid === uid) return mt.table
    }
  }
  for (const u of mr.unmatched_tables || []) {
    if (u.table?._uid === uid) return u.table
  }
  return null
}

export default function ConsoleTableEditRoutePage() {
  const { tableUid } = useParams()
  const uid = decodeURIComponent(String(tableUid || ''))
  const [table, setTable] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    try {
      const found = loadStashedConsoleTable(uid) || findTableInConsoleState(uid)
      if (!found) throw new Error('Table was not found in the current console session')
      if (!cancelled) setTable(found)
    } catch (e) {
      if (!cancelled) setError(e.message || 'Could not load table')
    } finally {
      if (!cancelled) setLoading(false)
    }
    return () => { cancelled = true }
  }, [uid])

  if (loading) {
    return (
      <div className="flex h-[100dvh] items-center justify-center bg-cream text-[14px] text-ink-soft">
        <Loader2 className="mr-2 h-5 w-5 animate-spin text-teal" strokeWidth={2} />
        Opening table editor…
      </div>
    )
  }

  if (error || !table) {
    return (
      <div className="flex h-[100dvh] flex-col items-center justify-center gap-3 bg-cream px-6 text-center">
        <div className="text-[15px] font-semibold text-ink">{error || 'Table not found'}</div>
        <Button variant="secondary" size="sm" onClick={closeConsoleEditorWindow}>Close tab</Button>
      </div>
    )
  }

  const editorTable = toEditorTable(table)

  const saveEdits = async (edits) => {
    const patched = applyEditorEditsToConsoleTable(table, edits)
    notifyConsoleTableEdited(uid, patched)
    clearStashedConsoleTable(uid)
  }

  return (
    <TableDetail
      table={editorTable}
      jobId={null}
      editorOnly
      onSave={saveEdits}
      editorCloseHref="/console"
      editorFooterHint="Saves back to the preview page, then closes this tab."
    />
  )
}
