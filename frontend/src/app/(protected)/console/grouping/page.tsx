'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import PdfGrouping from '../../../../components/pdf/PdfGrouping'

function GroupingBody() {
  const searchParams = useSearchParams()
  const jobId = String(searchParams.get('jobId') || '')
  return <PdfGrouping jobId={jobId} />
}

export default function PdfGroupingPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-ink-soft">Loading…</div>}>
      <GroupingBody />
    </Suspense>
  )
}
