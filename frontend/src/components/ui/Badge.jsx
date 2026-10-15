'use client'

// Small status pill — quiet tones from the brand palette.
// All tones share the same border box so ok/warn/error stay the same height.
const TONE_CLASSES = {
  ok: 'border-transparent bg-sage text-teal',
  // Needs-review chips — soft orange so they read apart from green/ok.
  warn: 'border-[#F0B27A]/70 bg-[#FFF6EE] text-[#D4782E]',
  error: 'border-coral/30 bg-error-bg text-coral',
}

export default function Badge({ tone = 'ok', children, className = '' }) {
  return (
    <span className={`inline-flex h-7 items-center whitespace-nowrap rounded-full border px-2.5 text-[11.5px] font-semibold leading-none tracking-tight transition-all duration-dhara ease-dhara ${TONE_CLASSES[tone]} ${className}`}>
      {children}
    </span>
  )
}
