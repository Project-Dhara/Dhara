'use client'

// Small status pill — quiet tones from the brand palette.
const TONE_CLASSES = {
  ok: 'bg-sage text-teal',
  warn: 'bg-warn-bg text-ink border border-yellow/40',
  error: 'bg-error-bg text-coral border border-coral/30',
}

export default function Badge({ tone = 'ok', children, className = '' }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 text-[11.5px] font-semibold tracking-tight transition-all duration-dhara ease-dhara ${TONE_CLASSES[tone]} ${className}`}>
      {children}
    </span>
  )
}
