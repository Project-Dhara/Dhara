// Console flow state persisted across a page refresh / sidebar detour
// (sessionStorage). Returning to Console must restore the same step.
//
// File objects can't survive storage (browsers won't reconstruct a File), so
// metadataFiles / pendingDatasetFiles are excluded — re-add files if you
// refresh mid upload-step.
export const CONSOLE_STORAGE_KEY = 'dhara_console_state_v1'

export function loadPersistedConsoleState() {
  try {
    const raw = sessionStorage.getItem(CONSOLE_STORAGE_KEY)
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}
