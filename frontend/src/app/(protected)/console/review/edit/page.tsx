'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import { PdfTableEditorPage } from '@/components/pdf/PdfReview'

function EditBody() {
  const searchParams = useSearchParams()
  const jobId = String(searchParams.get('jobId') || '')
  const tableId = decodeURIComponent(String(searchParams.get('tableId') || ''))

  return (
    <PdfTableEditorPage
      jobId={jobId}
      tableId={tableId}
    />
  )
}

export default function PdfTableEditRoutePage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-ink-soft">Opening table editor…</div>}>
      <EditBody />
    </Suspense>
  )
}
