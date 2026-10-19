'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft, ArrowRight, Check, Download, Loader2, Search, Sparkles, X } from 'lucide-react'
import { withAuthHeaders } from '../../lib/auth'
import { withLlmKeyHeaders } from '../../lib/llmKey'
import Badge from '../ui/Badge'
import Button from '../ui/Button'
import ErrorBanner from '../ui/ErrorBanner'
import KydsSummaryCard from '../KydsSummaryCard'
import PdfConsoleLayout from './PdfConsoleLayout'
import ProcessingStepper from '../console/ProcessingStepper'
import StageSubstepBreadcrumb from '../console/StageSubstepBreadcrumb'
import { INVENTORY_CRUMBS } from '../console/ConsoleStages'
import {
  PRIMARY_FILTERS,
  REASON_FILTER_IDS,
  REASON_LABELS,
  TABLE_EDIT_CHANNEL,
  closeEditorWindow,
  displayTitle,
  isAiClassified,
  matchesStatusFilter,
  matchesSourceTypeFilter,
  matchesTableSearch,
  primaryReviewReason,
  reviewFlagSummary,
  SOURCE_TYPE_FILTERS,
  scrollElementIntoViewBelowSticky,
  tableHasMissingTitle,
  tableHeaderKey,
  tableSourceSubtitle,
} from '../../lib/pdfReviewHelpers'
import {
  ContinueAfterSelectionDialog,
  DeleteConfirmDialog,
  KeepSelectedConfirmDialog,
  MergeConfirmDialog,
  ReviewBadge,
  ScrollToTopButton,
  TableExpandPanel,
} from './PdfReviewAtoms'
import { TableDetail, TableTitleDisplay } from './TableDetail'
import FilesReturnChoiceDialog from '../console/FilesReturnChoiceDialog'
import { beginAppendFilesMode } from '../../lib/consoleSession'
import { namesFromReviewTables } from '../../lib/existingDatasetNames'

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
  const [sourceTypeFilter, setSourceTypeFilter] = useState('all')
  const [tableSearch, setTableSearch] = useState('')
  const [tablePage, setTablePage] = useState(0)
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  // null | 'keep' | 'delete' | 'download' | 'merge' — same checkbox UI, different confirm action
  const [selectMode, setSelectMode] = useState(null)
  const [pendingDeleteIds, setPendingDeleteIds] = useState(null)
  const [pendingMergeIds, setPendingMergeIds] = useState(null)
  const [pendingKeepIds, setPendingKeepIds] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [merging, setMerging] = useState(false)
  const [continuing, setContinuing] = useState(false)
  // Soft pipeline selection: tables stay visible; only these IDs continue.
  // null = no filter (every table proceeds, previous behaviour).
  const [pipelineSelectedIds, setPipelineSelectedIds] = useState(null)
  const [continueWarnOpen, setContinueWarnOpen] = useState(false)
  // AI search over the existing list — null match set means regular text search.
  const [aiSearching, setAiSearching] = useState(false)
  const [aiMatchIds, setAiMatchIds] = useState(null)
  const [aiIntent, setAiIntent] = useState(null)
  const [aiRationale, setAiRationale] = useState('')
  // 'persist' | 'group' — drives the Continue placeholder stepper
  const [continuePhase, setContinuePhase] = useState('persist')
  const [downloadingZip, setDownloadingZip] = useState(false)
  const [downloadingId, setDownloadingId] = useState(null)
  const [filesReturnOpen, setFilesReturnOpen] = useState(false)
  const rootRef = useRef(null)
  const stickyFiltersRef = useRef(null)
  const tableCardRefs = useRef(new Map())
  const router = useRouter()

  const requestLeaveToFiles = () => setFilesReturnOpen(true)
  const confirmStartOverFiles = () => {
    setFilesReturnOpen(false)
    onDone?.()
  }
  const confirmAddMoreFiles = () => {
    setFilesReturnOpen(false)
    beginAppendFilesMode(router, {
      jobId,
      existingFilenames: namesFromReviewTables(tables, filename),
      returnPath: `/console/review/${jobId}`,
    })
  }
  const handleStageGoToStep = (targetStep) => {
    if (targetStep === 1) {
      requestLeaveToFiles()
      return
    }
    if (!jobId) return
    if (targetStep === 2) {
      router.push(`/console/review/${jobId}`)
      return
    }
    if (targetStep === 3) {
      router.push(`/console/grouping/${jobId}`)
    }
  }

  // When a table card expands, bring it into view under the sticky filters so
  // the opened preview is not stuck below the fold.
  useEffect(() => {
    if (!expanded) return undefined
    const card = tableCardRefs.current.get(expanded)
    if (!card) return undefined
    let cancelled = false
    let innerRaf = 0
    const run = () => {
      if (cancelled) return
      scrollElementIntoViewBelowSticky(card, stickyFiltersRef.current)
    }
    // Wait for the accordion to mount / start opening before measuring.
    const outerRaf = window.requestAnimationFrame(() => {
      innerRaf = window.requestAnimationFrame(run)
    })
    // Nudge again after the expand animation so tall previews stay in view.
    const t = window.setTimeout(run, 280)
    return () => {
      cancelled = true
      window.cancelAnimationFrame(outerRaf)
      window.cancelAnimationFrame(innerRaf)
      window.clearTimeout(t)
    }
  }, [expanded])

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

  const requestContinueToGrouping = () => {
    if (continuing) return
    if (pipelineSelectedIds?.size) {
      setContinueWarnOpen(true)
      return
    }
    void continueToGrouping()
  }

  const continueToGrouping = async () => {
    setContinueWarnOpen(false)
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
      const approvedIds = pipelineSelectedIds?.size ? [...pipelineSelectedIds] : null
      const tablesForContinue = approvedIds
        ? (tables || []).filter((t) => approvedIds.includes(t.table_id))
        : (tables || [])
      const res = await fetch(
        `/api/pdf/jobs/${jobId}/persist-approved`,
        withLlmKeyHeaders(withAuthHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          // Preview state is source of truth for titles / reviews at Continue.
          // approved_table_ids (when set) limits which tables enter grouping.
          body: JSON.stringify({
            tables: tablesForContinue.map((t) => ({
              table_id: t.table_id,
              title: t.title ?? null,
              rows: t.rows,
              columns: t.columns,
              classification: t.classification,
              human_review_needed: t.human_review_needed,
              human_review_reason: t.human_review_reason,
              semantic_status: t.semantic_status,
            })),
            ...(approvedIds ? { approved_table_ids: approvedIds } : {}),
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

  const patchTable = async (tableId, edits) => {
    setTables((prev) => prev.map((t) => (t.table_id === tableId ? { ...t, ...edits } : t)))
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

  const saveReview = async (tableId, edits) => {
    await patchTable(tableId, edits)
    setReviewedIds((prev) => new Set(prev).add(tableId))
  }

  const removeTablesByIds = async (ids) => {
    if (!ids?.length) return
    const res = await fetch(`/api/pdf/jobs/${jobId}/tables/delete`, withAuthHeaders({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ table_ids: ids }),
    }))
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      throw new Error(body.detail || 'Could not remove tables')
    }
    const idSet = new Set(ids)
    setTables((prev) => prev.filter((t) => !idSet.has(t.table_id)))
    setReviewedIds((prev) => {
      const next = new Set(prev)
      ids.forEach((id) => next.delete(id))
      return next
    })
    setPipelineSelectedIds((prev) => {
      if (!prev?.size) return prev
      const next = new Set([...prev].filter((id) => !idSet.has(id)))
      return next.size ? next : null
    })
    setAiMatchIds((prev) => (prev ? prev.filter((id) => !idSet.has(id)) : prev))
    if (expanded && idSet.has(expanded)) setExpanded(null)
    setSelectedIds(new Set())
    setSelectMode(null)
  }

  const confirmDelete = async () => {
    if (!pendingDeleteIds?.length) return
    setDeleting(true)
    const ids = [...pendingDeleteIds]
    try {
      await removeTablesByIds(ids)
      setPendingDeleteIds(null)
    } catch (e) {
      setError(e.message || 'Could not delete tables')
      setPendingDeleteIds(null)
    } finally {
      setDeleting(false)
    }
  }

  const confirmKeepSelected = () => {
    if (!pendingKeepIds?.length) return
    setPipelineSelectedIds(new Set(pendingKeepIds))
    setPendingKeepIds(null)
    setSelectedIds(new Set())
    setSelectMode(null)
    setTablePage(0)
  }

  const clearAiSearch = ({ keepSelectMode = false } = {}) => {
    setAiMatchIds(null)
    setAiIntent(null)
    setAiRationale('')
    if (!keepSelectMode && selectMode === 'delete') {
      // Leaving AI remove selection — drop select mode unless steward is mid-delete.
      setSelectMode(null)
      setSelectedIds(new Set())
    }
  }

  const runAiSearch = async () => {
    const prompt = tableSearch.trim()
    if (!prompt || aiSearching || !tables?.length) return
    setAiSearching(true)
    setError('')
    try {
      const res = await fetch(
        `/api/pdf/jobs/${jobId}/tables/ai-search`,
        withLlmKeyHeaders(withAuthHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            prompt,
            tables: tables.map((t) => ({
              table_id: t.table_id,
              title: t.title ?? null,
              banner_table_id: t.banner_table_id ?? null,
              page: t.page,
              short_description: t.short_description ?? t.description ?? null,
            })),
          }),
        })),
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(typeof body.detail === 'string' ? body.detail : 'AI search failed')
      }
      const data = await res.json()
      const alive = new Set((tables || []).map((t) => t.table_id))
      const ids = (data.table_ids || []).map(String).filter((id) => alive.has(id))
      const intent = data.intent === 'remove' ? 'remove' : 'find'
      setAiMatchIds(ids)
      setAiIntent(intent)
      setAiRationale(typeof data.rationale === 'string' ? data.rationale : '')
      setExpanded(null)
      setTablePage(0)

      if (intent === 'remove' && ids.length) {
        // Select in the existing delete workflow — never auto-delete.
        setSelectMode('delete')
        setSelectedIds(new Set(ids))
      } else if (selectMode === 'delete' && intent !== 'remove') {
        setSelectMode(null)
        setSelectedIds(new Set())
      }

      if (!ids.length) {
        setError(data.rationale || 'No tables matched that AI search.')
      }
    } catch (e) {
      setError(e.message || 'AI search failed')
    } finally {
      setAiSearching(false)
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
    // Re-open Select with the current pipeline picks pre-checked so the
    // steward can add more without starting from scratch.
    setSelectedIds(
      mode === 'keep' && pipelineSelectedIds?.size
        ? new Set(pipelineSelectedIds)
        : new Set(),
    )
    setExpanded(null)
    setTablePage(0)
  }

  if (error && !tables) {
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3} onGoToStep={handleStageGoToStep}>
        <FilesReturnChoiceDialog
          open={filesReturnOpen}
          onCancel={() => setFilesReturnOpen(false)}
          onAddMore={confirmAddMoreFiles}
          onStartOver={confirmStartOverFiles}
        />
        <div className="flex flex-col gap-[18px]">
          <div className="flex flex-col">
            <button
              type="button"
              className="mb-3.5 inline-flex items-center gap-1.5 self-start text-[15px] font-semibold text-teal hover:text-teal-dark"
              onClick={requestLeaveToFiles}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              Upload another PDF
            </button>
            <StageSubstepBreadcrumb
              crumbs={INVENTORY_CRUMBS}
              activeId="preview"
              onNavigate={(next) => {
                if (next === 'files') requestLeaveToFiles()
              }}
              isReachable={() => true}
              ariaLabel="Dataset inventory"
              size="page"
            />
            <div className="mt-1 text-[15px] text-ink-soft">Couldn’t load this extraction job.</div>
          </div>
          <div className="flex flex-col gap-3 rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
            <ErrorBanner>{error}</ErrorBanner>
            <Button variant="primary" className="self-start" onClick={requestLeaveToFiles}>Upload PDF again</Button>
          </div>
        </div>
      </PdfConsoleLayout>
    )
  }
  if (!tables) {
    return (
      <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3} onGoToStep={handleStageGoToStep}>
        <FilesReturnChoiceDialog
          open={filesReturnOpen}
          onCancel={() => setFilesReturnOpen(false)}
          onAddMore={confirmAddMoreFiles}
          onStartOver={confirmStartOverFiles}
        />
        <div className="flex flex-col gap-[18px]">
          <div className="flex flex-col">
            <StageSubstepBreadcrumb
              crumbs={INVENTORY_CRUMBS}
              activeId="preview"
              onNavigate={(next) => {
                if (next === 'files') requestLeaveToFiles()
              }}
              isReachable={() => true}
              ariaLabel="Dataset inventory"
              size="page"
            />
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
    const primary = primaryReviewReason(t)
    if (primary && filterCounts[primary] !== undefined) filterCounts[primary] += 1
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
    // DEV-ONLY: isolate tables that went through the LLM classification
    // step vs. the deterministic auto-accepted path, for QA'ing AI output.
    // Never shown in a production build.
    ...(process.env.NODE_ENV !== 'production' ? [
      { id: 'dev_ai_classified', label: 'AI extracted' },
      { id: 'dev_auto_extracted', label: 'Auto-extracted' },
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

  const sourceTypeCounts = { all: tables.length, pdf: 0, excel: 0, csv: 0 }
  for (const t of tables) {
    const st = (t.source_type || '').toLowerCase()
    if (st === 'pdf') sourceTypeCounts.pdf += 1
    else if (st === 'excel') sourceTypeCounts.excel += 1
    else if (st === 'csv') sourceTypeCounts.csv += 1
  }
  const sourceFilterOptions = SOURCE_TYPE_FILTERS.filter(
    (o) => o.id === 'all' || sourceTypeCounts[o.id] > 0,
  )

  let filteredTables = tables.filter((t) =>
    matchesStatusFilter(t, activeFilter, reviewedIds.has(t.table_id))
      && matchesSourceTypeFilter(t, sourceTypeFilter)
  )
  // Search is additive: status / reason / merge filters stay unchanged.
  // AI "find" filters the list; AI "remove" only selects checkboxes so the
  // full list stays accessible for manual adjustments.
  const searchQuery = tableSearch.trim()
  if (aiMatchIds && aiIntent === 'find') {
    const idSet = new Set(aiMatchIds)
    filteredTables = filteredTables.filter((t) => idSet.has(t.table_id))
  } else if (!aiMatchIds && searchQuery) {
    filteredTables = filteredTables.filter((t) => matchesTableSearch(t, searchQuery))
  }
  // Merge mode: after the first selection, only show tables with the same headers.
  if (selectMode === 'merge' && selectedIds.size > 0) {
    const anchor = tables.find((t) => selectedIds.has(t.table_id))
    const key = anchor ? tableHeaderKey(anchor) : ''
    if (key) {
      filteredTables = filteredTables.filter((t) => tableHeaderKey(t) === key)
    }
  }
  // Pipeline selection: keep every table visible, but float selected ones to the top.
  if (pipelineSelectedIds?.size) {
    filteredTables = [...filteredTables].sort((a, b) => {
      const aSel = pipelineSelectedIds.has(a.table_id) ? 0 : 1
      const bSel = pipelineSelectedIds.has(b.table_id) ? 0 : 1
      return aSel - bSel
    })
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
        {activeFilter !== 'all' || searchQuery ? ' (filtered)' : ''}
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

  const chipClass = (active, { review = false } = {}) =>
    `dhara-tab flex h-8 flex-none items-center gap-1.5 rounded-full px-3.5 text-[12.5px] font-semibold ${
      review
        ? (active
          ? 'border-[#E8A05A] bg-[#F5C48A] text-[#8A4A12]'
          : 'border-[#F0B27A]/55 bg-[#FFF6EE] text-[#D4782E] hover:border-[#E8A05A] hover:bg-[#FFECD8]')
        : (active
          ? 'border-teal-deep bg-teal-deep text-cream'
          : 'border-line bg-white text-ink-soft hover:border-teal/35 hover:bg-sage hover:text-teal-deep')
    }`

  return (
    <PdfConsoleLayout jobId={jobId} step={2} maxStepReached={3} onGoToStep={handleStageGoToStep}>
    <div ref={rootRef} className="flex flex-col gap-[18px]">
      <ScrollToTopButton scrollRootRef={rootRef} />
      <FilesReturnChoiceDialog
        open={filesReturnOpen}
        onCancel={() => setFilesReturnOpen(false)}
        onAddMore={confirmAddMoreFiles}
        onStartOver={confirmStartOverFiles}
      />
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
      {pendingKeepIds && (
        <KeepSelectedConfirmDialog
          keepCount={pendingKeepIds.length}
          dropCount={Math.max(0, (tables?.length || 0) - pendingKeepIds.length)}
          onCancel={() => setPendingKeepIds(null)}
          onConfirm={confirmKeepSelected}
          keeping={false}
        />
      )}
      {continueWarnOpen && (
        <ContinueAfterSelectionDialog
          count={pipelineSelectedIds?.size || 0}
          onCancel={() => !continuing && setContinueWarnOpen(false)}
          onConfirm={() => { void continueToGrouping() }}
          continuing={continuing}
        />
      )}

      {/* Page header — title / purpose stay above the content panel */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <button
            type="button"
            className="mb-3.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-teal hover:text-teal-dark"
            onClick={requestLeaveToFiles}
          >
            <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
            Upload another file
          </button>
          <StageSubstepBreadcrumb
            crumbs={INVENTORY_CRUMBS}
            activeId="preview"
            onNavigate={(next) => {
              if (next === 'files') requestLeaveToFiles()
            }}
            isReachable={() => true}
            ariaLabel="Dataset inventory"
            size="page"
          />
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
        </div>
      </div>

      {error && <ErrorBanner>{error}</ErrorBanner>}

      {/* Content box: filters stick at the top of the scrollport while tables scroll underneath. */}
      <div className="rounded-xl border border-line bg-white shadow-sm">
        <div ref={stickyFiltersRef} className="sticky top-0 z-20 space-y-2 rounded-t-xl border-b border-line bg-white px-5 py-3 sm:px-6">
          <div className="space-y-1">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-stretch">
              <label
                className={`flex min-w-0 flex-1 items-center gap-2 rounded-lg border px-2.5 py-2 focus-within:border-teal focus-within:shadow-focus-ring ${
                  aiMatchIds
                    ? 'border-teal/50 bg-sage/40'
                    : 'border-line bg-cream'
                }`}
              >
                {aiMatchIds ? (
                  <Sparkles className="h-4 w-4 flex-none text-teal" strokeWidth={2} aria-hidden />
                ) : (
                  <Search className="h-4 w-4 flex-none text-ink-soft" strokeWidth={2} aria-hidden />
                )}
                <input
                  type="text"
                  value={tableSearch}
                  onChange={(e) => {
                    setTableSearch(e.target.value)
                    if (aiMatchIds) clearAiSearch({ keepSelectMode: true })
                    setExpanded(null)
                    setTablePage(0)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                      e.preventDefault()
                      runAiSearch()
                    }
                  }}
                  placeholder={aiMatchIds ? 'AI search active — edit to return to regular search' : 'Search by table name or page…'}
                  className="min-w-0 flex-1 appearance-none border-0 bg-transparent p-0 text-[13.5px] text-ink shadow-none outline-none placeholder:text-ink-soft focus:outline-none focus:ring-0"
                  aria-label="Search tables by name or page number"
                  autoComplete="off"
                  spellCheck={false}
                  disabled={aiSearching}
                />
                {(tableSearch || aiMatchIds) ? (
                  <button
                    type="button"
                    className="flex-none text-ink-soft hover:text-teal"
                    onClick={() => {
                      setTableSearch('')
                      clearAiSearch()
                      setExpanded(null)
                      setTablePage(0)
                    }}
                    aria-label="Clear search"
                  >
                    <X className="h-3.5 w-3.5" strokeWidth={2} />
                  </button>
                ) : null}
              </label>
              <Button
                variant="secondary"
                className="sm:flex-none"
                disabled={aiSearching || !tableSearch.trim() || !tables?.length}
                onClick={runAiSearch}
                title="Interpret this as a natural-language search (⌘/Ctrl+Enter)"
              >
                {aiSearching ? (
                  <span className="inline-flex items-center gap-1.5">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} aria-hidden />
                    Searching…
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5">
                    <Sparkles className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
                    Search with AI
                  </span>
                )}
              </Button>
            </div>
            {aiMatchIds ? (
              <div className="flex flex-wrap items-center gap-2 px-0.5">
                <span className="inline-flex items-center gap-1 rounded-full border border-teal/30 bg-sage px-2 py-0.5 text-[11.5px] font-semibold text-teal-deep">
                  <Sparkles className="h-3 w-3" strokeWidth={2} aria-hidden />
                  AI {aiIntent === 'remove' ? 'remove selection' : 'results'}
                  <span className="tabular-nums">· {aiMatchIds.length}</span>
                </span>
                {aiRationale ? (
                  <span className="min-w-0 flex-1 truncate text-[11.5px] text-ink-soft">{aiRationale}</span>
                ) : null}
                <button
                  type="button"
                  className="text-[11.5px] font-semibold text-teal hover:text-teal-dark"
                  onClick={() => clearAiSearch()}
                >
                  Regular search
                </button>
              </div>
            ) : (
              <p className="m-0 px-0.5 text-[11.5px] leading-snug text-ink-soft">
                Tip: jump to a page with <span className="font-medium text-ink">15</span>, <span className="font-medium text-ink">p15</span>, or <span className="font-medium text-ink">page 15</span>
                {' '}· or use <span className="font-medium text-ink">Search with AI</span> for natural language
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="flex-none text-[13px] font-bold tracking-wide text-ink">
              Filter by:
            </span>
            <div className="flex min-w-0 flex-1 flex-wrap gap-2" role="tablist" aria-label="Filter tables by review status">
              {primaryFilterOptions.map(({ id, label }) => {
                const isReviewChip = id === 'needs_review'
                const active = activeFilter === id
                  || (id === 'needs_review' && REASON_FILTER_IDS.includes(activeFilter))
                return (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={chipClass(active, { review: isReviewChip })}
                  onClick={() => {
                    setStatusFilter(id)
                    setExpanded(null)
                    setTablePage(0)
                  }}
                >
                  {label}
                  <span className={`rounded-full px-1.5 py-px text-[11px] font-bold transition-colors duration-[420ms] ${
                    active
                      ? (isReviewChip ? 'bg-white/30 text-[#8A4A12]' : 'bg-cream/20 text-cream')
                      : (isReviewChip ? 'bg-white/80 text-[#D4782E]' : 'bg-cream text-ink-soft')
                  }`}>
                    {filterCounts[id] ?? 0}
                  </span>
                </button>
                )
              })}
            </div>
            {!selectMode ? (
              <div className="ml-auto flex flex-none items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={tables.length === 0}
                  onClick={() => enterSelectMode('keep')}
                  title="Choose which tables continue to grouping and later steps"
                >
                  {pipelineSelectedIds?.size ? `Select (${pipelineSelectedIds.size})` : 'Select'}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={tables.length < 2}
                  onClick={() => enterSelectMode('merge')}
                  title="Merge tables that flow into multiple pages"
                >
                  Merge
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
                <Button
                  variant="secondary"
                  size="sm"
                  className="!border-[#c45c4a] !text-[#c45c4a] hover:!bg-[#fff1ee]"
                  disabled={tables.length === 0}
                  onClick={() => enterSelectMode('delete')}
                >
                  Delete
                </Button>
              </div>
            ) : null}
          </div>

          {sourceFilterOptions.length > 2 && (
            <div className="flex flex-wrap items-center gap-2 border-t border-line/70 pt-2">
              <span className="flex-none text-[12px] font-semibold tracking-wide text-ink-soft">Source:</span>
              {sourceFilterOptions.map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  className={chipClass(sourceTypeFilter === id)}
                  onClick={() => {
                    setSourceTypeFilter(id)
                    setExpanded(null)
                    setTablePage(0)
                  }}
                >
                  {label}
                  <span className={`rounded-full px-1.5 py-px text-[11px] font-bold ${
                    sourceTypeFilter === id ? 'bg-cream/20 text-cream' : 'bg-cream text-ink-soft'
                  }`}>
                    {sourceTypeCounts[id] ?? 0}
                  </span>
                </button>
              ))}
            </div>
          )}

          <TableExpandPanel open={showReasonFilters}>
            <div
              className="flex flex-wrap items-center gap-2 border-t border-line/70 pt-2"
              role="tablist"
              aria-label="Filter by review reason"
            >
              <span className="flex-none text-[12px] font-semibold tracking-wide text-ink-soft">
                Reason:
              </span>
              {reasonFilterOptions.map(({ id, label }) => {
                const active = activeFilter === id
                return (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={chipClass(active, { review: true })}
                  onClick={() => {
                    setStatusFilter(id)
                    setExpanded(null)
                    setTablePage(0)
                  }}
                >
                  {label}
                  <span className={`rounded-full px-1.5 py-px text-[11px] font-bold transition-colors duration-[420ms] ${
                    active ? 'bg-white/30 text-[#8A4A12]' : 'bg-white/80 text-[#D4782E]'
                  }`}>
                    {filterCounts[id] ?? 0}
                  </span>
                </button>
                )
              })}
            </div>
          </TableExpandPanel>

          {selectMode && (
            <div className="flex flex-wrap items-center gap-2.5 rounded-lg border border-line bg-cream/80 px-3 py-2">
              <label className="flex cursor-pointer items-center gap-2 text-[13px] font-semibold text-ink">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded-md accent-teal"
                  checked={allFilteredSelected}
                  disabled={filteredIds.length === 0}
                  onChange={toggleSelectAllFiltered}
                />
                Select all{activeFilter !== 'all' || selectMode === 'merge' ? ' shown' : ''}
              </label>
              <span className="text-[12.5px] text-ink-soft">
                {selectedCount === 0
                  ? (selectMode === 'merge'
                    ? 'Select a table — then only matching headers stay listed'
                    : selectMode === 'keep'
                      ? 'Select the tables that should continue in the pipeline'
                      : 'None selected')
                  : `${selectedCount} selected`}
                {selectMode === 'download'
                  ? ' · download as ZIP'
                  : selectMode === 'merge'
                    ? ' · merge same-header tables'
                    : selectMode === 'keep'
                      ? ' · for grouping (all tables stay listed)'
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
                ) : selectMode === 'keep' ? (
                  <>
                    {pipelineSelectedIds?.size ? (
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => {
                          setPipelineSelectedIds(null)
                          setSelectedIds(new Set())
                          setSelectMode(null)
                        }}
                      >
                        Clear selection
                      </Button>
                    ) : null}
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={selectedCount === 0}
                      onClick={() => setPendingKeepIds([...selectedIds])}
                    >
                      Use selected{selectedCount ? ` (${selectedCount})` : ''}
                    </Button>
                  </>
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
                : searchQuery
                  ? `No tables match “${searchQuery}”.`
                  : 'No tables match this filter.'}
            </div>
          ) : pageTables.map((t) => {
            const isOpen = expanded === t.table_id
            const reviewed = reviewedIds.has(t.table_id)
            const selected = selectedIds.has(t.table_id)
            const inPipeline = Boolean(pipelineSelectedIds?.has(t.table_id))
            const primaryReason = primaryReviewReason(t)
            const flagSummary = reviewed ? '' : reviewFlagSummary(t)
            const needsReviewBadge = Boolean(primaryReason)
              || Boolean(t.human_review_needed)
              || tableHasMissingTitle(t)
            return (
              <div
                key={t.table_id}
                ref={(node) => {
                  if (node) tableCardRefs.current.set(t.table_id, node)
                  else tableCardRefs.current.delete(t.table_id)
                }}
                className={`overflow-hidden rounded-2xl border transition-[border-color,background-color] duration-300 ease-out ${
                  isOpen
                    ? 'border-teal bg-surface'
                    : inPipeline
                      ? 'border-teal/55 bg-sage/50'
                      : selectMode && selected
                        ? 'border-teal/50 bg-surface'
                        : 'border-line bg-surface'
                }`}
              >
                <div className="flex items-center gap-2.5 px-3.5 py-2.5 hover:bg-cream">
                  {selectMode && (
                    <input
                      type="checkbox"
                      className="h-4 w-4 flex-none rounded-md accent-teal"
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
                      <div className="flex min-w-0 items-center gap-2">
                        <div className="min-w-0 flex-1">
                          <TableTitleDisplay table={t} />
                        </div>
                        {inPipeline ? (
                          <span className="flex-none rounded-md border border-teal/35 bg-sage px-1.5 py-0.5 text-[10.5px] font-semibold uppercase tracking-wide text-teal-deep">
                            Selected
                          </span>
                        ) : null}
                      </div>
                      {tableSourceSubtitle(t) ? (
                        <div className="mt-0.5 text-[11.5px] leading-snug text-ink-soft">
                          {tableSourceSubtitle(t)}
                        </div>
                      ) : null}
                      {flagSummary ? (
                        <div className="mt-1 text-[11.5px] leading-snug text-[#a65b1a]">
                          {flagSummary}
                        </div>
                      ) : null}
                    </div>
                    {/* Download in a fixed slot; status stays natural-width and right-aligned */}
                    <div className="flex flex-none items-center gap-1.5">
                      {!selectMode ? (
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
                      ) : (
                        <span className="h-7 w-7 flex-none" aria-hidden />
                      )}
                      <div className="flex h-7 w-[9.25rem] flex-none items-center justify-end">
                        {reviewed ? (
                          <Badge tone="ok">
                            <span className="inline-flex items-center gap-1">
                              <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden />
                              Reviewed
                            </span>
                          </Badge>
                        ) : (
                          <ReviewBadge
                            needed={needsReviewBadge}
                            reason={primaryReason}
                          />
                        )}
                      </div>
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
                    // Title blur persists text only — do not mark reviewed
                    // (that is reserved for "Save review").
                    onTitleCommit={(title) => patchTable(t.table_id, { title })}
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

      <div className="flex items-center justify-end gap-4">
        <Button variant="primary" disabled={continuing} onClick={requestContinueToGrouping} className="inline-flex items-center gap-1.5">
          {continuing ? 'Saving…' : (
            <>
              Continue
              <ArrowRight className="h-4 w-4" strokeWidth={2} aria-hidden />
            </>
          )}
        </Button>
      </div>
    </div>
    </PdfConsoleLayout>
  )
}
