'use client'

// Quiet error callout — light surface, soft coral edge.
export default function ErrorBanner({ children, className = '' }) {
  return (
    <div className={`rounded-xl border border-coral/25 bg-error-bg px-4 py-3 text-[13.5px] leading-relaxed text-ink ${className}`}>
      <strong className="font-semibold text-coral">Error:</strong> {children}
    </div>
  )
}
