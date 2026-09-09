'use client'

import { useEffect } from 'react'
import { usePathname, useRouter } from 'next/navigation'
import AppShell from '../../components/AppShell'
import KydsModal from '../../components/KydsModal'
import { useApp } from '../../context/AppContext'
import { withAuthHeaders } from '../../lib/auth'
import { notifyKydsChanged } from '../../lib/kydsEvents'
import { getConsoleReturnPath, rememberConsoleReturnPath } from '../../lib/consoleSession'

function screenForPathname(pathname: string) {
  if (pathname.startsWith('/console')) return 'console'
  if (pathname.startsWith('/catalogue')) return 'catalogue'
  if (pathname.startsWith('/settings')) return 'settings'
  return 'dashboard'
}

const PATH_FOR_SCREEN: Record<string, string> = {
  dashboard: '/dashboard',
  console: '/console',
  catalogue: '/catalogue',
  settings: '/settings',
}

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { authChecked, loggedIn, user, showKyds, setShowKyds, signOut } = useApp()
  const pathname = usePathname()
  const router = useRouter()

  useEffect(() => {
    if (authChecked && !loggedIn) router.replace('/login')
  }, [authChecked, loggedIn, router])

  // Remember deep console routes (PDF processing / review / grouping) so
  // AppShell → Console returns to the in-progress job after Settings.
  useEffect(() => {
    if (pathname) rememberConsoleReturnPath(pathname)
  }, [pathname])

  if (!authChecked || !loggedIn) return null // brief, avoids a logged-out flash before the client-side check runs

  return (
    <AppShell
      screen={screenForPathname(pathname)}
      user={user}
      onNavigate={(key: string) => {
        if (key === 'console') {
          router.push(getConsoleReturnPath() || '/console')
          return
        }
        router.push(PATH_FOR_SCREEN[key] || '/dashboard')
      }}
      onSignOut={() => { signOut(); router.push('/login') }}
    >
      {showKyds && (
        <KydsModal
          onSkip={() => setShowKyds(false)}
          onSave={async (form: unknown) => {
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
      {children}
    </AppShell>
  )
}
