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

type StageDef = {
  key: string
  label: string
  range: [number, number]
}

// Ranges mirror extraction progress percents; labels vary by source type so
// Excel/CSV waiting/running jobs do not show PDF "pages" copy.
const PDF_STAGES: StageDef[] = [
  { key: 'classify', label: 'Scanning your document to find pages with tables', range: [2, 10] },
  { key: 'extract', label: 'Extracting tables from the document', range: [10, 45] },
  { key: 'classify_confidence', label: 'Checking how confident we are in each table', range: [45, 55] },
  { key: 'validate', label: 'Double-checking uncertain tables with AI', range: [55, 100] },
]

const SPREADSHEET_STAGES: StageDef[] = [
  { key: 'classify', label: 'Reading your spreadsheet and locating tables', range: [2, 10] },
  { key: 'extract', label: 'Extracting tables from sheets', range: [10, 45] },
  { key: 'classify_confidence', label: 'Checking table structure and quality', range: [45, 55] },
  { key: 'validate', label: 'Reviewing uncertain tables', range: [55, 100] },
]

const MIXED_STAGES: StageDef[] = [
  { key: 'classify', label: 'Scanning uploaded files for tables', range: [2, 10] },
  { key: 'extract', label: 'Extracting tables from your files', range: [10, 45] },
  { key: 'classify_confidence', label: 'Checking how confident we are in each table', range: [45, 55] },
  { key: 'validate', label: 'Reviewing uncertain tables', range: [55, 100] },
]

const STAGE_ORDER = PDF_STAGES.map((s) => s.key)

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

type Job = {
  status: string
  stage: string
  percent: number
  message?: string
  filename?: string
  source_type?: string
  is_batch?: boolean
  batch_files?: BatchFile[]
  table_count?: number
  error?: string
}

type SourceKind = 'pdf' | 'spreadsheet' | 'mixed'

function stagesForKind(kind: SourceKind): StageDef[] {
  if (kind === 'spreadsheet') return SPREADSHEET_STAGES
  if (kind === 'mixed') return MIXED_STAGES
  return PDF_STAGES
}

function stageLabelMap(kind: SourceKind): Record<string, string> {
  return Object.fromEntries(stagesForKind(kind).map((s) => [s.key, s.label]))
}

function kindFromSourceType(sourceType?: string | null): SourceKind | null {
  const st = String(sourceType || '').toLowerCase()
  if (st === 'excel' || st === 'csv') return 'spreadsheet'
  if (st === 'pdf') return 'pdf'
  return null
}

function kindFromFilename(filename?: string | null): SourceKind | null {
  const name = String(filename || '').toLowerCase()
  if (/\.(xlsx?|xlsm|xls|csv|tsv)$/.test(name)) return 'spreadsheet'
  if (name.endsWith('.pdf')) return 'pdf'
  return null
}

/** Infer UI copy family without changing backend progress stages. */
function inferSourceKind(job: Job | null): SourceKind {
  if (!job) return 'pdf'
  const direct = kindFromSourceType(job.source_type)
  if (direct) return direct

  if (job.is_batch || String(job.source_type || '').toLowerCase() === 'batch') {
    const types = new Set(
      (job.batch_files || [])
        .map((f) => String(f.source_type || '').toLowerCase())
        .filter(Boolean),
    )
    const hasPdf = types.has('pdf')
    const hasSheet = types.has('excel') || types.has('csv')
    if (hasPdf && hasSheet) return 'mixed'
    if (hasSheet) return 'spreadsheet'
    if (hasPdf) return 'pdf'
    // Fall back to per-file names when source_type is missing on children.
    const nameKinds = (job.batch_files || [])
      .map((f) => kindFromFilename(f.filename))
      .filter(Boolean) as SourceKind[]
    if (nameKinds.length) {
      const set = new Set(nameKinds)
      if (set.has('pdf') && set.has('spreadsheet')) return 'mixed'
      if (set.has('spreadsheet')) return 'spreadsheet'
      if (set.has('pdf')) return 'pdf'
    }
  }

  return kindFromFilename(job.filename) || 'pdf'
}

function buildSteps(job: Job | null, sawValidate: boolean) {
  const kind = inferSourceKind(job)
  const stages = stagesForKind(kind)
  if (!job) return stages.map((s) => ({ ...s, status: 'pending' as const }))
  // queued / claimed are not pipeline stages — without this the stepper stays
  // entirely pending and looks stuck even though the worker will pick the job up.
  if (
    job.status === 'queued'
    || job.stage === 'queued'
    || job.stage === 'claimed'
  ) {
    const waitingMsg =
      job.message
      || (job.stage === 'claimed'
        ? 'Worker claimed this job — starting extraction…'
        : 'Waiting for the extraction worker…')
    return stages.map((s, i) => (
      i === 0
        ? { ...s, status: 'active' as const, message: waitingMsg }
        : { ...s, status: 'pending' as const }
    ))
  }
  const currentIdx = STAGE_ORDER.indexOf(job.stage)
  return stages.map((s, i) => {
    if (job.status === 'done') {
      if (s.key === 'validate' && !sawValidate) {
        return {
          ...s,
          status: 'skipped' as const,
          message: kind === 'pdf'
            ? 'Skipped — all tables auto-accepted, no AI review needed'
            : 'Skipped — all tables auto-accepted',
        }
      }
      return { ...s, status: 'done' as const }
    }
    if (i < currentIdx) return { ...s, status: 'done' as const }
    if (i === currentIdx) {
      const [lo, hi] = s.range
      const localPercent = Math.max(0, Math.min(100, Math.round(((job.percent - lo) / (hi - lo)) * 100)))
      return { ...s, status: 'active' as const, percent: localPercent, message: job.message }
    }
    return { ...s, status: 'pending' as const }
  })
}

