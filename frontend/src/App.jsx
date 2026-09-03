import { useState } from 'react'
import AppShell from './components/AppShell'
import Auth from './components/Auth'
import Dashboard from './components/Dashboard'
import Settings from './components/Settings'
import Catalogue from './components/Catalogue'
import Console from './components/Console'
import KydsModal from './components/KydsModal'
import { getLlmApiKey, setLlmApiKey, getLlmProvider, setLlmProvider } from './llmKey'
import { getStoredUser, clearSession, setSession, withAuthHeaders } from './auth'
import { notifyKydsChanged } from './kydsEvents'

export default function App() {
  const storedUser = getStoredUser()
  const [loggedIn, setLoggedIn] = useState(!!storedUser)
  const [showKyds, setShowKyds] = useState(false)
  const [screen, setScreen] = useState(
    () => sessionStorage.getItem('dhara_screen_v1') || 'dashboard'
  ) // 'dashboard' | 'console' | 'catalogue' | 'settings'
  const [consoleKey, setConsoleKey] = useState(0)
  const [consoleVisited, setConsoleVisited] = useState(screen === 'console')

  const navigate = (next) => {
    setScreen(next)
    try {
      sessionStorage.setItem('dhara_screen_v1', next)
    } catch {
      // best-effort
    }
    if (next === 'console') setConsoleVisited(true)
  }

  const [user, setUser] = useState(
    storedUser || { name: '', role: 'Administrator', email: '', dept: '' }
  )
  const savedKey = getLlmApiKey()
  const [settings, setSettings] = useState({ provider: getLlmProvider() || 'Anthropic', apiKey: savedKey })
  const [keySaved, setKeySaved] = useState(!!savedKey)

  if (!loggedIn) {
    return (
      <Auth
        onSuccess={(data) => {
          const nextUser = { name: data.name || data.email, email: data.email, dept: data.dept || '', role: 'Administrator' }
          setSession(data.token, nextUser)
          setUser(nextUser)
          setLoggedIn(true)
          setShowKyds(true)
          navigate('dashboard')
        }}
      />
    )
  }

  const startFlow = () => {
    try {
      sessionStorage.removeItem('dhara_console_state_v1')
    } catch {
      // best-effort
    }
    setConsoleKey((k) => k + 1)
    navigate('console')
  }

  const handleSettingsChange = (next) => {
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

  return (
    <AppShell
      screen={screen}
      user={user}
      onNavigate={navigate}
      onSignOut={() => { clearSession(); setLoggedIn(false); setShowKyds(false) }}
    >
      {showKyds && (
        <KydsModal
          onSkip={() => setShowKyds(false)}
          onSave={async (form) => {
            const res = await fetch('/api/kyds', withAuthHeaders({
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ responses: form }),
            }))
            if (!res.ok) {
              const err = await res.json().catch(() => ({}))
              throw new Error(err.detail || 'Could not save KYDS entry — please try again.')
            }
            setShowKyds(false)
            notifyKydsChanged()
          }}
        />
      )}
      {screen === 'dashboard' && <Dashboard onStartFlow={startFlow} />}

      {/* Kept mounted (hidden via CSS, not removed from the tree) once
          visited, so navigating away to Settings/Catalogue and back doesn't
          wipe in-progress flow state. Only an explicit "start new flow"
          (startFlow) remounts it via consoleKey. */}
      {consoleVisited && (
        <div style={{ display: screen === 'console' ? 'contents' : 'none' }}>
          <Console
            key={consoleKey}
            hasKey={keySaved}
            onGoSettings={() => navigate('settings')}
            onGoDashboard={() => navigate('dashboard')}
            onGoCatalogue={() => navigate('catalogue')}
            onUploadAnother={startFlow}
          />
        </div>
      )}

      {screen === 'catalogue' && (
        <Catalogue hasKey={keySaved} onGoSettings={() => navigate('settings')} />
      )}

      {screen === 'settings' && (
        <Settings
          settings={settings}
          onSettingsChange={handleSettingsChange}
          keySaved={keySaved}
          onSaveKey={handleSaveKey}
          user={user}
          onUserChange={setUser}
        />
      )}
    </AppShell>
  )
}
