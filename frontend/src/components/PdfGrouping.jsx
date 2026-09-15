'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { ArrowLeft } from 'lucide-react'
import { withAuthHeaders } from '../lib/auth'
import { withLlmKeyHeaders } from '../lib/llmKey'
import { getMetadataStandard } from '../lib/settingsConfig'
import { clearConsoleSession } from '../lib/consoleSession'
import { useApp } from '../context/AppContext'
import PdfConsoleLayout from './PdfConsoleLayout'
import GroupingWorkspace from './GroupingWorkspace'
import PostPreviewLaterSteps from './PostPreviewLaterSteps'
import ConsoleStatusPlaceholder from './ConsoleStatusPlaceholder'
import ErrorBanner from './ui/ErrorBanner'
import { STATUS_TRANSITIONS } from '../lib/consoleStatusTransitions'
import {
  fillGroupMetadataForMatchResult,
  matchResultToPdfSavePayload,
  pdfGroupingToMatchResult,
} from '../lib/postPreview'

function pdfPipelineStorageKey(jobId) {
  return `dhara_pdf_pipeline_v1_${jobId}`
}

function loadPdfPipeline(jobId) {
  try {
    const raw = sessionStorage.getItem(pdfPipelineStorageKey(jobId))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : null
  } catch {
    return null
  }
}

function savePdfPipeline(jobId, state) {
  try {
    sessionStorage.setItem(pdfPipelineStorageKey(jobId), JSON.stringify(state))
  } catch {
    // best-effort
  }
}

function clearPdfPipeline(jobId) {
  try {
    sessionStorage.removeItem(pdfPipelineStorageKey(jobId))
  } catch {
    // best-effort
  }
}

function toClientGrouping(data) {
  return {
    groups: (data.groups || []).map((g) => ({
      group_id: g.group_id,
      name: g.name,
      tables: g.tables || [],
    })),
    unmatched: data.unmatched_tables || data.unmatched || [],
    method: data.method,
  }
}

/**
 * PDF post-preview shell: load/persist job grouping, then the same shared
 * GroupingWorkspace → metadata → classify → publish flow as Excel/SQL.
 */
