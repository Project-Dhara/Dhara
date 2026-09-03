const KYDS_CHANGED = 'dhara-kyds-changed'

export function notifyKydsChanged() {
  window.dispatchEvent(new Event(KYDS_CHANGED))
}

export function onKydsChanged(handler) {
  window.addEventListener(KYDS_CHANGED, handler)
  return () => window.removeEventListener(KYDS_CHANGED, handler)
}
