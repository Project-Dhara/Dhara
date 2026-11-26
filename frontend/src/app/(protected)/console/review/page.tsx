'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import PdfReview from '../../../../components/pdf/PdfReview'
import { withAuthHeaders } from '../../../../lib/auth'
import { goToConsoleFiles } from '../../../../lib/consoleSession'

function ReviewBody() {
  const searchParams = useSearchParams()
  const jobId = String(searchParams.get('jobId') || '')
  const router = useRouter()
  const [filename, setFilename] = useState<string | null>(null)

  useEffect(() => {
    if (!jobId) return
    let cancelled = false
    fetch(`/api/pdf/jobs/${jobId}`, withAuthHeaders())
      .then((res) => res.json())
      .then((data) => { if (!cancelled) setFilename(data.filename) })
      .catch(() => { /* PdfReview itself surfaces a load error */ })
    return () => { cancelled = true }
  }, [jobId])

  if (!jobId) {
    return (
      <div className="p-6 text-sm text-ink-soft">
        Missing job id.{' '}
        <button type="button" className="text-teal underline" onClick={() => goToConsoleFiles(router)}>
          Back to Files
        </button>
      </div>
    )
  }

  return (
    <PdfReview
      jobId={jobId}
      filename={filename}
      onDone={() => {
        goToConsoleFiles(router)
      }}
    />
  )
}

export default function PdfReviewPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-ink-soft">Loading…</div>}>
      <ReviewBody />
    </Suspense>
  )
}
