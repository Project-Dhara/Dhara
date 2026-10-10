'use client'

// Cross-cutting app state that isn't owned by any one route: the signed-in
// user, LLM key/provider settings, and the "show KYDS modal" flag (KYDS is
// an overlay shown on top of whatever route is active, not a route itself).
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { getLlmApiKey, setLlmApiKey, getLlmProvider, setLlmProvider } from '../lib/llmKey'
import {
  getToken,
  getStoredUser,
  clearSession,
  setSession,
  withAuthHeaders,
  type StoredUser,
} from '../lib/auth'

type LoginData = { token: string; email: string; name?: string; dept?: string }
type Settings = { provider: string; apiKey: string }

type AppContextValue = {
  loggedIn: boolean
  authChecked: boolean
  user: StoredUser
  setUser: (u: StoredUser) => void
  showKyds: boolean
  setShowKyds: (v: boolean) => void
  settings: Settings
  keySaved: boolean
  onSettingsChange: (next: Settings) => void
  onSaveKey: (override?: Settings) => void
  login: (data: LoginData) => void
  signOut: () => void
}

const AppCtx = createContext<AppContextValue | null>(null)

const EMPTY_USER: StoredUser = { name: '', role: 'Administrator', email: '', dept: '' }

function normalizeProvider(raw: string): string {
  if (raw === 'OpenAI' || raw === 'Anthropic' || raw === 'MEITY-empanelled LLM') {
    return 'openai'
  }
  return raw || 'openai'
}

async function fetchStoredLlmKey(): Promise<Settings | null> {
  const res = await fetch('/api/llm-key', withAuthHeaders())
  if (!res.ok) return null
  const data = await res.json()
  const apiKey = String(data.api_key || '').trim()
  if (!apiKey) return { provider: 'openai', apiKey: '' }
  return {
    provider: normalizeProvider(String(data.provider || 'openai')),
    apiKey,
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  // Auth state is only known for certain once mounted on the client
  // (localStorage doesn't exist during server rendering) -- authChecked
  // gates any redirect logic until after that first client-side check, to
  // avoid a false "logged out" flash/hydration mismatch.
  const [authChecked, setAuthChecked] = useState(false)
  const [loggedIn, setLoggedIn] = useState(false)
  const [user, setUser] = useState<StoredUser>(EMPTY_USER)
  const [showKyds, setShowKyds] = useState(false)
  const [settings, setSettings] = useState<Settings>({ provider: 'openai', apiKey: '' })
  const [keySaved, setKeySaved] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      // Cache only until /api/me succeeds and we load from Postgres.
      const cachedKey = getLlmApiKey()
      const cachedProvider = normalizeProvider(getLlmProvider() || 'openai')
      setSettings({ provider: cachedProvider, apiKey: cachedKey })
      setKeySaved(!!cachedKey)

      const token = getToken()
      const storedUser = getStoredUser()
      if (!token || !storedUser) {
        clearSession()
        if (!cancelled) {
          setLoggedIn(false)
          setUser(EMPTY_USER)
          setAuthChecked(true)
        }
        return
      }

      try {
        // Confirm the token is still valid. An expired/invalid JWT returns 401 here.
        const res = await fetch('/api/me', withAuthHeaders())
        if (!res.ok) throw new Error('session invalid')
        const data = await res.json()
        if (cancelled) return
        const nextUser: StoredUser = {
          name: data.name || storedUser.name || data.email,
          email: data.email || storedUser.email,
          dept: data.dept || storedUser.dept || '',
          role: storedUser.role || 'Administrator',
        }
        setSession(token, nextUser)
        setUser(nextUser)
        setLoggedIn(true)

        const fromServer = await fetchStoredLlmKey()
        if (!cancelled && fromServer) {
          setLlmApiKey(fromServer.apiKey)
          setLlmProvider(fromServer.provider)
          setSettings(fromServer)
          setKeySaved(!!fromServer.apiKey)
        }
      } catch {
        clearSession()
        if (!cancelled) {
          setLoggedIn(false)
          setUser(EMPTY_USER)
        }
      } finally {
        if (!cancelled) setAuthChecked(true)
      }
    }

    restoreSession()
    return () => { cancelled = true }
  }, [])

  const handleSettingsChange = (next: Settings) => {
    setSettings(next)
    // Editing the key after it was saved invalidates the "saved" state until
    // it's explicitly saved again.
    if (next.apiKey !== getLlmApiKey()) setKeySaved(false)
  }

  const handleSaveKey = (override?: Settings) => {
    // Button onClick may pass a click event — only treat plain settings objects as overrides.
    const fromForm = override && typeof override === 'object' && 'apiKey' in override
      ? override
      : null
    const next = fromForm || settings
    const key = String(next.apiKey || '').trim()
    const provider = String(next.provider || '').trim() || 'openai'
    setSettings({ provider, apiKey: key })

    void (async () => {
      try {
        const res = await fetch('/api/llm-key', withAuthHeaders({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ api_key: key, provider }),
        }))
        if (!res.ok) {
          setKeySaved(false)
          return
        }
        setLlmApiKey(key)
        setLlmProvider(provider)
        setKeySaved(!!key)
      } catch {
        setKeySaved(false)
      }
    })()
  }

  const login = (data: LoginData) => {
    const nextUser: StoredUser = { name: data.name || data.email, email: data.email, dept: data.dept || '', role: 'Administrator' }
    setSession(data.token, nextUser)
    setUser(nextUser)
    setLoggedIn(true)
    setShowKyds(true)
    void (async () => {
      const fromServer = await fetchStoredLlmKey()
      if (fromServer) {
        setLlmApiKey(fromServer.apiKey)
        setLlmProvider(fromServer.provider)
        setSettings(fromServer)
        setKeySaved(!!fromServer.apiKey)
      }
    })()
  }

  const signOut = () => {
    clearSession()
    setLoggedIn(false)
    setShowKyds(false)
  }

  const value: AppContextValue = {
    loggedIn, authChecked, user, setUser,
    showKyds, setShowKyds,
    settings, keySaved,
    onSettingsChange: handleSettingsChange,
    onSaveKey: handleSaveKey,
    login, signOut,
  }

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>
}

export function useApp() {
  const ctx = useContext(AppCtx)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
