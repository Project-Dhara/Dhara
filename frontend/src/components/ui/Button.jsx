'use client'

// Shared button component -- variant="primary|secondary" covers every
// button in the app; size="sm" is the compact modal-button size.
const VARIANT_CLASSES = {
  primary: 'bg-teal text-white hover:bg-teal-dark disabled:bg-[#ece4d6] disabled:text-[#a49c8e] disabled:cursor-not-allowed',
  secondary: 'bg-white text-ink border border-line hover:border-teal hover:text-teal disabled:opacity-50 disabled:cursor-not-allowed',
}

const SIZE_CLASSES = {
  md: 'h-[42px] px-5 text-[15px]',
  sm: 'px-5 py-2 text-[13px]',
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
      className={`inline-flex items-center justify-center gap-2 rounded-md font-semibold transition-colors cursor-pointer ${VARIANT_CLASSES[variant]} ${SIZE_CLASSES[size]} ${className}`}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <span className="h-3.5 w-3.5 rounded-full border-2 border-current border-t-transparent animate-spin" />}
      {children}
    </button>
  )
}