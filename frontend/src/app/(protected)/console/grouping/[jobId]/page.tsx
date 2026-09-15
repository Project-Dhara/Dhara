'use client'

import { useParams } from 'next/navigation'
import PdfGrouping from '../../../../../components/pdf/PdfGrouping'

export default function PdfGroupingPage() {
  const { jobId } = useParams<{ jobId: string }>()
  return <PdfGrouping jobId={jobId} />
}
