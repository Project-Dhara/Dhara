// The user's LLM API key (and chosen provider). Persisted in Postgres via
// GET/POST /api/llm-key. localStorage is a short-lived cache so request
// headers stay available before the server round-trip completes; AppContext
// treats the API as the source of truth after login.
const STORAGE_KEY = 'dhara.llmApiKey'
const PROVIDER_STORAGE_KEY = 'dhara.llmProvider'
export const LLM_KEY_HEADER = 'X-Llm-Api-Key'
export const LLM_PROVIDER_HEADER = 'X-Llm-Provider'

export function getLlmApiKey(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setLlmApiKey(key: string) {
  try {
    if (key) localStorage.setItem(STORAGE_KEY, key)
    else localStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore (e.g. localStorage disabled)
  }
}

export function getLlmProvider(): string {
  try {
    return localStorage.getItem(PROVIDER_STORAGE_KEY) || ''
  } catch {
    return ''
  }
}

export function setLlmProvider(provider: string) {
  try {
    if (provider) localStorage.setItem(PROVIDER_STORAGE_KEY, provider)
    else localStorage.removeItem(PROVIDER_STORAGE_KEY)
  } catch {
    // ignore (e.g. localStorage disabled)
  }
}

// Merge the saved key (and provider, if set) into a fetch() init object's
// headers.
export function withLlmKeyHeaders(init: RequestInit = {}): RequestInit {
  const key = getLlmApiKey()
  if (!key) return init
  let provider = (getLlmProvider() || '').trim().toLowerCase()
  if (provider === 'meity-empanelled llm' || provider === 'openai' || provider === '') {
    provider = 'openai'
  } else if (provider === 'anthropic') {
    provider = 'anthropic'
  } else if (provider === 'self-hosted') {
    provider = ''
  }
  return {
    ...init,
    headers: {
      ...(init.headers || {}),
      [LLM_KEY_HEADER]: key,
      ...(provider ? { [LLM_PROVIDER_HEADER]: provider } : {}),
    },
  }
}
