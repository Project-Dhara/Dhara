// See frontend/.env.example. When true, the Metadata Workspace step's save
// action skips the real catalogue push (which needs a DB, and GCS when
// ENABLE_GCS=true) and proceeds as a pure UI click-through.
export const CLICK_THROUGH_ENABLED = import.meta.env.VITE_ENABLE_CLICK_THROUGH === 'true'
