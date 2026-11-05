'use client'

import { useRouter } from 'next/navigation'
import Console from '../../../components/console/Console'
import { useApp } from '../../../context/AppContext'
import { goToConsoleFiles } from '../../../lib/consoleSession'

// Console.jsx still manages its own step (1-6) state/rendering internally --
// splitting it into real per-step routes is future work. This route just
// supplies the same navigation callbacks it used to get as plain props.
export default function ConsolePage() {
  const { keySaved, invalidateDashboard, invalidateCatalogue } = useApp()
  const router = useRouter()
  return (
    <Console
      hasKey={keySaved}
      onGoSettings={() => router.push('/settings')}
      onGoDashboard={() => {
        invalidateDashboard()
        router.push('/dashboard')
      }}
      onGoCatalogue={() => {
        invalidateCatalogue()
        router.push('/catalogue')
      }}
      onUploadAnother={() => {
        goToConsoleFiles(router)
      }}
    />
  )
}
