'use client'

import { useRouter } from 'next/navigation'
import Catalogue from '../../../components/catalogue/Catalogue'
import { useApp } from '../../../context/AppContext'

export default function CataloguePage() {
  const { keySaved } = useApp()
  const router = useRouter()
  return <Catalogue hasKey={keySaved} onGoSettings={() => router.push('/settings')} />
}
