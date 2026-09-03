// See frontend/.env.example. When true, Continue to publish skips the real
// catalogue write (needs a DB, and GCS when ENABLE_GCS=true) and proceeds
// as a pure UI click-through.
export const CLICK_THROUGH_ENABLED = import.meta.env.VITE_ENABLE_CLICK_THROUGH === 'true'
