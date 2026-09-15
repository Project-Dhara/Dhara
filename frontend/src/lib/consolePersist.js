// Console flow state persisted across a page refresh (sessionStorage) — a
// detour or reload should not lose an in-progress upload flow. Extracted
// verbatim from Console.jsx (was the local STORAGE_KEY / loadPersisted).
//
// File objects can't survive storage either way (browsers won't let a File
// be reconstructed from storage), so metadataFiles is deliberately excluded
// by the caller — the user just re-adds files if they refresh mid-upload-step.
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
