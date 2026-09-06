'use client'

import { useRouter } from 'next/navigation'
import Console from '../../../components/Console'
import { useApp } from '../../../context/AppContext'

// Console.jsx still manages its own step (1-6) state/rendering internally --
// splitting it into real per-step routes is future work. This route just
// supplies the same navigation callbacks it used to get as plain props.
export default function ConsolePage() {
  const { keySaved } = useApp()
  const router = useRouter()
  return (
    <Console
      hasKey={keySaved}
      onGoSettings={() => router.push('/settings')}
      onGoDashboard={() => router.push('/dashboard')}
      onGoCatalogue={() => router.push('/catalogue')}
      onUploadAnother={() => {
        try { sessionStorage.removeItem('dhara_console_state_v1') } catch { /* best-effort */ }
        router.push('/console')
      }}
    />
  )
}
