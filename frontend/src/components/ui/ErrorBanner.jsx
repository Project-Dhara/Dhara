'use client'

// Quiet error callout — light surface, soft coral edge.
export default function ErrorBanner({ children, className = '' }) {
  return (
    <div className={`rounded-xl border border-coral/25 bg-[#FDF6F5] px-4 py-3 text-[13.5px] leading-relaxed text-ink ${className}`}>
      <strong className="font-semibold text-[#a13b3b]">Error:</strong> {children}
    </div>
  )
}
