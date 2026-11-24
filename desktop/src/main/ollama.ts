import { OLLAMA_ORIGIN, OLLAMA_OPENAI_BASE_URL } from './paths'

export interface OllamaStatus {
  reachable: boolean
  baseUrl: string
  models: string[]
  error?: string
}

/**
 * Read-only helper for the Settings “use a local model” opt-in.
 * Dhara never downloads, installs or starts Ollama. If the user installed it themselves
 * and it is running on 127.0.0.1:11434, this reports the models it has.
 */
export async function ollamaStatus(): Promise<OllamaStatus> {
  try {
    const res = await fetch(`${OLLAMA_ORIGIN}/api/tags`, { signal: AbortSignal.timeout(3000) })
    if (!res.ok) {
      return { reachable: false, baseUrl: OLLAMA_OPENAI_BASE_URL, models: [], error: `HTTP ${res.status}` }
    }
    const json = (await res.json()) as { models?: Array<{ name?: string }> }
    const models = (json.models ?? []).map((m) => m.name ?? '').filter(Boolean)
    return { reachable: true, baseUrl: OLLAMA_OPENAI_BASE_URL, models }
  } catch (err) {
    return {
      reachable: false,
      baseUrl: OLLAMA_OPENAI_BASE_URL,
      models: [],
      error: err instanceof Error ? err.message : String(err),
    }
  }
}

export const OLLAMA_DOWNLOAD_PAGE = 'https://ollama.com/download'
