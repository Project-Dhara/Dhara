'use client'

import { useRouter } from 'next/navigation'
import { ConsoleStagesShell } from '../console/ConsoleStages'

/**
 * PDF pipeline stages map onto the same Console Stages numbers as Excel:
 *   1 Files · 2 Preview · 3 Grouping · 4 Metadata · 5 Classify · 6 Publish
 *
 * Pass `onGoToStep` when the page owns later steps in-memory (grouping →
 * metadata onward); otherwise default to the review/grouping routes.
 */
export default function PdfConsoleLayout({ jobId, step, maxStepReached, onGoToStep = undefined, children }) {
  const router = useRouter()

  const defaultGoToStep = (targetStep) => {
    if (targetStep === 1) {
      router.push('/console')
      return
    }
    if (!jobId) return
    if (targetStep === 2) {
      router.push(`/console/review/${jobId}`)
      return
    }
    if (targetStep === 3) {
      router.push(`/console/grouping/${jobId}`)
    }
  }

  return (
    <ConsoleStagesShell
      step={step}
      maxStepReached={maxStepReached}
      onGoToStep={onGoToStep || defaultGoToStep}
    >
      {children}
    </ConsoleStagesShell>
  )
}
