// The user's own LLM API key, entered in Settings. Persisted in localStorage
// so it survives reloads; sent to the backend on every LLM-backed request
// instead of relying on the backend's own .env key/SKIP_LLM toggle.
const STORAGE_KEY = 'dhara.llmApiKey'
export const LLM_KEY_HEADER = 'X-Llm-Api-Key'

export function getLlmApiKey() {
  try {
    return localStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setLlmApiKey(key) {
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore (e.g. localStorage disabled)
  }
}

// Merge the saved key into a fetch() init object's headers, if one is set.
export function withLlmKeyHeaders(init = {}) {
  const key = getLlmApiKey()
  if (!key) return init
  return { ...init, headers: { ...(init.headers || {}), [LLM_KEY_HEADER]: key } }
}
