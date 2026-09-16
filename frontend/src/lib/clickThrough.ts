// See frontend/.env.example. When true, Continue to publish skips the real
// catalogue write (needs a DB, and GCS when ENABLE_GCS=true) and proceeds
// as a pure UI click-through. Next.js exposes client-side env vars via the
// NEXT_PUBLIC_ prefix (Vite's old VITE_ prefix doesn't apply here).
export const CLICK_THROUGH_ENABLED = process.env.NEXT_PUBLIC_ENABLE_CLICK_THROUGH === 'true'
