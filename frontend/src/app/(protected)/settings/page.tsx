'use client'

import Settings from '../../../components/Settings'
import { useApp } from '../../../context/AppContext'

export default function SettingsPage() {
  const { settings, onSettingsChange, keySaved, onSaveKey, user, setUser } = useApp()
  return (
    <Settings
      settings={settings}
      onSettingsChange={onSettingsChange}
      keySaved={keySaved}
      onSaveKey={onSaveKey}
      user={user}
      onUserChange={setUser}
    />
  )
}
