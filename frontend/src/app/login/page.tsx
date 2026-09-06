'use client'

import { useRouter } from 'next/navigation'
import Auth from '../../components/Auth'
import { useApp } from '../../context/AppContext'

export default function LoginPage() {
  const { login } = useApp()
  const router = useRouter()
  return (
    <Auth
      onSuccess={(data: any) => {
        login(data)
        router.push('/dashboard')
      }}
    />
  )
}
