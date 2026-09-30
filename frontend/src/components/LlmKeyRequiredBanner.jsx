'use client'

import Button from './ui/Button'

/**
 * Shown at the start of Console / PDF upload when the steward has not saved
 * an LLM API key in Settings. Uploads still work; AI-assisted steps degrade.
 */
export default function LlmKeyRequiredBanner({ onGoSettings }) {
  return (
    <div className="rounded-lg border border-[#f3c98b] bg-[#fffaf1] px-4 py-3.5 text-sm leading-relaxed text-[#8a5a12]">
      <strong>LLM key not configured</strong>
      <div className="mt-1">
        You can continue without one. AI extraction, metadata auto-fill, and NCO matching
        will not work as intended until you save an API key in Settings.
      </div>
      {onGoSettings && (
        <div className="mt-3">
          <Button type="button" onClick={onGoSettings}>
            Open Settings
          </Button>
        </div>
      )}
    </div>
  )
}
