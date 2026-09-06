'use client'

import ProgressBar from './ui/ProgressBar'

// Purely presentational multi-step progress indicator. Takes a generic
// {steps: [{key, label, status, percent?, message?}]} shape so it can later
// be reused for a flow with no real job/percent (e.g. the xlsx batch-extract
// flow, driven by a simple two-call state machine with indeterminate
// progress) without needing to know how the caller computed those statuses.
// status is one of 'pending' | 'active' | 'done' | 'skipped' | 'error'.
function StatusIcon({ status }) {
  if (status === 'done') {
    return (
      <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-green text-white text-xs">✓</span>
    )
  }
  if (status === 'active') {
    return <span className="h-6 w-6 flex-none rounded-full border-2 border-teal border-t-transparent animate-spin" />
  }
  if (status === 'error') {
    return (
      <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-coral text-white text-xs">!</span>
    )
  }
  if (status === 'skipped') {
    return (
      <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-line text-ink-soft text-xs">—</span>
    )
  }
  return <span className="h-6 w-6 flex-none rounded-full border-2 border-line" />
}

export default function ProcessingStepper({ steps }) {
  return (
    <div className="flex flex-col gap-5">
      {steps.map((step) => (
        <div key={step.key} className="flex gap-3">
          <StatusIcon status={step.status} />
          <div className="flex-1 pt-0.5">
            <div className={`text-[15px] font-semibold ${step.status === 'pending' ? 'text-ink-soft' : 'text-ink'}`}>
              {step.label}
            </div>
            {step.status === 'active' && (
              <div className="mt-2 flex flex-col gap-1.5">
                {typeof step.percent === 'number' ? (
                  <ProgressBar percent={step.percent} className="max-w-xs" />
                ) : (
                  <div className="h-2 max-w-xs animate-progress-pulse rounded-full bg-teal/40" />
                )}
                {step.message && <div className="text-xs text-ink-soft">{step.message}</div>}
              </div>
            )}
            {step.status === 'skipped' && step.message && (
              <div className="mt-1 text-xs text-ink-soft">{step.message}</div>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}