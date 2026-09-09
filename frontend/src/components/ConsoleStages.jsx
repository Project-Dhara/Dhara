'use client'

import { useEffect, useState } from 'react'
import { Check } from 'lucide-react'

// Shared console stage rail — used by the Excel flow (Console.jsx) and the
// PDF extraction pages (processing / review / next-steps) so both pipelines
// show the same "Console stages" sidebar.

export const STAGE_DEFS = [
  {
    name: 'Dataset Inventory', firstStep: 1, sub: 'Files, preview',
    subs: [
      { step: 1, label: 'Files' },
      { step: 2, label: 'Preview' },
    ],
  },
  {
    name: 'Metadata Workspace', firstStep: 3, sub: 'Grouping and catalogue fields',
    subs: [
      { step: 3, label: 'Grouping' },
      { step: 4, label: 'Metadata' },
    ],
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
  if (step <= 2) return 0
  if (step <= 4) return 1
  if (step === 5) return 2
  return 3
}

// Connected-line stepper: ivory pending → teal active → leaf-green done.
// Substeps stay hidden until you hover a stage, then float out as a small
// panel beneath it — click any reachable one (current or already-visited) to
// jump straight there, including back to an earlier substep.
export function StageSidebar({ stageIdx, step, maxStepReached, expandedStage, setExpandedStage, goToStep }) {
  return (
    <div className="flex w-full items-center rounded-2xl border border-line/90 bg-surface px-5 py-3.5">
      {STAGE_DEFS.map((s, i) => {
        const active = i === stageIdx
        const done = i < stageIdx
        const isLast = i === STAGE_DEFS.length - 1
        return (
          <div key={s.name} className={`flex items-center ${isLast ? 'flex-none' : 'flex-1'}`}>
            <div className="dhara-tab group relative flex flex-none cursor-default items-center gap-2.5 rounded-full border-transparent px-2.5 py-1.5 hover:bg-teal-deep">
              <span
                className={`flex h-6 w-6 flex-none items-center justify-center rounded-full text-[11px] font-semibold transition-all duration-[420ms] ease-[cubic-bezier(0.22,1,0.36,1)] ${
                  active
                    ? 'bg-teal text-white shadow-[0_0_0_4px_rgba(23,107,107,0.14)] group-hover:bg-cream/20 group-hover:text-cream group-hover:shadow-none'
                    : done
                      ? 'bg-green text-white group-hover:bg-cream/20 group-hover:text-cream'
                      : 'bg-cream text-[#9AA0A6] group-hover:bg-cream/20 group-hover:text-cream'
                }`}
              >
                {done ? <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden /> : i + 1}
              </span>
              <span
                className={`whitespace-nowrap text-[12.5px] font-semibold tracking-tight transition-colors duration-[420ms] ease-[cubic-bezier(0.22,1,0.36,1)] group-hover:text-cream ${
                  active ? 'text-ink' : done ? 'text-ink-soft' : 'text-[#9AA0A6]'
                }`}
              >
                {s.name}
              </span>

              {/* Floating substep panel — invisible/unhittable until hovered,
                  so it never steals clicks or space from the stepper bar. */}
              <div className="pointer-events-none absolute left-0 top-full z-30 -translate-y-1 pt-2.5 opacity-0 transition-all duration-200 ease-out group-hover:pointer-events-auto group-hover:translate-y-0 group-hover:opacity-100">
                <div className="flex min-w-[200px] flex-col gap-0.5 rounded-xl border border-line bg-surface p-1.5 shadow-hover">
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
                        className={`flex items-center gap-2 rounded-lg px-2.5 py-2 text-left transition-colors duration-150 ${
                          reachable ? 'cursor-pointer hover:bg-sage/70' : 'cursor-default'
                        }`}
                      >
                        <span
                          className={`h-1.5 w-1.5 flex-none rounded-full ${
                            subActive ? 'bg-teal' : subDone ? 'bg-green' : 'bg-line'
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
              </div>
            </div>
            {!isLast && (
              <div className="mx-3 h-px min-w-[16px] flex-1 rounded-full bg-line">
                <div
                  className={`h-full rounded-full transition-all duration-500 ease-out ${done ? 'w-full bg-green' : 'w-0 bg-teal'}`}
                />
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

/**
 * Shell that mirrors Console.jsx's left rail for PDF routes.
 * step / maxStepReached map to the same STAGE_DEFS numbers as Excel:
 *   1 Files · 2 Preview · 3 Grouping · 4 Metadata · 5 Classify · 6 Publish
 * Grouping lives under Metadata Workspace (with Metadata); Files/Preview
 * stay under Dataset Inventory.
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
    <div className="flex flex-col gap-5">
      <StageSidebar
        stageIdx={stageIdx}
        step={step}
        maxStepReached={maxStepReached}
        expandedStage={expandedStage}
        setExpandedStage={setExpandedStage}
        goToStep={goToStep}
      />
      {/* Same content column as Excel Console.jsx — header + panels stay unchanged inside children. */}
      <div className="flex min-w-0 flex-1 flex-col gap-[18px]">
        {children}
      </div>
    </div>
  )
}
