'use client'

import { useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'

/** Legacy URL — redirects to /console/grouping/[jobId]. */
export default function PdfNextStepsRedirect() {
  const { jobId } = useParams<{ jobId: string }>()
  const router = useRouter()

  useEffect(() => {
    if (jobId) router.replace(`/console/grouping/${jobId}`)
  }, [jobId, router])

  return null
}
