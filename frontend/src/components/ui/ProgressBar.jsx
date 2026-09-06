'use client'

// Replaces .progress-bar-track/.progress-bar-fill.
export default function ProgressBar({ percent = 0, className = '' }) {
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <div className={`h-2 w-full overflow-hidden rounded-full bg-outer-bg ${className}`}>
      <div
        className="h-full rounded-full bg-teal transition-[width] duration-300 ease-out"
        style={{ width: `${Math.max(4, clamped)}%` }}
      />
    </div>
  )
}