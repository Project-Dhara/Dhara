'use client'

import { useEffect, useRef, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import ProcessingStepper from '../../../../../components/console/ProcessingStepper'
import PdfConsoleLayout from '../../../../../components/pdf/PdfConsoleLayout'
import ErrorBanner from '../../../../../components/ui/ErrorBanner'
import Button from '../../../../../components/ui/Button'
import { withAuthHeaders } from '../../../../../lib/auth'
import { goToConsoleFiles } from '../../../../../lib/consoleSession'

const POLL_INTERVAL_MS = 2000

// (key, label, [rangeLow, rangeHigh]) -- ranges mirror the exact percent
// values extraction/pdf_extraction.py's run_pipeline() reports for each
// stage, used to scale the backend's single global percent into a per-row
// local 0-100% fill.
const STAGES = [
  { key: 'classify', label: 'Scanning your document to find pages with tables', range: [2, 10] as [number, number] },
  { key: 'extract', label: 'Extracting tables from the document', range: [10, 45] as [number, number] },
  { key: 'classify_confidence', label: 'Checking how confident we are in each table', range: [45, 55] as [number, number] },
  { key: 'validate', label: 'Double-checking uncertain tables with AI', range: [55, 100] as [number, number] },
]
const STAGE_ORDER = STAGES.map((s) => s.key)

type BatchFile = {
  file_job_id: string
  filename: string
  source_type: string
  status: string
  error?: string | null
  stage?: string
  percent?: number
  message?: string
}

const STAGE_LABEL: Record<string, string> = Object.fromEntries(
  STAGES.map((s) => [s.key, s.label]),
)

type Job = {
  status: string
  stage: string
  percent: number
  message?: string
  filename?: string
  is_batch?: boolean
  batch_files?: BatchFile[]
}

function buildSteps(job: Job | null, sawValidate: boolean) {
  if (!job) return STAGES.map((s) => ({ ...s, status: 'pending' }))
  const currentIdx = STAGE_ORDER.indexOf(job.stage)
  return STAGES.map((s, i) => {
    if (job.status === 'done') {
      if (s.key === 'validate' && !sawValidate) {
        return { ...s, status: 'skipped', message: 'Skipped — all tables auto-accepted, no AI review needed' }
      }
      return { ...s, status: 'done' }
    }
    if (i < currentIdx) return { ...s, status: 'done' }
    if (i === currentIdx) {
      const [lo, hi] = s.range
      const localPercent = Math.max(0, Math.min(100, Math.round(((job.percent - lo) / (hi - lo)) * 100)))
      return { ...s, status: 'active', percent: localPercent, message: job.message }
    }
    return { ...s, status: 'pending' }
  })
}

export default function PdfProcessingPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const router = useRouter()
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const sawValidateRef = useRef(false)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    let cancelled = false

    const poll = async () => {
      try {
        const res = await fetch(`/api/pdf/jobs/${jobId}`, withAuthHeaders())
        if (!res.ok) throw new Error('Lost track of this processing job')
        const data = await res.json()
        if (cancelled) return
        if (data.stage === 'validate') sawValidateRef.current = true
        setJob(data)
        if (data.status === 'done' || data.status === 'completed_with_errors') {
          if (pollRef.current) clearInterval(pollRef.current)
          router.push(`/console/review/${jobId}`)
        } else if (data.status === 'error' || data.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
          setError(data.message || 'PDF processing failed')
        }
      } catch (e: any) {
        if (!cancelled) {
          if (pollRef.current) clearInterval(pollRef.current)
          setError(e.message)
        }
      }
    }

    poll() // immediate first check, don't wait 2s for a refreshed/direct-linked page
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS)
    return () => { cancelled = true; if (pollRef.current) clearInterval(pollRef.current) }
  }, [jobId, router])

  if (error) {
    return (
      <PdfConsoleLayout jobId={jobId} step={1} maxStepReached={1}>
        <div className="mx-auto flex max-w-xl flex-col gap-4 py-8">
          <div className="font-display text-xl font-medium text-ink">Something went wrong</div>
          <ErrorBanner>{error}</ErrorBanner>
          <Button variant="primary" className="self-start" onClick={() => goToConsoleFiles(router)}>Upload a different PDF</Button>
        </div>
      </PdfConsoleLayout>
    )
  }

  // Still on Dataset Inventory → Files while extraction runs; Preview unlocks on review.
  return (
    <PdfConsoleLayout jobId={jobId} step={1} maxStepReached={1}>
      <div className="mx-auto flex max-w-xl flex-col gap-8 py-8">
        <div>
          <div className="font-display text-xl font-medium text-ink">{job?.filename || 'Processing your document'}</div>
          
        </div>
        <ProcessingStepper steps={buildSteps(job, sawValidateRef.current)} />
        {job?.is_batch && job.batch_files?.length ? (
          <ul className="flex flex-col gap-2 rounded-lg border border-line bg-white p-4 text-[13px]">
            {job.batch_files.map((f) => {
              const stageHint = f.status === 'running' && f.stage
                ? (STAGE_LABEL[f.stage] || f.message || f.stage)
                : null
              const pct = typeof f.percent === 'number' ? Math.max(0, Math.min(100, f.percent)) : null
              return (
                <li key={f.file_job_id} className="flex flex-col gap-1">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="min-w-0 truncate font-medium text-ink">{f.filename}</span>
                    <span className={`text-[12px] font-semibold uppercase tracking-wide ${
                      f.status === 'done'
                        ? 'text-green'
                        : f.status === 'error'
                          ? 'text-coral'
                          : 'text-ink-soft'
                    }`}>
                      {f.status === 'running'
                        ? (pct != null ? `${pct}%` : 'Processing…')
                        : f.status}
                    </span>
                  </div>
                  {stageHint ? (
                    <div className="truncate text-[11.5px] text-ink-soft">{stageHint}</div>
                  ) : null}
                  {f.status === 'error' && f.error ? (
                    <div className="text-[11.5px] text-coral">{f.error}</div>
                  ) : null}
                </li>
              )
            })}
          </ul>
        ) : null}
      </div>
    </PdfConsoleLayout>
  )
}
