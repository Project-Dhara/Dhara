'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { withAuthHeaders } from '../../lib/auth'
import { withLlmKeyHeaders } from '../../lib/llmKey'
import { getMetadataStandard } from '../../lib/settingsConfig'
import { beginAppendFilesMode, goToConsoleFiles } from '../../lib/consoleSession'
import { useApp } from '../../context/AppContext'
import PdfConsoleLayout from './PdfConsoleLayout'
import FilesReturnChoiceDialog from '../console/FilesReturnChoiceDialog'
import GroupingWorkspace from '../console/GroupingWorkspace'
import PostPreviewLaterSteps from '../console/PostPreviewLaterSteps'
import ConsoleStatusPlaceholder from '../console/ConsoleStatusPlaceholder'
import StageSubstepBreadcrumb from '../console/StageSubstepBreadcrumb'
import { METADATA_CRUMBS } from '../console/ConsoleStages'
import ErrorBanner from '../ui/ErrorBanner'
import KydsSummaryCard from '../KydsSummaryCard'
import { STATUS_TRANSITIONS, groupingToMetadataTransition } from '../../lib/consoleStatusTransitions'
import { fetchMineKydsFilled } from '../../lib/kydsFilled'
import {
  applySuggestedUntitledMerge,
  fillGroupMetadataForMatchResult,
  matchResultToPdfSavePayload,
  pdfGroupingToMatchResult,
} from '../../lib/postPreview'
import Button from '../ui/Button'
import { namesFromMatchResult } from '../../lib/existingDatasetNames'

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
    // Never clobber a populated grouping with a null/empty snapshot (Dashboard
    // deep-links set pipelineStep early; a premature save would wipe tables).
    let next = state
    if (!matchResultHasTables(state?.matchResult)) {
      const prev = loadPdfPipeline(jobId)
      if (matchResultHasTables(prev?.matchResult)) {
        next = {
          ...state,
          matchResult: prev.matchResult,
          autoSnapshot: state?.autoSnapshot || prev.autoSnapshot || prev.matchResult,
        }
      }
    }
    sessionStorage.setItem(pdfPipelineStorageKey(jobId), JSON.stringify(next))
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

/** Dashboard deep-link: /console/grouping?jobId=…&step=4 (Grouping shell steps 3–7). */
function parsePipelineStepParam(raw) {
  const n = Number.parseInt(String(raw ?? ''), 10)
  if (!Number.isFinite(n) || n < 3 || n > 7) return null
  return n
}

function matchResultHasTables(mr) {
  if (!mr || typeof mr !== 'object') return false
  const grouped = (mr.groups || []).reduce(
    (n, g) => n + ((g.matched_tables || g.tables || []).length),
    0,
  )
  const unmatched = (mr.unmatched_tables || mr.unmatched || []).length
  return grouped + unmatched > 0
}

