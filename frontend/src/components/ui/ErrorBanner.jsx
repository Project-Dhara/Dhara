'use client'

// Replaces .error-banner.
export default function ErrorBanner({ children, className = '' }) {
  return (
    <div className={`rounded-lg border border-coral bg-[#fdeceb] px-4 py-3 text-[13.5px] text-ink ${className}`}>
      <strong>Error:</strong> {children}
    </div>
  )
}