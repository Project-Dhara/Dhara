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

export default function App() {
  const storedUser = getStoredUser()
  const [loggedIn, setLoggedIn] = useState(!!storedUser)
  const [showKyds, setShowKyds] = useState(false)
  const [screen, setScreen] = useState('dashboard') // 'dashboard' | 'console' | 'catalogue' | 'settings'
  const [consoleKey, setConsoleKey] = useState(0)

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
          setScreen('dashboard')
        }}
      />
    )
  }

  const startFlow = () => {
    setConsoleKey((k) => k + 1)
    setScreen('console')
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
      onNavigate={setScreen}
      onSignOut={() => { clearSession(); setLoggedIn(false); setShowKyds(false) }}
    >
      {showKyds && (
        <KydsModal
          onSkip={() => setShowKyds(false)}
          onSave={async (form) => {
            try {
              await fetch('/api/kyds', withAuthHeaders({
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ responses: form }),
              }))
            } finally {
              setShowKyds(false)
            }
          }}
        />
      )}
      {screen === 'dashboard' && <Dashboard onStartFlow={startFlow} />}

      {screen === 'console' && (
        <Console
          key={consoleKey}
          hasKey={keySaved}
          onGoSettings={() => setScreen('settings')}
          onGoDashboard={() => setScreen('dashboard')}
          onGoCatalogue={() => setScreen('catalogue')}
          onUploadAnother={startFlow}
        />
      )}

      {screen === 'catalogue' && (
        <Catalogue hasKey={keySaved} onGoSettings={() => setScreen('settings')} />
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
