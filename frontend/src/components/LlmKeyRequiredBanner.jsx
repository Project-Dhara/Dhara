'use client'

import Button from './ui/Button'

/**
 * Shown at the start of Console / PDF upload when the steward has not saved
 * an LLM API key in Settings. All AI paths use that key only (no server .env fallback).
 */
export default function LlmKeyRequiredBanner({ onGoSettings }) {
  return (
    <div className="rounded-lg border border-[#f3c98b] bg-[#fffaf1] px-4 py-3.5 text-sm leading-relaxed text-[#8a5a12]">
      <strong>LLM key required</strong>
      <div className="mt-1">
        Save an API key in Settings before uploading datasets. AI extraction, metadata auto-fill,
        and NCO matching require an LLM API key. 
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
