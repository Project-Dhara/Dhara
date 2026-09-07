'use client'

import { useParams, useRouter } from 'next/navigation'
import Button from '../../../../../components/ui/Button'
import PdfConsoleLayout from '../../../../../components/PdfConsoleLayout'

// Static placeholder -- the real next stage (grouping & harmonization for
// PDF-extracted tables) doesn't exist yet. No data fetch, no job-status
// display, no backend call: purely a client-side navigation destination for
// the review page's "Continue" button until that stage is built.
export default function PdfNextStepsPlaceholder() {
  const { jobId } = useParams<{ jobId: string }>()
  const router = useRouter()
  return (
    <PdfConsoleLayout jobId={jobId} step={3} maxStepReached={3}>
      <div className="mx-auto flex max-w-lg flex-col items-center gap-4 py-16 text-center">
        <div className="font-display text-2xl font-medium text-ink">Coming soon</div>
        <p className="text-[15px] text-ink-soft">
          Grouping &amp; harmonization for PDF-extracted tables is coming soon. The tables you reviewed are saved —
          this next step (grouping tables into datasets and finalizing metadata) isn&apos;t built yet.
        </p>
        <div className="flex flex-wrap items-center justify-center gap-2.5">
          <Button variant="secondary" onClick={() => router.push(`/console/review/${jobId}`)}>← Back to preview</Button>
          <Button variant="primary" onClick={() => router.push('/console')}>Back to console</Button>
        </div>
      </div>
    </PdfConsoleLayout>
  )
}
