import { useEffect, useRef, useState } from 'react'
import FileUpload from './FileUpload'
import PdfReview from './PdfReview'
import { withAuthHeaders } from '../auth'
import { withLlmKeyHeaders } from '../llmKey'

const POLL_INTERVAL_MS = 2000

const STAGE_LABELS = {
  queued: 'Queued…',
  classify: 'Scanning pages for text…',
  extract: 'Extracting tables…',
  classify_confidence: 'Checking extraction confidence…',
  validate: 'AI reconstruction & classification…',
  done: 'Complete',
}

export default function PdfUpload() {
  // idle | uploading | processing | review | error
  const [stage, setStage] = useState('idle')
  const [job, setJob] = useState(null) // {job_id, status, stage, percent, message, filename, table_count, needs_review_count}
  const [error, setError] = useState('')
  const pollRef = useRef(null)

  useEffect(() => () => clearInterval(pollRef.current), [])

  const stopPolling = () => {
    clearInterval(pollRef.current)
    pollRef.current = null
  }

  const pollJob = (jobId) => {
    pollRef.current = setInterval(async () => {
      try {
        const res = await fetch(`/api/pdf/jobs/${jobId}`, withAuthHeaders())
        if (!res.ok) throw new Error('Lost track of the processing job')
        const data = await res.json()
        setJob(data)
        if (data.status === 'done') {
          stopPolling()
          setStage('review')
        } else if (data.status === 'error') {
          stopPolling()
          setError(data.message || 'PDF processing failed')
          setStage('error')
        }
      } catch (e) {
        stopPolling()
        setError(e.message)
        setStage('error')
      }
    }, POLL_INTERVAL_MS)
  }

  const handleUpload = async (file) => {
    setError('')
    setStage('uploading')
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/pdf/upload', withAuthHeaders(withLlmKeyHeaders({ method: 'POST', body: fd })))
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Upload failed' }))
        throw new Error(err.detail || 'Upload failed')
      }
      const { job_id } = await res.json()
      setJob({ job_id, status: 'queued', stage: 'queued', percent: 0, message: 'Queued', filename: file.name })
      setStage('processing')
      pollJob(job_id)
    } catch (e) {
      setError(e.message)
      setStage('error')
    }
  }

  const reset = () => {
    stopPolling()
    setJob(null)
    setError('')
    setStage('idle')
  }

  if (stage === 'review' && job) {
    return <PdfReview jobId={job.job_id} filename={job.filename} onDone={reset} />
  }

  const busy = stage === 'uploading' || stage === 'processing'
  const percent = job?.percent ?? 0

  return (
    <div className="pdf-upload">
      <div className="batch-upload-label-row">
        <span className="batch-upload-swatch" style={{ background: 'var(--teal)' }} />
        <span className="batch-upload-label">Or upload a PDF report</span>
      </div>

      <FileUpload
        onUpload={handleUpload}
        loading={busy}
        label="Add a PDF report"
        hint="PDF — drag and drop or browse"
        accept=".pdf"
        extensionRegex={/\.pdf$/i}
        selectedName={job?.filename}
      />

      {error && <div className="error-banner"><strong>Error:</strong> {error}</div>}

      {busy && (
        <div className="pdf-upload-progress">
          <div className="progress-bar-track">
            <div className="progress-bar-fill" style={{ width: `${Math.max(4, percent)}%` }} />
          </div>
          <div className="pdf-upload-progress-row">
            <span className="pdf-upload-progress-label">
              {STAGE_LABELS[job?.stage] || 'Processing…'}
            </span>
            <span className="pdf-upload-progress-pct">{percent}%</span>
          </div>
          {job?.message && <div className="pdf-upload-progress-msg">{job.message}</div>}
        </div>
      )}

      {stage === 'error' && (
        <button className="console-secondary-btn" onClick={reset}>Try again</button>
      )}
    </div>
  )
}
