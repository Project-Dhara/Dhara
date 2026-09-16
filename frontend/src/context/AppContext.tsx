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
  onSaveKey: () => void
  login: (data: LoginData) => void
  signOut: () => void
}

const AppCtx = createContext<AppContextValue | null>(null)

const EMPTY_USER: StoredUser = { name: '', role: 'Administrator', email: '', dept: '' }

export function AppProvider({ children }: { children: ReactNode }) {
  // Auth state is only known for certain once mounted on the client
  // (localStorage doesn't exist during server rendering) -- authChecked
  // gates any redirect logic until after that first client-side check, to
  // avoid a false "logged out" flash/hydration mismatch.
  const [authChecked, setAuthChecked] = useState(false)
  const [loggedIn, setLoggedIn] = useState(false)
  const [user, setUser] = useState<StoredUser>(EMPTY_USER)
  const [showKyds, setShowKyds] = useState(false)
  const [settings, setSettings] = useState<Settings>({ provider: 'Anthropic', apiKey: '' })
  const [keySaved, setKeySaved] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function restoreSession() {
      const savedKey = getLlmApiKey()
      setSettings({ provider: getLlmProvider() || 'Anthropic', apiKey: savedKey })
      setKeySaved(!!savedKey)

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
        // Confirm the token is still valid for this backend process. A
        // restart rotates AUTH_INSTANCE_ID and returns 401 here.
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

  const handleSaveKey = () => {
    setLlmApiKey(settings.apiKey.trim())
    setLlmProvider(settings.provider.trim())
    setKeySaved(!!settings.apiKey.trim())
  }

  const login = (data: LoginData) => {
    const nextUser: StoredUser = { name: data.name || data.email, email: data.email, dept: data.dept || '', role: 'Administrator' }
    setSession(data.token, nextUser)
    setUser(nextUser)
    setLoggedIn(true)
    setShowKyds(true)
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
