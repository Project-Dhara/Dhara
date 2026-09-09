'use client'

import { useEffect, useRef, useState } from 'react'
import ProcessingStepper from './ProcessingStepper'

/**
 * Full-page status UI between Console stages (same look as PDF processing).
 *
 * Advances through `steps` on a timer. If `work` is provided, waits for that
 * promise as well before calling `onComplete` (so real API work can finish
 * while the stepper animates).
 */
export default function ConsoleStatusPlaceholder({
  title,
  subtitle,
  steps,
  work = null,
  msPerStep = 850,
  onComplete,
}) {
  const [activeIdx, setActiveIdx] = useState(0)
  const [percent, setPercent] = useState(8)
  const [workDone, setWorkDone] = useState(!work)
  const [animDone, setAnimDone] = useState(false)
  const completedRef = useRef(false)
  const onCompleteRef = useRef(onComplete)
  onCompleteRef.current = onComplete

  useEffect(() => {
    if (!work) {
      setWorkDone(true)
      return undefined
    }
    let cancelled = false
    Promise.resolve()
      .then(() => work())
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setWorkDone(true)
      })
    return () => { cancelled = true }
    // Run once when this status page mounts — callers pass a stable work fn per transition.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (steps.length === 0) {
      setAnimDone(true)
      return undefined
    }
    setActiveIdx(0)
    setPercent(8)
    setAnimDone(false)

    const timeouts = []
    steps.forEach((_, i) => {
      timeouts.push(setTimeout(() => {
        setActiveIdx(i)
        setPercent(12)
      }, i * msPerStep))
    })
    timeouts.push(setTimeout(() => {
      setActiveIdx(steps.length - 1)
      setPercent(100)
      setAnimDone(true)
    }, steps.length * msPerStep))

    const tick = setInterval(() => {
      setPercent((p) => (p >= 92 ? p : p + 7 + Math.floor(Math.random() * 6)))
    }, 280)

    return () => {
      timeouts.forEach((t) => clearTimeout(t))
      clearInterval(tick)
    }
  }, [steps, msPerStep])

  useEffect(() => {
    if (!animDone || !workDone || completedRef.current) return
    completedRef.current = true
    const t = setTimeout(() => onCompleteRef.current?.(), 280)
    return () => clearTimeout(t)
  }, [animDone, workDone])

  const displaySteps = steps.map((s, i) => {
    if (i < activeIdx) return { ...s, status: 'done' }
    if (i === activeIdx) {
      return {
        ...s,
        status: 'active',
        percent: i === steps.length - 1 && animDone ? 100 : percent,
        message: s.message,
      }
    }
    return { ...s, status: 'pending' }
  })

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-8 py-8">
      <div>
        <div className="font-display text-xl font-medium text-ink">{title}</div>
        {subtitle && (
          <div className="mt-1 text-sm text-ink-soft">{subtitle}</div>
        )}
      </div>
      <ProcessingStepper steps={displaySteps} />
    </div>
  )
}
