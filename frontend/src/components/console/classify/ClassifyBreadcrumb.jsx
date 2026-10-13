'use client'

import { ChevronRight } from 'lucide-react'

const CRUMBS = [
  { id: 'classification', label: 'Classification', step: 5 },
  { id: 'harmonisation', label: 'Harmonisation', step: 6 },
]

/**
 * Page-title breadcrumb for Classification ↔ Harmonisation.
 * Clicking an earlier crumb navigates back without resetting classify state
 * (Classify stays mounted across steps 5–6).
 */
export default function ClassifyBreadcrumb({ phase, onNavigate, canOpenHarmonisation, size = 'page' }) {
  const isPage = size === 'page'
  return (
    <nav
      aria-label="Classification and harmonisation"
      className={`flex flex-wrap items-center ${isPage ? 'gap-1.5' : 'gap-1'}`}
    >
      {CRUMBS.map((crumb, i) => {
        const active = phase === crumb.id
        const reachable = crumb.id === 'classification' || canOpenHarmonisation
        return (
          <span key={crumb.id} className="inline-flex items-center gap-1">
            {i > 0 && (
              <ChevronRight
                className={`mx-0.5 flex-none text-[#c2b8a6] ${isPage ? 'h-5 w-5' : 'h-3.5 w-3.5'}`}
                strokeWidth={2}
                aria-hidden
              />
            )}
            <button
              type="button"
              disabled={!reachable}
              onClick={() => reachable && onNavigate(crumb.id)}
              aria-current={active ? 'page' : undefined}
              className={`inline-flex items-center rounded-lg transition-colors ${
                isPage
                  ? `px-1 py-0.5 ${
                      active
                        ? 'font-display text-[26px] font-medium leading-tight text-ink'
                        : reachable
                          ? 'font-display text-[26px] font-medium leading-tight text-[#b0a898] hover:text-teal-deep'
                          : 'cursor-default font-display text-[26px] font-medium leading-tight text-[#d5cec2]'
                    }`
                  : `px-2 py-1 text-[13px] ${
                      active
                        ? 'bg-sage/70 font-semibold text-teal-deep'
                        : reachable
                          ? 'font-medium text-ink-soft hover:bg-cream hover:text-teal-deep'
                          : 'cursor-default font-medium text-[#c7cbce]'
                    }`
              }`}
            >
              {crumb.label}
            </button>
          </span>
        )
      })}
    </nav>
  )
}
