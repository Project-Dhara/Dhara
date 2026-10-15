'use client'

import StageSubstepBreadcrumb from '../StageSubstepBreadcrumb'

export const CLASSIFY_CRUMBS = [
  { id: 'classification', label: 'Classification', step: 5 },
  { id: 'harmonisation', label: 'Harmonisation', step: 6 },
]

/**
 * Page-title breadcrumb for Classification ↔ Harmonisation.
 * Clicking an earlier crumb navigates back without resetting classify state
 * (Classify stays mounted across steps 5–6).
 */
export default function ClassifyBreadcrumb({ phase, onNavigate, canOpenHarmonisation, size = 'page' }) {
  return (
    <StageSubstepBreadcrumb
      crumbs={CLASSIFY_CRUMBS}
      activeId={phase}
      onNavigate={onNavigate}
      isReachable={(crumb) => crumb.id === 'classification' || canOpenHarmonisation}
      ariaLabel="Classification and harmonisation"
      size={size}
    />
  )
}
