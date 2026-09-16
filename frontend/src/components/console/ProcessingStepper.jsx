'use client'

import { AlertTriangle, Check, Minus } from 'lucide-react'
import ProgressBar from '../ui/ProgressBar'

// Purely presentational multi-step progress indicator. Takes a generic
// {steps: [{key, label, status, percent?, message?}]} shape so it can later
// be reused for a flow with no real job/percent (e.g. the xlsx batch-extract
// flow, driven by a simple two-call state machine with indeterminate
// progress) without needing to know how the caller computed those statuses.
// status is one of 'pending' | 'active' | 'done' | 'skipped' | 'error'.
function StatusIcon({ status }) {
  if (status === 'done') {
    return (
      <span className="relative flex h-6 w-6 flex-none items-center justify-center rounded-full bg-green text-white shadow-sm ring-4 ring-green/15 transition-all duration-300">
        <Check className="h-3.5 w-3.5" strokeWidth={2.5} aria-hidden />
      </span>
    )
  }
  if (status === 'active') {
    return (
      <span className="relative flex h-6 w-6 flex-none items-center justify-center">
        <span className="absolute inset-0 rounded-full bg-teal/15" />
        <span className="h-6 w-6 flex-none rounded-full border-2 border-teal border-t-transparent animate-spin" />
      </span>
    )
  }
  if (status === 'error') {
    return (
      <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full bg-coral text-white shadow-sm ring-4 ring-coral/15 transition-all duration-300">
        <AlertTriangle className="h-3.5 w-3.5" strokeWidth={2.25} aria-hidden />
      </span>
    )
  }
  if (status === 'skipped') {
    return (
      <span className="flex h-6 w-6 flex-none items-center justify-center rounded-full border border-line bg-white text-ink-soft transition-all duration-300">
        <Minus className="h-3.5 w-3.5" strokeWidth={2} aria-hidden />
      </span>
    )
  }
  return <span className="h-6 w-6 flex-none rounded-full border-2 border-line bg-white transition-all duration-300" />
}

export default function ProcessingStepper({ steps }) {
  return (
    <div className="flex flex-col">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1
        return (
          <div key={step.key} className="relative flex gap-3.5 pb-6 last:pb-0">
            {!isLast && (
              <span
                className={`absolute left-3 top-6 w-px transition-colors duration-500 ${step.status === 'done' ? 'bg-green' : 'bg-line'}`}
                style={{ height: 'calc(100% - 0.75rem)' }}
                aria-hidden
              />
            )}
            <StatusIcon status={step.status} />
            <div className="min-w-0 flex-1 pt-0.5">
              <div className={`text-[15px] font-semibold transition-colors duration-300 ${step.status === 'pending' ? 'text-ink-soft' : 'text-ink'}`}>
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
        )
      })}
    </div>
  )
}