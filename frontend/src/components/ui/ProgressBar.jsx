'use client'

// Quiet track + teal fill.
export default function ProgressBar({ percent = 0, className = '' }) {
  const clamped = Math.max(0, Math.min(100, percent))
  return (
    <div className={`h-1.5 w-full overflow-hidden rounded-full bg-line ${className}`}>
      <div
        className="h-full rounded-full bg-teal transition-[width] duration-dhara-slow ease-dhara-out"
        style={{ width: `${Math.max(4, clamped)}%` }}
      />
    </div>
  )
}
