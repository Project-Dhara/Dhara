'use client'

import { Suspense, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'

/** Legacy URL — redirects to /console/grouping?jobId=… */
function RedirectBody() {
  const searchParams = useSearchParams()
  const jobId = String(searchParams.get('jobId') || '')
  const router = useRouter()

  useEffect(() => {
    if (jobId) {
      router.replace(`/console/grouping?jobId=${encodeURIComponent(jobId)}`)
    } else {
      router.replace('/console')
    }
  }, [jobId, router])

  return null
}

export default function PdfNextStepsRedirect() {
  return (
    <Suspense fallback={null}>
      <RedirectBody />
    </Suspense>
  )
}
