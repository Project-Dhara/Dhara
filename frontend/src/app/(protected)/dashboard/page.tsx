'use client'

import { useRouter } from 'next/navigation'
import Dashboard from '../../../components/Dashboard'
import { goToConsoleFiles } from '../../../lib/consoleSession'

export default function DashboardPage() {
  const router = useRouter()
  return (
    <Dashboard
      onStartFlow={() => {
        goToConsoleFiles(router)
      }}
    />
  )
}
