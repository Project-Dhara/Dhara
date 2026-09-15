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

// Green fill on the connector after stage `i`: full once that stage is
// behind you, otherwise proportional to the current substep (same rule for
// Excel and PDF — both share this rail).
function connectorFillPercent(i, stageIdx, step) {
  if (i < stageIdx) return 100
  if (i > stageIdx) return 0
  const subs = STAGE_DEFS[i].subs
  if (!subs.length) return 0
  const idx = subs.findIndex((s) => s.step === step)
  const at = idx < 0 ? 0 : idx
  return Math.round(((at + 1) / subs.length) * 100)
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
            <div className="dhara-tab group relative flex flex-none cursor-default items-center gap-2.5 rounded-full border-transparent px-2.5 py-1.5 hover:bg-sage">
              <span
                className={`flex h-6 w-6 flex-none items-center justify-center rounded-full text-[11px] font-semibold transition-all duration-dhara ease-dhara ${
                  active
                    ? 'bg-teal-deep text-cream shadow-[0_0_0_4px_rgba(18,64,62,0.14)]'
                    : done
                      ? 'bg-green text-white'
                      : 'bg-cream text-[#9AA0A6] group-hover:bg-white group-hover:text-teal-deep'
                }`}
              >
                {done ? <Check className="h-3 w-3" strokeWidth={2.5} aria-hidden /> : i + 1}
              </span>
              <span
                className={`whitespace-nowrap text-[12.5px] font-semibold tracking-tight transition-colors duration-dhara ease-dhara ${
                  active ? 'text-ink group-hover:text-teal-deep' : done ? 'text-ink-soft group-hover:text-teal-deep' : 'text-[#9AA0A6] group-hover:text-teal-deep'
                }`}
              >
                {s.name}
              </span>

              {/* Floating substep panel — invisible/unhittable until hovered,
                  so it never steals clicks or space from the stepper bar. */}
              <div className="pointer-events-none absolute left-0 top-full z-30 -translate-y-1.5 pt-2.5 opacity-0 transition-all duration-dhara ease-dhara group-hover:pointer-events-auto group-hover:translate-y-0 group-hover:opacity-100">
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
              <div className="mx-3 h-0.5 min-w-[16px] flex-1 overflow-hidden rounded-full bg-line">
                <div
                  className="h-full rounded-full bg-green transition-all duration-dhara-slow ease-dhara-out"
                  style={{ width: `${connectorFillPercent(i, stageIdx, step)}%` }}
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
      <div key={step} className="dhara-page-enter flex min-w-0 flex-1 flex-col gap-[18px]">
        {children}
      </div>
    </div>
  )
}
