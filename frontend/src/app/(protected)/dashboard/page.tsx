'use client'

import { useRouter } from 'next/navigation'
import Dashboard from '../../../components/Dashboard'
import { clearConsoleSession } from '../../../lib/consoleSession'

export default function DashboardPage() {
  const router = useRouter()
  return (
    <Dashboard
      onStartFlow={() => {
        clearConsoleSession()
        router.push('/console')
      }}
    />
  )
}
