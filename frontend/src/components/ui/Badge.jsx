'use client'

// Small status pill — quiet tones from the brand palette.
const TONE_CLASSES = {
  ok: 'bg-sage text-teal',
  warn: 'bg-[#FFF8E8] text-[#8a6116] border border-yellow/35',
  error: 'bg-[#FDF0EF] text-[#a13b3b] border border-coral/30',
}

export default function Badge({ tone = 'ok', children, className = '' }) {
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-1 text-[11.5px] font-semibold tracking-tight transition-colors duration-150 ${TONE_CLASSES[tone]} ${className}`}>
      {children}
    </span>
  )
}