function fileStatusLabel(f: BatchFile): string {
  if (f.status === 'running') {
    const pct = typeof f.percent === 'number' ? Math.max(0, Math.min(100, f.percent)) : null
    return pct != null ? `${pct}%` : 'Processing…'
  }
  if (f.status === 'queued') return 'Waiting'
  return f.status
}

function fileStageHint(f: BatchFile): string | null {
  if (f.status === 'running' && f.stage) {
    const kind = kindFromSourceType(f.source_type) || kindFromFilename(f.filename) || 'pdf'
    return stageLabelMap(kind)[f.stage] || f.message || f.stage
  }
  if (f.status === 'queued') return f.message || 'Waiting for extraction worker'
  return null
}

export default function PdfProcessingPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const router = useRouter()
  const [job, setJob] = useState<Job | null>(null)
  const [error, setError] = useState('')
  const [noTables, setNoTables] = useState(false)
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
          // Extraction finished with nothing usable — stop before Preview/Grouping.
          if (Number(data.table_count) === 0) {
            setNoTables(true)
            return
          }
          router.push(`/console/review/${jobId}`)
        } else if (data.status === 'cancelled') {
          if (pollRef.current) clearInterval(pollRef.current)
          goToConsoleFiles(router)
        } else if (data.status === 'error' || data.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current)
          const msg = String(data.message || data.error || '')
          if (/no tables/i.test(msg)) {
            setNoTables(true)
          } else {
            setError(msg || 'Processing failed')
          }
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

  const sourceKind = inferSourceKind(job)
  const uploadCta = sourceKind === 'spreadsheet'
    ? 'Upload a different file'
    : sourceKind === 'mixed'
      ? 'Upload different files'
      : 'Upload a different PDF'

  const existingFilenames = job?.filename
    ? [job.filename]
    : (job?.batch_files || []).map((f) => f.filename).filter(Boolean)

  const filesLayoutProps = {
    jobId,
    step: 1 as const,
    maxStepReached: 1,
    askBeforeLeaveFiles: true,
    cancelJobOnStartOver: true,
    existingFilenames,
    filesReturnPath: `/console/processing/${jobId}`,
    filesReturnTitle: 'File still processing',
    filesReturnBody: (
      <>
        This upload is still running. You can add more files while it continues, or start
        over with a new upload (this cancels the current job).
      </>
    ),
  }

  if (error) {
    return (
      <PdfConsoleLayout {...filesLayoutProps}>
        <div className="mx-auto flex max-w-xl flex-col gap-4 py-8">
          <div className="font-display text-xl font-medium text-ink">Something went wrong</div>
          <ErrorBanner>{error}</ErrorBanner>
          <Button variant="primary" className="self-start" onClick={() => goToConsoleFiles(router)}>
            {uploadCta}
          </Button>
        </div>
      </PdfConsoleLayout>
    )
  }

  if (noTables) {
    return (
      <PdfConsoleLayout {...filesLayoutProps}>
        <div className="mx-auto flex max-w-xl flex-col gap-4 py-8">
          <div className="font-display text-xl font-medium text-ink">No tables found</div>
          <p className="m-0 text-[14px] leading-relaxed text-ink-soft">
            No tables were extracted from{' '}
            <span className="font-medium text-ink">{job?.filename || 'this file'}</span>.
            Upload another file or try again with a different document.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button variant="primary" onClick={() => goToConsoleFiles(router)}>
              Upload another file
            </Button>
            <Button variant="secondary" onClick={() => goToConsoleFiles(router)}>
              Try again
            </Button>
          </div>
        </div>
      </PdfConsoleLayout>
    )
  }

  // Still on Dataset Inventory → Files while extraction runs; Preview unlocks on review.
  return (
    <PdfConsoleLayout {...filesLayoutProps}>
      <div className="mx-auto flex max-w-xl flex-col gap-8 py-8">
        <div>
          <div className="font-display text-xl font-medium text-ink">{job?.filename || 'Processing your document'}</div>
          
        </div>
        <ProcessingStepper steps={buildSteps(job, sawValidateRef.current)} />
        {job?.is_batch && job.batch_files?.length ? (
          <ul className="flex flex-col gap-2 rounded-lg border border-line bg-white p-4 text-[13px]">
            {job.batch_files.map((f) => {
              const stageHint = fileStageHint(f)
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
                      {fileStatusLabel(f)}
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
