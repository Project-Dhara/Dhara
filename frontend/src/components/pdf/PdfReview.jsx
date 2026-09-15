'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ArrowRight, Check, Download, Loader2 } from 'lucide-react'
import { withAuthHeaders } from '../../lib/auth'
import { withLlmKeyHeaders } from '../../lib/llmKey'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import ErrorBanner from '../ui/ErrorBanner'
import KydsSummaryCard from '../KydsSummaryCard'
import PdfConsoleLayout from './PdfConsoleLayout'
import ProcessingStepper from '../console/ProcessingStepper'
import {
  PRIMARY_FILTERS,
  REASON_FILTER_IDS,
  REASON_LABELS,
  closeEditorWindow,
  collectReviewReasons,
  isAiClassified,
  matchesStatusFilter,
  tableHeaderKey,
} from '../../lib/pdfReviewHelpers'
import { DeleteConfirmDialog, MergeConfirmDialog, ScrollToTopButton, TableExpandPanel } from './PdfReviewAtoms'
import { TableDetail, TableTitleDisplay } from './TableDetail'

export function PdfTableEditorPage({ jobId, tableId }) {
  const [table, setTable] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError('')
    fetch(`/api/pdf/jobs/${encodeURIComponent(jobId)}/result`, withAuthHeaders())
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || 'Could not load table')
        }
        return res.json()
      })
      .then((data) => {
        if (cancelled) return
        const found = (data.tables || []).find((t) => String(t.table_id) === String(tableId))
        if (!found) throw new Error(`Table ${tableId} was not found in this job`)
        setTable(found)
      })
      .catch((e) => {
        if (!cancelled) setError(e.message || 'Could not load table')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => { cancelled = true }
  }, [jobId, tableId])

  const saveEdits = async (edits) => {
    const res = await fetch(`/api/pdf/jobs/${encodeURIComponent(jobId)}/tables/${encodeURIComponent(tableId)}`, withAuthHeaders({
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(edits),
    }))
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || 'Could not save table edits')
    }
  }

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
        <Button variant="secondary" size="sm" onClick={() => closeEditorWindow(jobId)}>Close tab</Button>
      </div>
    )
  }

  return (
    <TableDetail
      table={table}
      jobId={jobId}
      editorOnly
      onSave={saveEdits}
    />
  )
}

