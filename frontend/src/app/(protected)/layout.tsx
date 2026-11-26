'use client'

import { Suspense, useEffect } from 'react'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import AppShell from '../../components/AppShell'
import KydsModal from '../../components/KydsModal'
import { useApp } from '../../context/AppContext'
import { withAuthHeaders } from '../../lib/auth'
import { notifyKydsChanged } from '../../lib/kydsEvents'
import { markKydsSavedThisSession, resetMineKyds } from '../../lib/kydsFilled'
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

function ProtectedLayoutInner({ children }: { children: React.ReactNode }) {
  const { authChecked, loggedIn, user, showKyds, setShowKyds, signOut } = useApp()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const router = useRouter()
  const search = searchParams?.toString() || ''

  useEffect(() => {
    if (authChecked && !loggedIn) router.replace('/login')
  }, [authChecked, loggedIn, router])

  // Remember the latest Console location (main /console or PDF deep links) so
  // AppShell → Console returns to where the user left off — not a stale job.
  useEffect(() => {
    if (!pathname) return
    rememberConsoleReturnPath(search ? `${pathname}?${search}` : pathname)
  }, [pathname, search])

  if (!authChecked || !loggedIn) return null // brief, avoids a logged-out flash before the client-side check runs

  // Full-page table editor: skip AppShell chrome for maximum workspace.
  const isTableEditor = Boolean(
    pathname
    && (
      pathname.startsWith('/console/review/edit')
      || pathname.startsWith('/console/preview/edit')
    ),
  )
  if (isTableEditor) {
    return <>{children}</>
  }

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
          onSkip={() => {
            setShowKyds(false)
            // Skipping must not leave a previous upload's KYDS as "mine".
            void resetMineKyds()
          }}
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
            markKydsSavedThisSession()
            setShowKyds(false)
            notifyKydsChanged()
          }}
        />
      )}
      {children}
    </AppShell>
  )
}

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  return (
    <Suspense fallback={null}>
      <ProtectedLayoutInner>{children}</ProtectedLayoutInner>
    </Suspense>
  )
}
