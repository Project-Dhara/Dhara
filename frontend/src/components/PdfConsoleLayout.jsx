'use client'

import { useRouter } from 'next/navigation'
import { ConsoleStagesShell } from './ConsoleStages'

/**
 * PDF pipeline stages map onto the same Console Stages numbers as Excel:
 *   1 Files (upload / processing) · 2 Preview (review) · 3 Grouping (next-steps)
 * Metadata / Harmonisation / Publish stay locked until those PDF stages exist.
 */
export default function PdfConsoleLayout({ jobId, step, maxStepReached, children }) {
  const router = useRouter()

  const onGoToStep = (targetStep) => {
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
    <ConsoleStagesShell step={step} maxStepReached={maxStepReached} onGoToStep={onGoToStep}>
      {children}
    </ConsoleStagesShell>
  )
}
