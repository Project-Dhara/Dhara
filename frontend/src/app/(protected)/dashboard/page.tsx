'use client'

import { useRouter } from 'next/navigation'
import Dashboard from '../../../components/Dashboard'

export default function DashboardPage() {
  const router = useRouter()
  return (
    <Dashboard
      onStartFlow={() => {
        try { sessionStorage.removeItem('dhara_console_state_v1') } catch { /* best-effort */ }
        router.push('/console')
      }}
    />
  )
}