export default function PdfReview({ jobId, filename, onDone }) {
  const [tables, setTables] = useState(null)
  const [error, setError] = useState('')
  const [expanded, setExpanded] = useState(null)
  const [reviewedIds, setReviewedIds] = useState(() => new Set())
  const [statusFilter, setStatusFilter] = useState('all')
  const [tablePage, setTablePage] = useState(0)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  // null | 'delete' | 'download' | 'merge' — same checkbox UI, different confirm action
  const [selectMode, setSelectMode] = useState(null)
  const [pendingDeleteIds, setPendingDeleteIds] = useState(null)
  const [pendingMergeIds, setPendingMergeIds] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [merging, setMerging] = useState(false)
  const [continuing, setContinuing] = useState(false)
  // 'persist' | 'group' — drives the Continue placeholder stepper
  const [continuePhase, setContinuePhase] = useState('persist')
  const [downloadingZip, setDownloadingZip] = useState(false)
  const [downloadingId, setDownloadingId] = useState(null)
  const rootRef = useRef(null)
  const router = useRouter()

  const triggerBlobDownload = async (url, fallbackName, init = {}) => {
    const res = await fetch(url, withAuthHeaders(init))
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(typeof body.detail === 'string' ? body.detail : 'Download failed')
    }
    const blob = await res.blob()
    const cd = res.headers.get('Content-Disposition') || ''
    const match = /filename="?([^";]+)"?/i.exec(cd)
    const name = match?.[1] || fallbackName
    const objectUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objectUrl
    a.download = name
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(objectUrl)
  }

  const downloadZip = async (tableIds = null) => {
    setDownloadingZip(true)
    setError('')
    try {
      const fallback = `${(filename || 'tables').replace(/\.[^.]+$/, '')}_tables.zip`
      if (tableIds?.length) {
        await triggerBlobDownload(
          `/api/pdf/jobs/${jobId}/tables/download-zip`,
          fallback,
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ table_ids: tableIds }),
          },
        )
      } else {
        await triggerBlobDownload(`/api/pdf/jobs/${jobId}/tables/download-zip`, fallback)
      }
      if (selectMode === 'download') exitSelectMode()
    } catch (e) {
      setError(e.message || 'Could not download ZIP')
    } finally {
      setDownloadingZip(false)
    }
  }

  const downloadOneTable = async (tableId, title) => {
    setDownloadingId(tableId)
    setError('')
    try {
      const safe = (title || `table_${tableId}`).replace(/[/\\?%*:|"<>]/g, '_').slice(0, 80)
      await triggerBlobDownload(
        `/api/pdf/jobs/${jobId}/tables/${encodeURIComponent(tableId)}/download`,
        `${safe}.xlsx`,
      )
    } catch (e) {
      setError(e.message || 'Could not download table')
    } finally {
      setDownloadingId(null)
    }
  }

  const continueToGrouping = async () => {
    setContinuing(true)
    setContinuePhase('persist')
    setError('')
    // Advance the stepper while the single persist+propose request runs.
    const phaseTimer = setTimeout(() => setContinuePhase('group'), 900)
    try {
      // Drop stale grouping UI from a previous Continue so the new propose wins.
      try {
        sessionStorage.removeItem(`dhara_pdf_pipeline_v1_${jobId}`)
      } catch {
        /* best-effort */
      }
      const res = await fetch(
        `/api/pdf/jobs/${jobId}/persist-approved`,
        withLlmKeyHeaders(withAuthHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // Preview state is source of truth for titles / reviews at Continue.
          body: JSON.stringify({
            tables: (tables || []).map((t) => ({
              table_id: t.table_id,
              title: t.title ?? null,
              rows: t.rows,
              columns: t.columns,
              classification: t.classification,
              human_review_needed: t.human_review_needed,
              human_review_reason: t.human_review_reason,
              semantic_status: t.semantic_status,
            })),
          }),
        })),
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not save tables for grouping')
      }
      clearTimeout(phaseTimer)
      setContinuePhase('group')
      router.push(`/console/grouping/${jobId}`)
    } catch (e) {
      clearTimeout(phaseTimer)
      setError(e.message || 'Could not continue to grouping')
      setContinuing(false)
      setContinuePhase('persist')
    }
  }

  useEffect(() => {
    let cancelled = false
    fetch(`/api/pdf/jobs/${jobId}/result`, withAuthHeaders())
      .then(async (res) => {
        if (!res.ok) {
          let detail = ''
          try {
            const body = await res.json()
            detail = body?.detail || ''
          } catch { /* ignore */ }
          if (res.status === 404) {
            throw new Error(detail || 'This extraction job is no longer available (server restarted). Please upload the PDF again.')
          }
          if (res.status === 409) {
            throw new Error(detail || 'Extraction is still running — wait for it to finish, then refresh.')
          }
          throw new Error(detail || 'Could not load results')
        }
        return res.json()
      })
      .then((data) => { if (!cancelled) setTables(data.tables) })
      .catch((e) => { if (!cancelled) setError(e.message) })
    return () => { cancelled = true }
  }, [jobId])

  // Sync when the full-page editor tab saves (BroadcastChannel + storage fallback).
  useEffect(() => {
    const apply = (payload) => {
      if (!payload || payload.jobId !== jobId) return
      const { tableId, edits } = payload
      if (!tableId || !edits) return
      setTables((prev) => prev.map((t) => (t.table_id === tableId ? { ...t, ...edits } : t)))
      setReviewedIds((prev) => new Set(prev).add(tableId))
    }
    let bc
    try {
      bc = new BroadcastChannel(TABLE_EDIT_CHANNEL)
      bc.onmessage = (ev) => {
        if (ev?.data?.type === 'table-edited') apply(ev.data)
      }
    } catch {
      bc = null
    }
    const onStorage = (ev) => {
      if (ev.key !== TABLE_EDIT_CHANNEL || !ev.newValue) return
      try {
        apply(JSON.parse(ev.newValue))
      } catch {
        /* ignore */
      }
    }
    const onFocus = () => {
      // Re-fetch so this tab stays fresh if BroadcastChannel was blocked.
      fetch(`/api/pdf/jobs/${jobId}/result`, withAuthHeaders())
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => { if (data?.tables) setTables(data.tables) })
        .catch(() => {})
    }
    window.addEventListener('storage', onStorage)
    window.addEventListener('focus', onFocus)
    return () => {
      bc?.close()
      window.removeEventListener('storage', onStorage)
      window.removeEventListener('focus', onFocus)
    }
  }, [jobId])

  const saveReview = async (tableId, edits) => {
    setTables((prev) => prev.map((t) => (t.table_id === tableId ? { ...t, ...edits } : t)))
    setReviewedIds((prev) => new Set(prev).add(tableId))
    try {
      await fetch(`/api/pdf/jobs/${jobId}/tables/${tableId}`, withAuthHeaders({
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(edits),
      }))
    } catch {
      // Local state already reflects the edit; a failed PATCH just means it
      // won't persist server-side if the page is reloaded -- non-fatal here.
    }
  }

  const confirmDelete = async () => {
    if (!pendingDeleteIds?.length) return
    setDeleting(true)
    const ids = [...pendingDeleteIds]
    try {
      const res = await fetch(`/api/pdf/jobs/${jobId}/tables/delete`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_ids: ids }),
      }))
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || 'Could not delete tables')
      }
      const idSet = new Set(ids)
      setTables((prev) => prev.filter((t) => !idSet.has(t.table_id)))
      setSelectedIds((prev) => {
        const next = new Set(prev)
        ids.forEach((id) => next.delete(id))
        return next
      })
      setReviewedIds((prev) => {
        const next = new Set(prev)
        ids.forEach((id) => next.delete(id))
        return next
      })
      if (expanded && idSet.has(expanded)) setExpanded(null)
      setPendingDeleteIds(null)
      setSelectedIds(new Set())
      setSelectMode(null)
    } catch (e) {
      setError(e.message || 'Could not delete tables')
      setPendingDeleteIds(null)
    } finally {
      setDeleting(false)
    }
  }

  const confirmMerge = async () => {
    if (!pendingMergeIds?.length || pendingMergeIds.length < 2) return
    setMerging(true)
    setError('')
    const ids = [...pendingMergeIds]
    try {
      const res = await fetch(`/api/pdf/jobs/${jobId}/tables/merge`, withAuthHeaders({
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ table_ids: ids }),
      }))
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : 'Could not merge tables')
      }
      const body = await res.json()
      const survivorId = body.survivor_table_id
      const removed = new Set(body.merged_table_ids || [])
      setTables((prev) => {
        const next = prev.filter((t) => !removed.has(t.table_id))
        if (body.table) {
          return next.map((t) => (t.table_id === survivorId ? { ...t, ...body.table } : t))
        }
        return next
      })
      setReviewedIds((prev) => {
        const next = new Set(prev)
        removed.forEach((id) => next.delete(id))
        return next
      })
      if (expanded && removed.has(expanded)) setExpanded(survivorId || null)
      setPendingMergeIds(null)
      setSelectedIds(new Set())
      setSelectMode(null)
    } catch (e) {
      setError(e.message || 'Could not merge tables')
      setPendingMergeIds(null)
    } finally {
      setMerging(false)
    }
  }

  const exitSelectMode = () => {
    setSelectMode(null)
    setSelectedIds(new Set())
  }

  const enterSelectMode = (mode) => {
    setSelectMode(mode)
    setSelectedIds(new Set())
    setExpanded(null)
    setTablePage(0)
  }

  if (error && !tables) {
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3}>
        <div className="flex flex-col gap-[18px]">
          <div className="flex flex-col">
            <button
              type="button"
              className="mb-3.5 inline-flex items-center gap-1.5 self-start text-[15px] font-semibold text-teal hover:text-teal-dark"
              onClick={onDone}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              Upload another PDF
            </button>
            <div className="font-display text-[26px] font-medium leading-tight text-ink">Review Extracted Tables</div>
            <div className="mt-1 text-[15px] text-ink-soft">Couldn’t load this extraction job.</div>
          </div>
          <div className="flex flex-col gap-3 rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
            <ErrorBanner>{error}</ErrorBanner>
            <Button variant="primary" className="self-start" onClick={onDone}>Upload PDF again</Button>
          </div>
        </div>
      </PdfConsoleLayout>
    )
  }
  if (!tables) {
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3}>
        <div className="flex flex-col gap-[18px]">
          <div className="flex flex-col">
            <div className="font-display text-[26px] font-medium leading-tight text-ink">Review Extracted Tables</div>
            <div className="mt-1 text-[15px] text-ink-soft">Loading results…</div>
          </div>
          <div className="rounded-xl border border-line bg-white p-5 py-10 text-center text-ink-soft shadow-sm sm:p-6">
            Loading results…
          </div>
        </div>
      </PdfConsoleLayout>
    )
  }

  if (continuing) {
    const persistDone = continuePhase === 'group'
    const continueSteps = [
      {
        key: 'persist',
        label: 'Saving approved tables',
        status: persistDone ? 'done' : 'active',
        message: persistDone ? undefined : 'Writing reviewed tables so grouping can use them…',
      },
      {
        key: 'group',
        label: 'Grouping similar tables',
        status: persistDone ? 'active' : 'pending',
        message: persistDone ? 'Building embeddings and proposing groups…' : undefined,
      },
    ]
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3}>
        <div className="mx-auto flex max-w-xl flex-col gap-8 py-8">
          <div>
            <div className="font-display text-xl font-medium text-ink">{filename || 'Preparing grouping'}</div>
            <div className="mt-1 text-sm text-ink-soft">
              Saving your tables and running grouping — this may take a moment.
            </div>
          </div>
          <ProcessingStepper steps={continueSteps} />
        </div>
      </PdfConsoleLayout>
    )
  }

  const filterCounts = {
    all: tables.length, needs_review: 0, no_review: 0, reviewed: 0,
    dev_ai_classified: 0, dev_auto_extracted: 0,
  }
  for (const key of Object.keys(REASON_LABELS)) filterCounts[key] = 0
  for (const t of tables) {
    const reviewed = reviewedIds.has(t.table_id)
    if (reviewed) filterCounts.reviewed += 1
    if (matchesStatusFilter(t, 'needs_review', reviewed)) filterCounts.needs_review += 1
    if (matchesStatusFilter(t, 'no_review', reviewed)) filterCounts.no_review += 1
    if (isAiClassified(t)) filterCounts.dev_ai_classified += 1
    else filterCounts.dev_auto_extracted += 1
    for (const reason of collectReviewReasons(t)) {
      if (filterCounts[reason] !== undefined) filterCounts[reason] += 1
    }
  }

  const primaryFilterOptions = [
    { id: 'all', label: 'All' },
    ...PRIMARY_FILTERS
      .filter((id) => (filterCounts[id] ?? 0) > 0)
      .map((id) => ({
        id,
        label: id === 'needs_review' ? 'Review needed' : 'No review needed',
      })),
    ...(filterCounts.reviewed > 0 ? [{ id: 'reviewed', label: 'Reviewed' }] : []),
    // DEV-ONLY: isolate tables that went through the OpenAI classification
    // step vs. the deterministic auto-accepted path, for QA'ing AI output.
    // Never shown in a production build.
    ...(process.env.NODE_ENV !== 'production' ? [
      { id: 'dev_ai_classified', label: 'Dev: AI classified' },
      { id: 'dev_auto_extracted', label: 'Dev: Auto-extracted' },
    ] : []),
  ]

  const reasonFilterOptions = REASON_FILTER_IDS
    .filter((id) => (filterCounts[id] ?? 0) > 0)
    .map((id) => ({ id, label: REASON_LABELS[id] }))

  const allFilterIds = new Set([
    ...primaryFilterOptions.map((o) => o.id),
    ...reasonFilterOptions.map((o) => o.id),
  ])
  // If the active filter no longer has matches (e.g. after deletes), fall back to All.
  const activeFilter = allFilterIds.has(statusFilter) ? statusFilter : 'all'
  const showReasonFilters = (
    activeFilter === 'needs_review' || REASON_FILTER_IDS.includes(activeFilter)
  ) && reasonFilterOptions.length > 0

  let filteredTables = tables.filter((t) =>
    matchesStatusFilter(t, activeFilter, reviewedIds.has(t.table_id))
  )
  // Merge mode: after the first selection, only show tables with the same headers.
  if (selectMode === 'merge' && selectedIds.size > 0) {
    const anchor = tables.find((t) => selectedIds.has(t.table_id))
    const key = anchor ? tableHeaderKey(anchor) : ''
    if (key) {
      filteredTables = filteredTables.filter((t) => tableHeaderKey(t) === key)
    }
  }
  const TABLES_PER_PAGE = 25
  const filteredCount = filteredTables.length
  const pageCount = Math.max(1, Math.ceil(filteredCount / TABLES_PER_PAGE) || 1)
  const currentPage = Math.min(Math.max(0, tablePage), pageCount - 1)
  const pageStart = currentPage * TABLES_PER_PAGE
  const pageTables = filteredTables.slice(pageStart, pageStart + TABLES_PER_PAGE)
  const pageEnd = filteredCount === 0 ? 0 : pageStart + pageTables.length
  const filteredIds = filteredTables.map((t) => t.table_id)
  const allFilteredSelected = filteredIds.length > 0 && filteredIds.every((id) => selectedIds.has(id))
  const selectedCount = selectedIds.size
  const canMerge = selectMode === 'merge' && selectedCount >= 2

  const toggleSelected = (tableId) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(tableId)) next.delete(tableId)
      else next.add(tableId)
      return next
    })
  }

  const toggleSelectAllFiltered = () => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (allFilteredSelected) filteredIds.forEach((id) => next.delete(id))
      else filteredIds.forEach((id) => next.add(id))
      return next
    })
  }

  const goPrevTablePage = () => {
    setExpanded(null)
    setTablePage((p) => Math.max(0, Math.min(p, pageCount - 1) - 1))
  }
  const goNextTablePage = () => {
    setExpanded(null)
    setTablePage((p) => Math.min(pageCount - 1, Math.min(p, pageCount - 1) + 1))
  }
  const tablesPaginationBar = filteredCount > 0 ? (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="text-[12.5px] text-ink-soft">
        Showing {pageStart + 1}–{pageEnd} of {filteredCount}
        {activeFilter !== 'all' ? ' (filtered)' : ''}
        {' · '}{TABLES_PER_PAGE} per page
      </div>
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line bg-white text-ink-soft hover:border-teal hover:text-teal disabled:cursor-not-allowed disabled:opacity-35"
          disabled={currentPage <= 0}
          aria-label="Previous page"
          title="Previous page"
          onClick={goPrevTablePage}
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
        </button>
        <span className="min-w-[5.5rem] text-center text-[12.5px] font-semibold tabular-nums text-ink">
          {currentPage + 1} / {pageCount}
        </span>
        <button
          type="button"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-line bg-white text-ink-soft hover:border-teal hover:text-teal disabled:cursor-not-allowed disabled:opacity-35"
          disabled={currentPage >= pageCount - 1}
          aria-label="Next page"
          title="Next page"
          onClick={goNextTablePage}
        >
          <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
        </button>
      </div>
    </div>
  ) : null

  const chipClass = (active) =>
    `dhara-tab flex h-8 flex-none items-center gap-1.5 rounded-full px-3.5 text-[12.5px] font-semibold ${
      active
        ? 'border-teal-deep bg-teal-deep text-cream'
        : 'border-line bg-white text-ink-soft hover:border-teal/35 hover:bg-sage hover:text-teal-deep'
    }`

  return (
    <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3}>
    <div ref={rootRef} className="flex flex-col gap-[18px]">
      <ScrollToTopButton scrollRootRef={rootRef} />
      {pendingDeleteIds && (
        <DeleteConfirmDialog
          count={pendingDeleteIds.length}
          onCancel={() => !deleting && setPendingDeleteIds(null)}
          onConfirm={confirmDelete}
          deleting={deleting}
        />
      )}
      {pendingMergeIds && (
        <MergeConfirmDialog
          count={pendingMergeIds.length}
          onCancel={() => !merging && setPendingMergeIds(null)}
          onConfirm={confirmMerge}
          merging={merging}
        />
      )}

      {/* Page header — title / purpose stay above the content panel */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <button
            type="button"
            className="mb-3.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-teal hover:text-teal-dark"
            onClick={onDone}
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            Upload another PDF
          </button>
          <div className="font-display text-[26px] font-medium leading-tight text-ink">Review Extracted Tables</div>
          <div className="mt-1.5 text-[13px] font-medium text-ink">
            {filename || 'PDF report'}
            {filteredCount > 0 ? (
              <span className="font-normal text-ink-soft">
                {' '}· page {currentPage + 1} of {pageCount}
              </span>
            ) : null}
          </div>
        </div>
        <div className="flex flex-none flex-wrap items-center justify-end gap-2.5">
          <KydsSummaryCard variant="corner" />
          <Button variant="primary" disabled={continuing} onClick={continueToGrouping} className="inline-flex items-center gap-1.5">
            {continuing ? 'Saving…' : (
              <>
                Continue
                <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
              </>
            )}
          </Button>
        </div>
      </div>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      {/* Content box: filters stick at the top of the scrollport while tables scroll underneath. */}
      <div className="rounded-xl border border-line bg-white shadow-sm">
        <div className="sticky top-0 z-20 space-y-2 rounded-t-xl border-b border-line bg-white px-5 py-3 sm:px-6">
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex-none text-[13px] font-bold tracking-wide text-ink">
              Filter by:
            </span>
            <div className="flex min-w-0 flex-1 flex-wrap gap-2" role="tablist" aria-label="Filter tables by review status">
              {primaryFilterOptions.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={activeFilter === id || (id === 'needs_review' && REASON_FILTER_IDS.includes(activeFilter))}
                  className={chipClass(activeFilter === id || (id === 'needs_review' && REASON_FILTER_IDS.includes(activeFilter)))}
                  onClick={() => {
                    setStatusFilter(id)
                    setExpanded(null)
                    setTablePage(0)
                  }}
                >
                  {label}
                  <span className={`rounded-full px-1.5 py-px text-[11px] font-bold transition-colors duration-[420ms] ${
                    activeFilter === id || (id === 'needs_review' && REASON_FILTER_IDS.includes(activeFilter))
                      ? 'bg-cream/20 text-cream'
                      : 'bg-cream text-ink-soft'
                  }`}>
                    {filterCounts[id] ?? 0}
                  </span>
                </button>
              ))}
            </div>
            {!selectMode ? (
              <div className="ml-auto flex flex-none items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={tables.length < 2}
                  onClick={() => enterSelectMode('merge')}
                  title="Merge tables that share the same column headers"
                >
                  Merge
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  className="!border-[#c45c4a] !text-[#c45c4a] hover:!bg-[#fff1ee]"
                  disabled={tables.length === 0}
                  onClick={() => enterSelectMode('delete')}
                >
                  Delete
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={!tables?.length || downloadingZip}
                  onClick={() => enterSelectMode('download')}
                  title="Select tables to download as a ZIP"
                >
                  Download
                </Button>
              </div>
            ) : null}
          </div>

          {showReasonFilters && (
            <div
              className="flex flex-wrap items-center gap-2 border-t border-line/70 pt-2"
              role="tablist"
              aria-label="Filter by review reason"
            >
              <span className="flex-none text-[12px] font-semibold tracking-wide text-ink-soft">
                Reason:
              </span>
              {reasonFilterOptions.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={activeFilter === id}
                  className={chipClass(activeFilter === id)}
                  onClick={() => {
                    setStatusFilter(id)
                    setExpanded(null)
                    setTablePage(0)
                  }}
                >
                  {label}
                  <span className={`rounded-full px-1.5 py-px text-[11px] font-bold transition-colors duration-[420ms] ${
                    activeFilter === id ? 'bg-cream/20 text-cream' : 'bg-cream text-ink-soft'
                  }`}>
                    {filterCounts[id] ?? 0}
                  </span>
                </button>
              ))}
            </div>
          )}

          {selectMode && (
            <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-line bg-cream/80 px-3 py-2">
              <label className="flex cursor-pointer items-center gap-2 text-[13px] font-semibold text-ink">
                <input
                  type="checkbox"
                  className="h-3.5 w-3.5 accent-teal"
                  checked={allFilteredSelected}
                  disabled={filteredIds.length === 0}
                  onChange={toggleSelectAllFiltered}
                />
                Select all{activeFilter !== 'all' || selectMode === 'merge' ? ' shown' : ''}
              </label>
              <span className="text-[12.5px] text-ink-soft">
                {selectedCount === 0
                  ? (selectMode === 'merge' ? 'Select a table — then only matching headers stay listed' : 'None selected')
                  : `${selectedCount} selected`}
                {selectMode === 'download'
                  ? ' · download as ZIP'
                  : selectMode === 'merge'
                    ? ' · merge same-header tables'
                    : ' · delete'}
              </span>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                <Button variant="secondary" size="sm" onClick={exitSelectMode} disabled={downloadingZip || merging}>
                  Cancel
                </Button>
                {selectMode === 'delete' ? (
                  <Button
                    variant="secondary"
                    size="sm"
                    className="!border-[#c45c4a] !text-[#c45c4a] hover:!bg-[#fff1ee]"
                    disabled={selectedCount === 0}
                    onClick={() => setPendingDeleteIds([...selectedIds])}
                  >
                    Delete selected
                  </Button>
                ) : selectMode === 'merge' ? (
                  <Button
                    variant="primary"
                    size="sm"
                    disabled={!canMerge || merging}
                    onClick={() => setPendingMergeIds([...selectedIds])}
                  >
                    Merge selected{selectedCount >= 2 ? ` (${selectedCount})` : ''}
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={!tables?.length || downloadingZip}
                      onClick={() => downloadZip(null)}
                    >
                      {downloadingZip ? 'Preparing…' : 'Download all'}
                    </Button>
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={selectedCount === 0 || downloadingZip}
                      onClick={() => downloadZip([...selectedIds])}
                    >
                      {downloadingZip ? 'Preparing…' : `Download selected${selectedCount ? ` (${selectedCount})` : ''}`}
                    </Button>
                  </>
                )}
              </div>
            </div>
          )}

          {tablesPaginationBar ? (
            <div className="border-t border-line pt-2">
              {tablesPaginationBar}
            </div>
          ) : null}
        </div>

        <div className="flex flex-col gap-2 px-5 py-3 sm:px-6 sm:pb-5">
          {filteredCount === 0 ? (
            <div className="rounded-lg border border-dashed border-line px-2 py-10 text-center text-[13px] text-ink-soft">
              {selectMode === 'merge' && selectedIds.size > 0
                ? 'No other tables share these column headers.'
                : 'No tables match this filter.'}
            </div>
          ) : pageTables.map((t) => {
            const isOpen = expanded === t.table_id
            const reviewed = reviewedIds.has(t.table_id)
            const selected = selectedIds.has(t.table_id)
            return (
              <div key={t.table_id} className={`overflow-hidden rounded-lg border bg-surface transition-[border-color] duration-300 ease-out ${isOpen ? 'border-teal' : selectMode && selected ? 'border-teal/50' : 'border-line'}`}>
                <div className="flex items-center gap-2.5 px-3.5 py-2.5 hover:bg-cream">
                  {selectMode && (
                    <input
                      type="checkbox"
                      className="h-3.5 w-3.5 flex-none accent-teal"
                      checked={selected}
                      aria-label={`Select ${displayTitle(t) || `page ${t.page} table`}`}
                      onChange={() => toggleSelected(t.table_id)}
                      onClick={(e) => e.stopPropagation()}
                    />
                  )}
                  <div
                    className="flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-3"
                    onClick={() => setExpanded(isOpen ? null : t.table_id)}
                  >
                    <div className="min-w-0 flex-1">
                      <TableTitleDisplay table={t} />
                      <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">
                        Page {t.page} · {t.semantic_status === 'classified' ? 'AI-classified' : 'Auto-accepted (no AI review)'}
                      </div>
                    </div>
                    <div className="flex flex-none items-center gap-2">
                      {!selectMode && (
                        <button
                          type="button"
                          className="flex h-7 w-7 flex-none items-center justify-center rounded border border-line text-ink-soft hover:border-teal hover:text-teal disabled:opacity-50"
                          title="Download this table"
                          aria-label="Download this table"
                          disabled={downloadingId === t.table_id}
                          onClick={(e) => {
                            e.stopPropagation()
                            downloadOneTable(t.table_id, displayTitle(t) || `page_${t.page}_table`)
                          }}
                        >
                          {downloadingId === t.table_id ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} aria-hidden />
                          ) : (
                            <Download className="h-3.5 w-3.5" strokeWidth={1.75} aria-hidden />
                          )}
                        </button>
                      )}
                      {reviewed ? (
                        <Badge tone="ok">
                          <span className="inline-flex items-center gap-1">
                            <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden />
                            Reviewed
                          </span>
                        </Badge>
                      ) : (
                        <ReviewBadge needed={t.human_review_needed} reason={t.human_review_reason} />
                      )}
                    </div>
                  </div>
                </div>
                <TableExpandPanel open={isOpen}>
                  <TableDetail
                    table={t}
                    jobId={jobId}
                    onSave={(edits) => saveReview(t.table_id, edits)}
                    onTitleLive={(title) => {
                      setTables((prev) => prev.map((row) => (
                        row.table_id === t.table_id ? { ...row, title } : row
                      )))
                    }}
                    onTitleCommit={(title) => saveReview(t.table_id, { title })}
                  />
                </TableExpandPanel>
              </div>
            )
          })}

          {tablesPaginationBar ? (
            <div className="mt-2 border-t border-line pt-3">
              {tablesPaginationBar}
            </div>
          ) : null}
        </div>
      </div>
    </div>
    </PdfConsoleLayout>
  )
}
