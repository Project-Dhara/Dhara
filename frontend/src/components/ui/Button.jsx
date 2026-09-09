'use client'

// Shared button component -- variant="primary|secondary" covers every
// button in the app; size="sm" is the compact modal-button size.
const VARIANT_CLASSES = {
  primary:
    'bg-teal text-white hover:bg-teal-dark active:scale-[0.985] disabled:bg-[#ece8e0] disabled:text-[#a49c8e] disabled:cursor-not-allowed disabled:active:scale-100',
  secondary:
    'bg-surface text-ink border border-line hover:border-teal/35 hover:bg-sage/60 hover:text-teal active:scale-[0.985] disabled:opacity-50 disabled:cursor-not-allowed disabled:active:scale-100',
}

const SIZE_CLASSES = {
  md: 'h-10 px-5 text-[14.5px]',
  sm: 'px-4 py-2 text-[13px]',
}

export default function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  disabled = false,
  className = '',
  children,
  ...rest
}) {
  return (
    <button
      className={`inline-flex cursor-pointer items-center justify-center gap-2 rounded-xl font-semibold tracking-tight transition-all duration-150 ease-out focus-visible:outline-none focus-visible:shadow-focus-ring ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />}
      {children}
    </button>
  )
}