export default function PdfGrouping({ jobId }) {
  const router = useRouter()
  const { keySaved } = useApp()
  const persisted = loadPdfPipeline(jobId)

  const [filename, setFilename] = useState(persisted?.filename ?? '')
  const [method, setMethod] = useState(persisted?.method ?? null)
  const [loading, setLoading] = useState(!persisted?.matchResult)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [manualGrouping, setManualGrouping] = useState(persisted?.manualGrouping ?? false)
  const [editingGroups, setEditingGroups] = useState(false)
  const [autoSnapshot, setAutoSnapshot] = useState(persisted?.autoSnapshot ?? null)
  const [toast, setToast] = useState(null)

  const [pipelineStep, setPipelineStep] = useState(persisted?.pipelineStep ?? 3)
  const [maxStepReached, setMaxStepReached] = useState(persisted?.maxStepReached ?? 3)
  const [matchResult, setMatchResult] = useState(persisted?.matchResult ?? null)
  const [metadataFilling, setMetadataFilling] = useState(false)
  const [metaLabel, setMetaLabel] = useState(persisted?.metaLabel ?? '')
  const [metadataId, setMetadataId] = useState(persisted?.metadataId ?? null)
  const [metadataIds, setMetadataIds] = useState(persisted?.metadataIds ?? [])
  const [metadataStarted, setMetadataStarted] = useState(
    Boolean(persisted?.matchResult && (persisted?.pipelineStep ?? 3) >= 4),
  )
  const [statusPage, setStatusPage] = useState(null)
  const continueOkRef = useRef(false)

  useEffect(() => {
    if (pipelineStep === 4) setMetadataStarted(true)
  }, [pipelineStep])

  useEffect(() => {
    savePdfPipeline(jobId, {
      filename,
      method,
      manualGrouping,
      autoSnapshot,
      pipelineStep,
      maxStepReached,
      matchResult,
      metaLabel,
      metadataId,
      metadataIds,
    })
  }, [
    jobId, filename, method, manualGrouping, autoSnapshot,
    pipelineStep, maxStepReached, matchResult, metaLabel, metadataId, metadataIds,
  ])

  useEffect(() => {
    if (!jobId || pipelineStep < 3) return undefined
    let cancelled = false
    ;(async () => {
      try {
        await fetch(
          `/api/pdf/jobs/${encodeURIComponent(jobId)}/pipeline`,
          withAuthHeaders({
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ step: pipelineStep }),
          }),
        )
      } catch {
        if (!cancelled) { /* best-effort */ }
      }
    })()
    return () => { cancelled = true }
  }, [jobId, pipelineStep])

  const applyServerGrouping = useCallback((data, sourceFile) => {
    const client = toClientGrouping(data)
    const next = pdfGroupingToMatchResult(
      { groups: client.groups, unmatched: client.unmatched, method: client.method },
      sourceFile || data.filename || filename || 'pdf',
      jobId,
    )
    setMatchResult(next)
    setAutoSnapshot(next)
    if (client.method) setMethod(client.method)
    if (data.filename) setFilename(data.filename)
    return next
  }, [filename, jobId])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const hadPersistedPipeline = Boolean(persisted?.matchResult || (persisted?.pipelineStep ?? 3) > 3)
      if (!hadPersistedPipeline) setLoading(true)
      setError('')
      try {
        const res = await fetch(`/api/pdf/jobs/${jobId}/grouping`, withAuthHeaders())
        if (res.status === 409) {
          const persistRes = await fetch(
            `/api/pdf/jobs/${jobId}/persist-approved`,
            withLlmKeyHeaders(withAuthHeaders({ method: 'POST' })),
          )
          if (!persistRes.ok) {
            const body = await persistRes.json().catch(() => ({}))
            throw new Error(body.detail || 'Could not persist tables for grouping')
          }
          const persistedJob = await persistRes.json()
          if (cancelled) return
          applyServerGrouping(persistedJob.grouping || persistedJob, persistedJob.filename)
          setToast('Tables saved to Postgres and grouped by title.')
          return
        }
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || 'Could not load grouping')
        }
        const data = await res.json()
        if (cancelled) return
        const keepLocal = Boolean(
          persisted?.matchResult
          || (persisted?.pipelineStep ?? 3) > 3
          || (persisted?.manualGrouping && persisted?.matchResult),
        )
        if (!keepLocal) {
          applyServerGrouping(data, data.filename)
        } else if (!autoSnapshot && data.groups) {
          const snap = pdfGroupingToMatchResult(toClientGrouping(data), data.filename || filename || 'pdf', jobId)
          setAutoSnapshot(snap)
          if (data.method) setMethod(data.method)
          if (data.filename) setFilename(data.filename)
        }
      } catch (e) {
        if (!cancelled) setError(e.message || 'Failed to load grouping')
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId, applyServerGrouping])

  useEffect(() => {
    if (!toast) return undefined
    const t = setTimeout(() => setToast(null), 5000)
    return () => clearTimeout(t)
  }, [toast])

  const runPropose = async (reindex = false) => {
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
      applyServerGrouping(data, filename || data.filename)
      setManualGrouping(false)
      setEditingGroups(false)
      setToast(
        data.method === 'sdg_goal'
          ? 'Automatic grouping updated (SDG-wise).'
          : data.method === 'title_base' || String(data.method || '').startsWith('title_base')
            ? 'Automatic grouping updated (by title).'
            : `Automatic grouping updated (${data.method || 'title'}).`,
      )
    } catch (e) {
      setError(e.message || 'Propose failed')
    } finally {
      setSaving(false)
    }
  }

  const handleRequestAutomatic = () => {
    if (autoSnapshot) {
      setMatchResult(autoSnapshot)
      setManualGrouping(false)
      setEditingGroups(false)
      return
    }
    runPropose(false)
  }

  const saveAndContinue = async () => {
    if (!matchResult) return
    if ((matchResult.unmatched_tables || []).length > 0) {
      setToast('Assign every table to a group before continuing.')
      return
    }
    if (!(matchResult.groups || []).length) {
      setToast('Create at least one group before continuing.')
      return
    }
    if (metadataFilling || saving || statusPage) return

    setSaving(true)
    setMetadataFilling(true)
    setError('')
    setToast(null)

    const fillWork = async () => {
      try {
        const payload = matchResultToPdfSavePayload(matchResult)
        const res = await fetch(
          `/api/pdf/jobs/${jobId}/grouping`,
          withAuthHeaders({
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          }),
        )
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || 'Could not save grouping')
        }

        const filled = await fillGroupMetadataForMatchResult(matchResult, {
          withAuthHeaders,
          withLlmKeyHeaders,
          getMetadataStandard,
        })
        setMatchResult(filled.matchResult)
        if (filled.toast) setToast(filled.toast)
      } catch (e) {
        setError(e.message || 'Could not continue to metadata')
        setToast(e.message || 'Could not auto-fill metadata')
        throw e
      } finally {
        setSaving(false)
        setMetadataFilling(false)
      }
    }

    continueOkRef.current = false
    const trackedFillWork = async () => {
      try {
        await fillWork()
        continueOkRef.current = true
      } catch (_) {
        continueOkRef.current = false
      }
    }

    setStatusPage({
      ...STATUS_TRANSITIONS.groupingToMetadata,
      key: 'groupingToMetadata',
      work: trackedFillWork,
      after: () => {
        setStatusPage(null)
        if (continueOkRef.current) {
          setPipelineStep(4)
          setMaxStepReached((prev) => Math.max(prev, 4))
        }
      },
    })
  }

  const goToPipelineStep = (targetStep) => {
    if (targetStep === 1) {
      clearConsoleSession()
      router.push('/console')
      return
    }
    if (targetStep === 2) {
      router.push(`/console/review/${jobId}`)
      return
    }
    if (targetStep === 3) {
      setPipelineStep(3)
      return
    }
    if (targetStep >= 4 && targetStep <= maxStepReached) {
      if (targetStep === 4 && !matchResult) return
      setPipelineStep(targetStep)
    }
  }

  const tableCount = matchResult
    ? (matchResult.groups || []).reduce((n, g) => n + (g.matched_tables?.length || 0), 0)
      + (matchResult.unmatched_tables || []).length
    : 0

  if (statusPage) {
    return (
      <PdfConsoleLayout
        jobId={jobId}
        step={pipelineStep}
        maxStepReached={maxStepReached}
        onGoToStep={goToPipelineStep}
      >
        <div className="rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
          <ConsoleStatusPlaceholder
            key={statusPage.key}
            title={statusPage.title}
            subtitle={statusPage.subtitle}
            steps={statusPage.steps}
            work={statusPage.work || null}
            onComplete={statusPage.after}
          />
        </div>
      </PdfConsoleLayout>
    )
  }

  return (
    <PdfConsoleLayout
      jobId={jobId}
      step={pipelineStep}
      maxStepReached={maxStepReached}
      onGoToStep={goToPipelineStep}
    >
      {pipelineStep === 3 && (
        <div className="flex flex-col gap-[18px]">
          <div className="min-w-0">
            <button
              type="button"
              className="mb-3.5 inline-flex items-center gap-1.5 text-[15px] font-semibold text-teal hover:text-teal-dark"
              onClick={() => router.push(`/console/review/${jobId}`)}
            >
              <ArrowLeft className="h-4 w-4" strokeWidth={2} aria-hidden />
              Back to preview
            </button>
            <div className="font-display text-[26px] font-medium leading-tight text-ink">Group tables</div>
            <div className="mt-1.5 text-[13px] font-medium text-ink">
              {filename || 'PDF report'}
              <span className="font-normal text-ink-soft">
                {' '}
                · {tableCount} table(s)
                {method ? ` · ${method}` : ''}
              </span>
            </div>
          </div>

          <div className="flex flex-col gap-5 rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
            {error && <ErrorBanner>{error}</ErrorBanner>}
            <GroupingWorkspace
              matchResult={matchResult}
              onMatchResultChange={setMatchResult}
              manualGrouping={manualGrouping}
              onManualGroupingChange={setManualGrouping}
              editingGroups={editingGroups}
              onEditingGroupsChange={setEditingGroups}
              autoSnapshot={autoSnapshot}
              onRequestAutomatic={handleRequestAutomatic}
              onContinueToMetadata={saveAndContinue}
              metadataFilling={metadataFilling || saving}
              loading={loading}
              error=""
              toast={toast}
              onDismissToast={() => setToast(null)}
              preferTableId
              titleColumnLabel="Title"
              continueDisabled={saving}
            />
          </div>
        </div>
      )}

      {pipelineStep >= 4 && (
        <PostPreviewLaterSteps
          step={pipelineStep}
          matchResult={matchResult}
          pdfJobId={jobId}
          metadataFiles={[]}
          metadataStarted={metadataStarted}
          metaLabel={metaLabel}
          metadataId={metadataId}
          metadataIds={metadataIds}
          datasetLabel={filename || 'This dataset'}
          hasKey={keySaved}
          showMetadataHeading
          onBackToGrouping={() => setPipelineStep(3)}
          onMetadataDone={(label, ids) => {
            setMetaLabel(label || filename || 'PDF release')
            setMetadataIds(ids || [])
            setMetadataId((ids && ids[0]) || null)
            setStatusPage({
              ...STATUS_TRANSITIONS.metadataToClassify,
              key: 'metadataToClassify',
              after: () => {
                setStatusPage(null)
                setPipelineStep(5)
                setMaxStepReached((prev) => Math.max(prev, 5))
              },
            })
          }}
          onClassifyContinue={() => {
            setStatusPage({
              ...STATUS_TRANSITIONS.classifyToPublish,
              key: 'classifyToPublish',
              after: () => {
                setStatusPage(null)
                setPipelineStep(6)
                setMaxStepReached((prev) => Math.max(prev, 6))
              },
            })
          }}
          onGoSettings={() => router.push('/settings')}
          onGoDashboard={() => router.push('/dashboard')}
          onGoCatalogue={() => router.push('/catalogue')}
          onUploadAnother={() => {
            clearPdfPipeline(jobId)
            clearConsoleSession()
            router.push('/console')
          }}
        />
      )}
    </PdfConsoleLayout>
  )
}
