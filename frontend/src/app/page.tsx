'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { useApp } from '../context/AppContext'

export default function RootPage() {
  const { authChecked, loggedIn } = useApp()
  const router = useRouter()

  useEffect(() => {
    if (!authChecked) return
    router.replace(loggedIn ? '/dashboard' : '/login')
  }, [authChecked, loggedIn, router])

  return null
}
