import type { Metadata } from 'next'
import { AppProvider } from '../context/AppContext'
import './globals.css'

export const metadata: Metadata = {
  title: 'DHARA TOOLKIT',
  icons: { icon: '/favicon.png' },
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link
          href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap"
          rel="stylesheet"
        />
      </head>
      <body className="h-screen overflow-hidden bg-outer-bg font-body text-ink">
        <AppProvider>{children}</AppProvider>
      </body>
    </html>
  )
}
