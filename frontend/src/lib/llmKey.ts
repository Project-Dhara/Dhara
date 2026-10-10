// LLM credential status helpers. The raw API key is never stored in
// localStorage and is never sent on subsequent requests — the backend
// decrypts the stored secret for provider calls.

const PROVIDER_STORAGE_KEY = 'dhara.llmProvider'

/** @deprecated Cleared on load; do not write secrets here. */
const LEGACY_KEY_STORAGE = 'dhara.llmApiKey'

export function clearLegacyLlmKeyStorage() {
  try {
    localStorage.removeItem(LEGACY_KEY_STORAGE)
  } catch {
    // ignore
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

/** Auth-only headers — LLM keys stay server-side. */
export function withLlmKeyHeaders(init: RequestInit = {}): RequestInit {
  return init
}
