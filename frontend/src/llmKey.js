// The user's own LLM API key (and chosen provider), entered in Settings.
// Persisted in localStorage so it survives reloads; sent to the backend on
// every LLM-backed request instead of relying on the backend's own .env
// key/SKIP_LLM toggle.
const STORAGE_KEY = 'dhara.llmApiKey'
const PROVIDER_STORAGE_KEY = 'dhara.llmProvider'
export const LLM_KEY_HEADER = 'X-Llm-Api-Key'
export const LLM_PROVIDER_HEADER = 'X-Llm-Provider'

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

export function getLlmProvider() {
  try {
    return localStorage.getItem(PROVIDER_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setLlmProvider(provider) {
  try {
    if (provider) localStorage.setItem(PROVIDER_STORAGE_KEY, provider)
    else localStorage.removeItem(PROVIDER_STORAGE_KEY)
  } catch {
    // ignore (e.g. localStorage disabled)
  }
}

// Merge the saved key (and provider, if set) into a fetch() init object's
// headers.
export function withLlmKeyHeaders(init = {}) {
  const key = getLlmApiKey()
  if (!key) return init
  const provider = getLlmProvider()
  return {
    ...init,
    headers: {
      ...(init.headers || {}),
      [LLM_KEY_HEADER]: key,
      ...(provider ? { [LLM_PROVIDER_HEADER]: provider } : {}),
    },
  }
}