function serverGroupingHasTables(data) {
  if (!data || typeof data !== 'object') return false
  const grouped = (data.groups || []).reduce(
    (n, g) => n + ((g.tables || []).length),
    0,
  )
  const unmatched = (data.unmatched_tables || data.unmatched || []).length
  return grouped + unmatched > 0
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
  const searchParams = useSearchParams()
  const { keySaved, settings, invalidateDashboard, invalidateCatalogue } = useApp()
  const isSelfHosted = String(settings?.provider || '').toLowerCase() === 'self-hosted'
  const persisted = loadPdfPipeline(jobId)
  const requestedStep = useMemo(
    () => parsePipelineStepParam(searchParams?.get('step')),
    [searchParams],
  )
  const initialStep = requestedStep ?? persisted?.pipelineStep ?? 3

  const [filename, setFilename] = useState(persisted?.filename ?? '')
  const [method, setMethod] = useState(persisted?.method ?? null)
  const [loading, setLoading] = useState(!persisted?.matchResult)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [manualGrouping, setManualGrouping] = useState(persisted?.manualGrouping ?? false)
  const [editingGroups, setEditingGroups] = useState(false)
  const [autoSnapshot, setAutoSnapshot] = useState(persisted?.autoSnapshot ?? null)
  const [toast, setToast] = useState(null)
  const [suggestedMerges, setSuggestedMerges] = useState(
    () => (Array.isArray(persisted?.suggestedMerges) ? persisted.suggestedMerges : []),
  )

  const [pipelineStep, setPipelineStep] = useState(initialStep)
  const [filesReturnOpen, setFilesReturnOpen] = useState(false)
  const [maxStepReached, setMaxStepReached] = useState(
    Math.max(persisted?.maxStepReached ?? 3, initialStep),
  )
  const [matchResult, setMatchResult] = useState(persisted?.matchResult ?? null)
  const [metadataFilling, setMetadataFilling] = useState(false)
  const [metaLabel, setMetaLabel] = useState(persisted?.metaLabel ?? '')
  const [metadataId, setMetadataId] = useState(persisted?.metadataId ?? null)
  const [metadataIds, setMetadataIds] = useState(persisted?.metadataIds ?? [])
  const [metadataStarted, setMetadataStarted] = useState(
    Boolean(persisted?.matchResult && initialStep >= 4) || initialStep >= 4,
  )
  const [statusPage, setStatusPage] = useState(null)
  const [classificationComplete, setClassificationComplete] = useState(false)
  const goToHarmRef = useRef(null)
  const continueOkRef = useRef(false)
  const appliedQueryStepRef = useRef(false)

  useEffect(() => {
    if (pipelineStep === 4) setMetadataStarted(true)
  }, [pipelineStep])

  // Honour Dashboard ?step= once grouping data is available (metadata+ need matchResult).
  useEffect(() => {
    if (appliedQueryStepRef.current || requestedStep == null) return
    if (requestedStep >= 4 && !matchResult) return
    appliedQueryStepRef.current = true
    setPipelineStep(requestedStep)
    setMaxStepReached((prev) => Math.max(prev, requestedStep))
    if (requestedStep >= 4) setMetadataStarted(true)
  }, [requestedStep, matchResult])

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
      suggestedMerges,
    })
  }, [
    jobId, filename, method, manualGrouping, autoSnapshot,
    pipelineStep, maxStepReached, matchResult, metaLabel, metadataId, metadataIds,
    suggestedMerges,
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
    const suggestions = Array.isArray(data?.suggested_merges) ? data.suggested_merges : []
    setSuggestedMerges(suggestions)
    return next
  }, [filename, jobId])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const localHasTables = matchResultHasTables(persisted?.matchResult)
      // Only skip the loading flash when we already have tables to show.
      // (pipelineStep alone is not enough — Dashboard ?step= used to trip that.)
      if (!localHasTables) setLoading(true)
      setError('')
      try {
        const hydrateFromPersist = async () => {
          const persistRes = await fetch(
            `/api/pdf/jobs/${jobId}/persist-approved`,
            withLlmKeyHeaders(withAuthHeaders({ method: 'POST' })),
          )
          if (!persistRes.ok) {
            const body = await persistRes.json().catch(() => ({}))
            throw new Error(body.detail || 'Could not persist tables for grouping')
          }
          const persistedJob = await persistRes.json()
          if (cancelled) return null
          applyServerGrouping(persistedJob.grouping || persistedJob, persistedJob.filename)
          setToast('Tables saved to Postgres and grouped by title.')
          return persistedJob
        }

        const res = await fetch(`/api/pdf/jobs/${jobId}/grouping`, withAuthHeaders())
        if (res.status === 409) {
          await hydrateFromPersist()
          return
        }
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          throw new Error(body.detail || 'Could not load grouping')
        }
        const data = await res.json()
        if (cancelled) return

        // Keep local edits only when sessionStorage still has real tables.
        // A high pipelineStep with an empty matchResult (Dashboard ?step= race)
        // must not block applying the server grouping.
        if (localHasTables) {
          if (!autoSnapshot && serverGroupingHasTables(data)) {
            const snap = pdfGroupingToMatchResult(
              toClientGrouping(data),
              data.filename || filename || 'pdf',
              jobId,
            )
            setAutoSnapshot(snap)
            if (data.method) setMethod(data.method)
            if (data.filename) setFilename(data.filename)
          }
          return
        }

        if (serverGroupingHasTables(data)) {
          applyServerGrouping(data, data.filename)
          return
        }

        // Preview has tables but grouping rows are empty/missing — rebuild.
        await hydrateFromPersist()
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
          isSelfHosted,
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

    const hasKyds = await fetchMineKydsFilled()
    setStatusPage({
      ...groupingToMetadataTransition(hasKyds),
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

  const requestHarmonisation = () => {
    if (goToHarmRef.current) goToHarmRef.current()
    else if (classificationComplete) {
      setPipelineStep(6)
      setMaxStepReached((prev) => Math.max(prev, 6))
    }
  }

  const existingFilenames = namesFromMatchResult(matchResult, filename)

  const goToPipelineStep = (targetStep) => {
    if (targetStep === 1) {
      setFilesReturnOpen(true)
      return
    }
    if (targetStep === 2) {
      router.push(`/console/review?jobId=${encodeURIComponent(jobId)}`)
      return
    }
    if (targetStep === 3) {
      setPipelineStep(3)
      return
    }
    if (targetStep === 6) {
      requestHarmonisation()
      return
    }
    if (targetStep >= 4 && targetStep <= maxStepReached) {
      if (targetStep === 4 && !matchResult) return
      setPipelineStep(targetStep)
    }
  }

  const isStepReachable = (s) => {
    if (s === 6) return classificationComplete
    return s <= maxStepReached
  }

  const tableCount = matchResult
    ? (matchResult.groups || []).reduce((n, g) => n + (g.matched_tables?.length || 0), 0)
      + (matchResult.unmatched_tables || []).length
    : 0

  const filesReturnDialog = (
    <FilesReturnChoiceDialog
      open={filesReturnOpen}
      onCancel={() => setFilesReturnOpen(false)}
      onAddMore={() => {
        setFilesReturnOpen(false)
        beginAppendFilesMode(router, {
          jobId,
          existingFilenames,
          returnPath: `/console/review?jobId=${encodeURIComponent(jobId)}`,
        })
      }}
      onStartOver={() => {
        setFilesReturnOpen(false)
        clearPdfPipeline(jobId)
        goToConsoleFiles(router)
      }}
    />
  )

  if (statusPage) {
    return (
      <>
        {filesReturnDialog}
        <PdfConsoleLayout
          jobId={jobId}
          step={pipelineStep}
          maxStepReached={maxStepReached}
          onGoToStep={goToPipelineStep}
          isStepReachable={isStepReachable}
          existingFilenames={existingFilenames}
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
      </>
    )
  }

  return (
    <>
      {filesReturnDialog}
      <PdfConsoleLayout
      jobId={jobId}
      step={pipelineStep}
      existingFilenames={existingFilenames}
      maxStepReached={maxStepReached}
      onGoToStep={goToPipelineStep}
      isStepReachable={isStepReachable}
    >
      {pipelineStep === 3 && (
        <div className="flex flex-col gap-[18px]">
          <div className="flex items-start justify-between gap-6">
            <div className="min-w-0">
              <StageSubstepBreadcrumb
                crumbs={METADATA_CRUMBS}
                activeId="grouping"
                onNavigate={(next) => {
                  if (next === 'metadata') goToPipelineStep(4)
                }}
                isReachable={(crumb) => crumb.id === 'grouping' || maxStepReached >= 4}
                ariaLabel="Metadata workspace"
                size="page"
              />
              <div className="mt-1.5 text-[13px] font-medium text-ink">
                {filename || 'PDF report'}
                <span className="font-normal text-ink-soft">
                  {' '}
                  · {tableCount} table(s)
                  {method ? ` · ${method}` : ''}
                </span>
              </div>
            </div>
            <div className="flex flex-none flex-shrink-0 flex-wrap items-center justify-end gap-2.5">
              <KydsSummaryCard variant="corner" />
            </div>
          </div>

          <div className="flex flex-col gap-5 rounded-xl border border-line bg-white p-5 shadow-sm sm:p-6">
            {error && <ErrorBanner>{error}</ErrorBanner>}
            {suggestedMerges.length > 0 ? (
              <div className="flex flex-col gap-3 rounded-xl border border-line bg-sage/40 p-4">
                <div className="text-[15px] font-semibold text-ink">Suggested merges</div>
                <div className="text-[13px] text-ink-soft">
                  Untitled tables that share the same domain, entity, and table type.
                  Confirm to merge; dismiss to leave them as singletons. Wrong merges are worse than leaving them alone.
                </div>
                <ul className="m-0 flex list-none flex-col gap-3 p-0">
                  {suggestedMerges.map((s, idx) => (
                    <li
                      key={`${(s.table_ids || []).join('-')}-${idx}`}
                      className="flex flex-col gap-2 rounded-lg border border-line bg-white p-3 sm:flex-row sm:items-center sm:justify-between"
                    >
                      <div className="min-w-0 text-[13px] text-ink">
                        <div className="font-medium">
                          {(s.table_ids || []).length} untitled tables
                        </div>
                        <div className="text-ink-soft">{s.reason || 'Structural cue match'}</div>
                      </div>
                      <div className="flex flex-none flex-wrap gap-2">
                        <Button
                          variant="primary"
                          onClick={() => {
                            const ids = s.table_ids || []
                            setMatchResult((prev) => {
                              const next = applySuggestedUntitledMerge(prev, ids)
                              setAutoSnapshot(next)
                              return next
                            })
                            setSuggestedMerges((prev) => prev.filter((_, i) => i !== idx))
                            setToast('Suggestion applied — review the new group before continuing.')
                          }}
                        >
                          Confirm
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setSuggestedMerges((prev) => prev.filter((_, i) => i !== idx))
                          }}
                        >
                          Dismiss
                        </Button>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
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
              idColumnLabel="Dataset ID"
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
          onClassifyPhaseChange={(next) => {
            if (next === 'harmonisation') {
              setPipelineStep(6)
              setMaxStepReached((prev) => Math.max(prev, 6))
            } else if (next === 'classification') {
              setPipelineStep(5)
            }
          }}
          onClassificationCompleteChange={setClassificationComplete}
          onRegisterGoToHarmonisation={(fn) => { goToHarmRef.current = fn }}
          classificationComplete={classificationComplete}
          onClassifyContinue={() => {
            setStatusPage({
              ...STATUS_TRANSITIONS.classifyToPublish,
              key: 'classifyToPublish',
              after: () => {
                setStatusPage(null)
                setPipelineStep(7)
                setMaxStepReached((prev) => Math.max(prev, 7))
              },
            })
          }}
          showClassifyHeading
          onGoSettings={() => router.push('/settings')}
          onGoDashboard={() => {
            invalidateDashboard()
            router.push('/dashboard')
          }}
          onGoCatalogue={() => {
            invalidateCatalogue()
            router.push('/catalogue')
          }}
          onUploadAnother={() => {
            clearPdfPipeline(jobId)
            goToConsoleFiles(router)
          }}
          onMatchResultChange={setMatchResult}
        />
      )}
    </PdfConsoleLayout>
    </>
  )
}
