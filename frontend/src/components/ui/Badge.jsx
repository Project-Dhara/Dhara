'use client'

// Replaces .pdf-badge-ok/.pdf-badge-warn (and generalizes to an "error"
// tone) -- a small pill used to flag review status at a glance.
const TONE_CLASSES = {
  ok: 'bg-sage text-[#3d7a3d]',
  warn: 'bg-[#fff3d6] text-[#8a6116] border border-yellow',
  error: 'bg-[#fdeceb] text-[#a13b3b] border border-coral',
}

export default function Badge({ tone = 'ok', children, className = '' }) {
  return (
    <span className={`inline-block whitespace-nowrap rounded-full px-2.5 py-1 text-[11.5px] font-bold ${TONE_CLASSES[tone]} ${className}`}>
      {children}
    </span>
  )
}