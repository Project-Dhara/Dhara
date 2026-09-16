'use client'

import { useParams } from 'next/navigation'
import { PdfTableEditorPage } from '@/components/pdf/PdfReview'

export default function PdfTableEditRoutePage() {
  const { jobId, tableId } = useParams<{ jobId: string; tableId: string }>()
  const decodedTableId = decodeURIComponent(String(tableId || ''))

  return (
    <PdfTableEditorPage
      jobId={String(jobId || '')}
      tableId={decodedTableId}
    />
  )
}
