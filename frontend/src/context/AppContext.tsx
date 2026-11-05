'use client'

// Cross-cutting app state: signed-in user, LLM credential status, KYDS modal flag,
// plus stale-while-revalidate caches for Dashboard + Catalogue list screens.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react'
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

type LlmKeyStatus = {
  configured: boolean
  provider: string
  apiKey: string
  cryptoError: boolean
}

export type DashboardStats = {
  datasets?: number
  data_products?: number
  awaiting_review?: number
  published?: number
  [key: string]: unknown
}

export type DashboardRow = {
  id?: string
  name?: string
  source?: string
  product?: string
  readiness_pct?: number
  status?: string
  action?: string
  href?: string
  [key: string]: unknown
}

export type DashboardData = {
  stats: DashboardStats
  rows: DashboardRow[]
}

export type CatalogueGroup = {
  id: string
  title?: string
  table_count?: number
  row_count?: number
  last_updated?: string | null
  [key: string]: unknown
}

type AppContextValue = {
  loggedIn: boolean
  authChecked: boolean
  user: StoredUser
  setUser: (u: StoredUser) => void
  showKyds: boolean
  setShowKyds: (v: boolean) => void
  settings: Settings
  keySaved: boolean
  llmCryptoError: boolean
  onSettingsChange: (next: Settings) => void
  onSaveKey: (override?: Settings) => void
  login: (data: LoginData) => void
  signOut: () => void
  dashboard: DashboardData | null
  dashboardLoading: boolean
  dashboardError: string | null
  ensureDashboard: () => void
  invalidateDashboard: () => void
  catalogueGroups: CatalogueGroup[] | null
  catalogueLoading: boolean
  catalogueError: string | null
  ensureCatalogue: () => void
  invalidateCatalogue: () => void
}

const AppCtx = createContext<AppContextValue | null>(null)

const EMPTY_USER: StoredUser = { name: '', role: '', email: '', dept: '' }
const WORKSPACE_STALE_MS = 30_000

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

async function fetchLlmKeyStatus(): Promise<LlmKeyStatus | null> {
  const res = await fetch('/api/llm-key', withAuthHeaders())
  if (!res.ok) return null
  const data = await res.json()
  return {
    configured: Boolean(data.configured),
    provider: normalizeProvider(String(data.provider || 'openai')),
    apiKey: typeof data.api_key === 'string' ? data.api_key : '',
    cryptoError: Boolean(data.crypto_error),
  }
}

