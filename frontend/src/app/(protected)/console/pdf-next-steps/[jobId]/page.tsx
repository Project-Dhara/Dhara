'use client'

import { useRouter } from 'next/navigation'
import Button from '../../../../../components/ui/Button'

// Static placeholder -- the real next stage (grouping & harmonization for
// PDF-extracted tables) doesn't exist yet. No data fetch, no job-status
// display, no backend call: purely a client-side navigation destination for
// the review page's "Continue" button until that stage is built.
export default function PdfNextStepsPlaceholder() {
  const router = useRouter()
  return (
    <div className="mx-auto flex max-w-lg flex-col items-center gap-4 py-24 text-center">
      <div className="font-display text-2xl font-medium text-ink">Coming soon</div>
      <p className="text-[15px] text-ink-soft">
        Grouping &amp; harmonization for PDF-extracted tables is coming soon. The tables you reviewed are saved —
        this next step (grouping tables into datasets and finalizing metadata) isn&apos;t built yet.
      </p>
      <Button variant="primary" onClick={() => router.push('/console')}>Back to console</Button>
    </div>
  )
}
