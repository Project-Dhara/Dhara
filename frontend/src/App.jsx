import { useState } from 'react'
import AppShell from './components/AppShell'
import Auth from './components/Auth'
import Dashboard from './components/Dashboard'
import Settings from './components/Settings'
import Catalogue from './components/Catalogue'
import Console from './components/Console'
import { getLlmApiKey, setLlmApiKey } from './llmKey'

export default function App() {
  const [authScreen, setAuthScreen] = useState('login') // 'login' | 'signup'
  const [loggedIn, setLoggedIn] = useState(false)
  const [screen, setScreen] = useState('dashboard') // 'dashboard' | 'console' | 'catalogue' | 'settings'
  const [consoleKey, setConsoleKey] = useState(0)

  const [user, setUser] = useState({
    name: 'A. Menon',
    role: 'Administrator',
    email: 'a.menon@gov.in',
    dept: 'Directorate of Economics and Statistics',
  })
  const savedKey = getLlmApiKey()
  const [settings, setSettings] = useState({ provider: 'Anthropic', apiKey: savedKey })
  const [keySaved, setKeySaved] = useState(!!savedKey)

  if (!loggedIn) {
    return (
      <Auth
        screen={authScreen}
        onToggle={() => setAuthScreen((s) => (s === 'signup' ? 'login' : 'signup'))}
        onSubmit={(form) => {
          setUser((prev) => ({ ...prev, name: form.name || prev.name, email: form.email || prev.email }))
          setLoggedIn(true)
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
    setKeySaved(!!settings.apiKey.trim())
  }

  return (
    <AppShell
      screen={screen}
      user={user}
      onNavigate={setScreen}
      onSignOut={() => { setLoggedIn(false); setAuthScreen('login') }}
    >
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