function applyLlmStatus(
  status: LlmKeyStatus,
  setSettings: (s: Settings) => void,
  setKeySaved: (v: boolean) => void,
  setLlmCryptoError: (v: boolean) => void,
) {
  setLlmProvider(status.provider)
  setSettings({ provider: status.provider, apiKey: status.apiKey })
  setKeySaved(status.configured)
  setLlmCryptoError(status.cryptoError)
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [authChecked, setAuthChecked] = useState(false)
  const [loggedIn, setLoggedIn] = useState(false)
  const [user, setUser] = useState<StoredUser>(EMPTY_USER)
  const [showKyds, setShowKyds] = useState(false)
  const [settings, setSettings] = useState<Settings>({ provider: 'openai', apiKey: '' })
  const [keySaved, setKeySaved] = useState(false)
  const [llmCryptoError, setLlmCryptoError] = useState(false)

  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [dashboardLoading, setDashboardLoading] = useState(false)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const dashboardFetchedAt = useRef(0)
  const dashboardHasData = useRef(false)
  const dashboardInflight = useRef<Promise<void> | null>(null)

  const [catalogueGroups, setCatalogueGroups] = useState<CatalogueGroup[] | null>(null)
  const [catalogueLoading, setCatalogueLoading] = useState(false)
  const [catalogueError, setCatalogueError] = useState<string | null>(null)
  const catalogueFetchedAt = useRef(0)
  const catalogueHasData = useRef(false)
  const catalogueInflight = useRef<Promise<void> | null>(null)

  const clearWorkspaceCaches = useCallback(() => {
    setDashboard(null)
    setDashboardLoading(false)
    setDashboardError(null)
    dashboardFetchedAt.current = 0
    dashboardHasData.current = false
    dashboardInflight.current = null
    setCatalogueGroups(null)
    setCatalogueLoading(false)
    setCatalogueError(null)
    catalogueFetchedAt.current = 0
    catalogueHasData.current = false
    catalogueInflight.current = null
  }, [])

  const refreshDashboard = useCallback(async (opts?: { force?: boolean }) => {
    const force = Boolean(opts?.force)
    const fresh =
      dashboardFetchedAt.current > 0
      && Date.now() - dashboardFetchedAt.current < WORKSPACE_STALE_MS
    if (!force && fresh) return
    if (dashboardInflight.current) {
      await dashboardInflight.current
      return
    }

    // Keep last list visible; only blank-load on first visit.
    const silent = dashboardHasData.current
    if (!silent) setDashboardLoading(true)
    if (!silent) setDashboardError(null)

    const run = (async () => {
      try {
        const res = await fetch('/api/dashboard', withAuthHeaders())
        if (!res.ok) {
          const text = await res.text()
          throw new Error(text || `Could not load dashboard (${res.status})`)
        }
        const data = await res.json()
        setDashboard({
          stats: (data.stats || {}) as DashboardStats,
          rows: Array.isArray(data.rows) ? data.rows : [],
        })
        dashboardHasData.current = true
        dashboardFetchedAt.current = Date.now()
        setDashboardError(null)
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not load dashboard'
        // Keep last good list on background refresh failure.
        if (!silent) setDashboardError(message)
      } finally {
        setDashboardLoading(false)
        dashboardInflight.current = null
      }
    })()

    dashboardInflight.current = run
    await run
  }, [])

  const refreshCatalogue = useCallback(async (opts?: { force?: boolean }) => {
    const force = Boolean(opts?.force)
    const fresh =
      catalogueFetchedAt.current > 0
      && Date.now() - catalogueFetchedAt.current < WORKSPACE_STALE_MS
    if (!force && fresh) return
    if (catalogueInflight.current) {
      await catalogueInflight.current
      return
    }

    const silent = catalogueHasData.current
    if (!silent) setCatalogueLoading(true)
    if (!silent) setCatalogueError(null)

    const run = (async () => {
      try {
        const res = await fetch('/api/catalogue/groups', withAuthHeaders())
        if (!res.ok) {
          const text = await res.text()
          throw new Error(text || `Could not load catalogue (${res.status})`)
        }
        const data = await res.json()
        const rows = Array.isArray(data.groups) ? data.groups : []
        setCatalogueGroups(rows)
        catalogueHasData.current = true
        catalogueFetchedAt.current = Date.now()
        setCatalogueError(null)
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Could not load catalogue'
        if (!silent) setCatalogueError(message)
      } finally {
        setCatalogueLoading(false)
        catalogueInflight.current = null
      }
    })()

    catalogueInflight.current = run
    await run
  }, [])

  const ensureDashboard = useCallback(() => {
    void refreshDashboard()
  }, [refreshDashboard])

  const ensureCatalogue = useCallback(() => {
    void refreshCatalogue()
  }, [refreshCatalogue])

  const invalidateDashboard = useCallback(() => {
    dashboardFetchedAt.current = 0
    void refreshDashboard({ force: true })
  }, [refreshDashboard])

  const invalidateCatalogue = useCallback(() => {
    catalogueFetchedAt.current = 0
    void refreshCatalogue({ force: true })
  }, [refreshCatalogue])

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
          clearWorkspaceCaches()
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
          applyLlmStatus(status, setSettings, setKeySaved, setLlmCryptoError)
        }
      } catch {
        clearSession()
        if (!cancelled) {
          setLoggedIn(false)
          setUser(EMPTY_USER)
          clearWorkspaceCaches()
        }
      } finally {
        if (!cancelled) setAuthChecked(true)
      }
    }

    restoreSession()
    return () => { cancelled = true }
  }, [clearWorkspaceCaches])

  const handleSettingsChange = (next: Settings) => {
    setSettings(next)
    if (next.apiKey) setKeySaved(false)
    setLlmCryptoError(false)
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
        clearLegacyLlmKeyStorage()
        // Reload from DB so the visible key always comes from Postgres.
        const status = await fetchLlmKeyStatus()
        if (status) {
          applyLlmStatus(status, setSettings, setKeySaved, setLlmCryptoError)
        } else {
          setLlmProvider(provider)
          setSettings({ provider, apiKey: key })
          setKeySaved(Boolean(key))
          setLlmCryptoError(false)
        }
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
    clearWorkspaceCaches()
    void (async () => {
      const status = await fetchLlmKeyStatus()
      if (status) {
        applyLlmStatus(status, setSettings, setKeySaved, setLlmCryptoError)
      }
    })()
  }

  const signOut = () => {
    clearSession()
    clearLegacyLlmKeyStorage()
    setLlmProvider('')
    setSettings({ provider: 'openai', apiKey: '' })
    setKeySaved(false)
    setLlmCryptoError(false)
    setLoggedIn(false)
    setShowKyds(false)
    clearWorkspaceCaches()
  }

  const value: AppContextValue = {
    loggedIn, authChecked, user, setUser,
    showKyds, setShowKyds,
    settings, keySaved, llmCryptoError,
    onSettingsChange: handleSettingsChange,
    onSaveKey: handleSaveKey,
    login, signOut,
    dashboard,
    dashboardLoading,
    dashboardError,
    ensureDashboard,
    invalidateDashboard,
    catalogueGroups,
    catalogueLoading,
    catalogueError,
    ensureCatalogue,
    invalidateCatalogue,
  }

  return <AppCtx.Provider value={value}>{children}</AppCtx.Provider>
}

export function useApp() {
  const ctx = useContext(AppCtx)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
