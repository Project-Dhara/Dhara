'use client'

import { useEffect, useState } from 'react'
import { useParams, useRouter } from 'next/navigation'
import PdfReview from '../../../../../components/pdf/PdfReview'
import { withAuthHeaders } from '../../../../../lib/auth'
import { goToConsoleFiles } from '../../../../../lib/consoleSession'

export default function PdfReviewPage() {
  const { jobId } = useParams<{ jobId: string }>()
  const router = useRouter()
  const [filename, setFilename] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetch(`/api/pdf/jobs/${jobId}`, withAuthHeaders())
      .then((res) => res.json())
      .then((data) => { if (!cancelled) setFilename(data.filename) })
      .catch(() => { /* PdfReview itself surfaces a load error */ })
    return () => { cancelled = true }
  }, [jobId])

  // Dataset Inventory → Preview (step 2). Files (1) stays reachable via the stage rail.
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
