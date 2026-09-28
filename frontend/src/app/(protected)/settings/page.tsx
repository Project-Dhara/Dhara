'use client'

import { Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import Settings from '../../../components/Settings'
import { useApp } from '../../../context/AppContext'

function SettingsPageInner() {
  const { settings, onSettingsChange, keySaved, onSaveKey, user, setUser } = useApp()
  const searchParams = useSearchParams()
  const initialTab = searchParams.get('tab') || undefined
  return (
    <Settings
      settings={settings}
      onSettingsChange={onSettingsChange}
      keySaved={keySaved}
      onSaveKey={onSaveKey}
      user={user}
      onUserChange={setUser}
      initialTab={initialTab}
    />
  )
}

export default function SettingsPage() {
  return (
    <Suspense fallback={<div className="p-6 text-sm text-ink-soft">Loading settings…</div>}>
      <SettingsPageInner />
    </Suspense>
  )
}
