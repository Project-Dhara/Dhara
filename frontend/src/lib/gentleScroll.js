/** Shared slower scrolling helpers for AppShell and programmatic scroll-to-top. */

/** Fraction of native wheel delta applied (lower = slower). */
export const SCROLL_WHEEL_FACTOR = 0.72
/** Programmatic scroll-to-top duration (ms). */
export const SCROLL_TO_TOP_MS = 520

export function prefersReducedMotion() {
  if (typeof window === 'undefined') return false
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

function isWindowScroller(el) {
  return !el
    || el === window
    || el === document.documentElement
    || el === document.body
    || el === document.scrollingElement
}

/** Ease-out cubic scroll over `duration` ms (slower than native smooth). */
export function animateScrollTo(el, top, duration = SCROLL_TO_TOP_MS) {
  if (typeof window === 'undefined') return
  const target = isWindowScroller(el) ? window : el
  if (!target) return

  if (prefersReducedMotion()) {
    if (target === window) window.scrollTo(0, top)
    else target.scrollTop = top
    return
  }

  const getTop = () => (
    target === window
      ? (window.scrollY || document.documentElement.scrollTop || 0)
      : target.scrollTop
  )
  const setTop = (v) => {
    if (target === window) window.scrollTo(0, v)
    else target.scrollTop = v
  }

  const start = getTop()
  const delta = top - start
  if (Math.abs(delta) < 1) return

  // Slightly longer for long distances, but keep it snappy.
  const dist = Math.abs(delta)
  const scaled = Math.min(780, Math.max(duration, duration + dist * 0.06))

  const t0 = performance.now()
  const easeOutCubic = (t) => 1 - (1 - t) ** 3

  const step = (now) => {
    const p = Math.min(1, (now - t0) / scaled)
    setTop(start + delta * easeOutCubic(p))
    if (p < 1) requestAnimationFrame(step)
  }
  requestAnimationFrame(step)
}

/**
 * Slow wheel / trackpad scrolling on a scrollport.
 * Skips nested scroll areas that can still scroll, pinch-zoom, and reduced-motion.
 */
export function attachGentleWheel(el, factor = SCROLL_WHEEL_FACTOR) {
  if (!el || typeof window === 'undefined') return () => {}

  const onWheel = (e) => {
    if (e.ctrlKey || e.metaKey || e.defaultPrevented) return
    if (prefersReducedMotion()) return

    let node = e.target
    while (node && node !== el) {
      if (node instanceof Element) {
        const { overflowY } = getComputedStyle(node)
        if (
          (overflowY === 'auto' || overflowY === 'scroll' || overflowY === 'overlay')
          && node.scrollHeight > node.clientHeight + 1
        ) {
          const dy = e.deltaY
          const top = node.scrollTop
          const max = node.scrollHeight - node.clientHeight
          if ((dy < 0 && top > 0) || (dy > 0 && top < max - 1)) return
        }
      }
      node = node.parentElement
    }

    e.preventDefault()
    el.scrollTop += e.deltaY * factor
  }

  el.addEventListener('wheel', onWheel, { passive: false })
  return () => el.removeEventListener('wheel', onWheel)
}
