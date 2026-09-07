'use client'

import { useEffect, useState } from 'react'

// Shared console stage rail — used by the Excel flow (Console.jsx) and the
// PDF extraction pages (processing / review / next-steps) so both pipelines
// show the same "Console stages" sidebar.

export const STAGE_DEFS = [
  {
    name: 'Dataset Inventory', firstStep: 1, sub: 'Files, preview, grouping',
    subs: [
      { step: 1, label: 'Files' },
      { step: 2, label: 'Preview' },
      { step: 3, label: 'Grouping' },
    ],
  },
  {
    name: 'Metadata Workspace', firstStep: 4, sub: 'Title, category, coverage',
    subs: [{ step: 4, label: 'Metadata' }],
  },
  {
    name: 'Transformation & Harmonisation', firstStep: 5, sub: 'Concepts and code maps',
    subs: [{ step: 5, label: 'Classification & harmonisation' }],
  },
  {
    name: 'Dataset Publication', firstStep: 6, sub: 'API, MCP, catalogue',
    subs: [{ step: 6, label: 'Publish' }],
  },
]

export function stageIndexForStep(step) {
  if (step <= 3) return 0
  if (step === 4) return 1
  if (step === 5) return 2
  return 3
}

export function StageSidebar({ stageIdx, step, maxStepReached, expandedStage, setExpandedStage, goToStep }) {
  return (
    <aside className="flex w-[218px] flex-none flex-col gap-1 rounded-[10px] border border-line bg-white py-3">
      <div className="px-4 pb-2.5 text-[11px] uppercase tracking-[0.07em] text-[#8E9398]">Console stages</div>
      {STAGE_DEFS.map((s, i) => {
        const expanded = i === expandedStage
        const active = i === stageIdx
        const done = i < stageIdx
        return (
          <div key={s.name} className="flex flex-col">
            <button
              type="button"
              className="flex cursor-pointer items-start gap-2.5 px-4 py-2.5 text-left"
              onClick={() => setExpandedStage(i)}
            >
              <span
                className={`flex h-5 w-5 flex-none items-center justify-center rounded-full text-[11px] font-semibold ${
                  active ? 'bg-teal text-white' : done ? 'bg-sage text-[#3d7a3d]' : 'bg-cream text-[#8E9398]'
                }`}
              >
                {done ? '✓' : i + 1}
              </span>
              <span className="min-w-0">
                <span className={`block text-[13.5px] font-semibold ${active ? 'text-ink' : 'text-ink-soft'}`}>{s.name}</span>
                <span className="block text-[11.5px] text-[#8E9398]">{s.sub}</span>
              </span>
            </button>
            {expanded && (
              <div className="flex flex-col gap-0.5 py-0.5 pl-[46px] pr-4 pb-2">
                {s.subs.map((sub) => {
                  const subActive = sub.step === step
                  const subDone = sub.step < step
                  const reachable = sub.step <= maxStepReached
                  return (
                    <button
                      key={sub.step}
                      type="button"
                      disabled={!reachable}
                      onClick={() => reachable && goToStep(sub.step)}
                      className={`flex items-center gap-2 py-[5px] text-left ${reachable ? 'cursor-pointer' : 'cursor-default'}`}
                    >
                      <span
                        className={`h-1.5 w-1.5 flex-none rounded-full ${
                          subActive ? 'bg-teal' : subDone ? 'bg-sage' : 'bg-line'
                        }`}
                      />
                      <span
                        className={`text-[12.5px] ${
                          subActive ? 'font-semibold text-ink' : !reachable ? 'text-[#C7CBCE]' : subDone ? 'text-ink-soft' : 'text-[#8E9398]'
                        }`}
                      >
                        {sub.label}
                      </span>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </aside>
  )
}

/**
 * Shell that mirrors Console.jsx's left rail for PDF routes.
 * step / maxStepReached map to the same STAGE_DEFS numbers as Excel:
 *   1 Files · 2 Preview · 3 Grouping · 4 Metadata · 5 Classify · 6 Publish
 */
export function ConsoleStagesShell({ step, maxStepReached, onGoToStep, children }) {
  const stageIdx = stageIndexForStep(step)
  const [expandedStage, setExpandedStage] = useState(stageIdx)

  useEffect(() => {
    setExpandedStage(stageIndexForStep(step))
  }, [step])

  const goToStep = (targetStep) => {
    if (targetStep <= maxStepReached) onGoToStep?.(targetStep)
  }

  return (
    <div className="flex items-start gap-6">
      <div className="sticky top-0 self-start">
        <StageSidebar
          stageIdx={stageIdx}
          step={step}
          maxStepReached={maxStepReached}
          expandedStage={expandedStage}
          setExpandedStage={setExpandedStage}
          goToStep={goToStep}
        />
      </div>
      {/* Same content column as Excel Console.jsx — header + panels stay unchanged inside children. */}
      <div className="flex min-w-0 flex-1 flex-col gap-[18px]">
        {children}
      </div>
    </div>
  )
}
