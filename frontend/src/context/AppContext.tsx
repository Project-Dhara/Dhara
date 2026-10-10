'use client'

// Cross-cutting app state: signed-in user, LLM credential status, KYDS modal flag.
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import {
  clearLegacyLlmKeyStorage,
  getLlmProvider,
  setLlmProvider,
} from '../lib/llmKey'
import {
  getToken,
  getStoredUser,
  clearSession,
  setSession,
  withAuthHeaders,
  type StoredUser,
} from '../lib/auth'

type LoginData = {
  token: string
  email: string
  name?: string
  dept?: string
  role?: string
}

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

const EMPTY_USER: StoredUser = { name: '', role: '', email: '', dept: '' }

function normalizeProvider(raw: string): string {
  if (raw === 'OpenAI' || raw === 'Anthropic' || raw === 'MEITY-empanelled LLM') {
    return 'openai'
  }
  return raw || 'openai'
}

function normalizeRole(raw: string | undefined | null): string {
  const r = (raw || '').trim().toLowerCase().replace(/\s+/g, '_')
  if (r === 'administrator' || r === 'admin') return 'Administrator'
  if (r === 'data_steward' || r === 'data-steward') return 'Data Steward'
  if (r === 'data_user' || r === 'data-user') return 'Data User'
  if (raw === 'Administrator' || raw === 'Data Steward' || raw === 'Data User') return raw
  return raw || ''
}

async function fetchLlmKeyStatus(): Promise<{ configured: boolean; provider: string } | null> {
  const res = await fetch('/api/llm-key', withAuthHeaders())
  if (!res.ok) return null
  const data = await res.json()
  return {
    configured: Boolean(data.configured),
    provider: normalizeProvider(String(data.provider || 'openai')),
  }
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [authChecked, setAuthChecked] = useState(false)
  const [loggedIn, setLoggedIn] = useState(false)
  const [user, setUser] = useState<StoredUser>(EMPTY_USER)
  const [showKyds, setShowKyds] = useState(false)
  const [settings, setSettings] = useState<Settings>({ provider: 'openai', apiKey: '' })
  const [keySaved, setKeySaved] = useState(false)

  useEffect(() => {
    let cancelled = false
    clearLegacyLlmKeyStorage()

    async function restoreSession() {
      const cachedProvider = normalizeProvider(getLlmProvider() || 'openai')
      setSettings({ provider: cachedProvider, apiKey: '' })

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
        const res = await fetch('/api/me', withAuthHeaders())
        if (!res.ok) throw new Error('session invalid')
        const data = await res.json()
        if (cancelled) return
        const nextUser: StoredUser = {
          name: data.name || storedUser.name || data.email,
          email: data.email || storedUser.email,
          dept: data.dept || storedUser.dept || '',
          role: normalizeRole(data.role) || normalizeRole(storedUser.role),
        }
        setSession(token, nextUser)
        setUser(nextUser)
        setLoggedIn(true)

        const status = await fetchLlmKeyStatus()
        if (!cancelled && status) {
          setLlmProvider(status.provider)
          setSettings({ provider: status.provider, apiKey: '' })
          setKeySaved(status.configured)
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
    if (next.apiKey) setKeySaved(false)
  }

  const handleSaveKey = (override?: Settings) => {
    const fromForm = override && typeof override === 'object' && 'apiKey' in override
      ? override
      : null
    const next = fromForm || settings
    const key = String(next.apiKey || '').trim()
    const provider = String(next.provider || '').trim() || 'openai'

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
        const data = await res.json().catch(() => ({}))
        setLlmProvider(provider)
        // Clear the input — the server holds the secret.
        setSettings({ provider, apiKey: '' })
        setKeySaved(Boolean(data.configured) || Boolean(key))
        clearLegacyLlmKeyStorage()
      } catch {
        setKeySaved(false)
      }
    })()
  }

  const login = (data: LoginData) => {
    const nextUser: StoredUser = {
      name: data.name || data.email,
      email: data.email,
      dept: data.dept || '',
      role: normalizeRole(data.role),
    }
    setSession(data.token, nextUser)
    setUser(nextUser)
    setLoggedIn(true)
    setShowKyds(true)
    void (async () => {
      const status = await fetchLlmKeyStatus()
      if (status) {
        setLlmProvider(status.provider)
        setSettings({ provider: status.provider, apiKey: '' })
        setKeySaved(status.configured)
      }
    })()
  }

  const signOut = () => {
    clearSession()
    clearLegacyLlmKeyStorage()
    setLlmProvider('')
    setSettings({ provider: 'openai', apiKey: '' })
    setKeySaved(false)
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
