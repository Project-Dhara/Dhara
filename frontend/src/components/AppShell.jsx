'use client'

// Persistent app shell: logo, tri-color accent bar, primary nav, user card.
// Wraps every in-app screen (Dashboard / Console / Catalogue / Settings).
// Served from public/ (root-relative path) rather than imported as a module
// -- Next's bundler wraps imported image modules in a {src,width,height}
// object for next/image, which would break a plain <img src=...>.
import { LayoutDashboard, Library, Settings, TerminalSquare } from 'lucide-react'

export function DharaLogo({ compact }) {
  return (
    <img
      className={compact ? 'block h-auto w-[132px]' : 'block h-auto w-[168px]'}
      src="/dhara-logo.png"
      alt="Data Dhara"
    />
  )
}

export function TriBar({ className = '' }) {
  return (
    <div className={`flex h-1 gap-1 ${className}`}>
      <div className="flex-1 bg-yellow" />
      <div className="flex-1 bg-green" />
      <div className="flex-1 bg-coral" />
    </div>
  )
}

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard', Icon: LayoutDashboard },
  { key: 'console', label: 'Management Console', Icon: TerminalSquare },
  { key: 'catalogue', label: 'Catalogue', Icon: Library },
]

export default function AppShell({ screen, user, onNavigate, onSignOut, children }) {
  const initials = (user?.name || '')
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w[0])
    .join('')
    .slice(0, 2)
    .toUpperCase()

  return (
    <div className="flex h-screen w-full">
      <nav className="flex w-[232px] flex-none flex-col border-r border-line bg-white py-[22px]">
        <div className="px-5 pb-3">
          <DharaLogo compact />
        </div>
        <TriBar className="mx-5 my-3.5 mb-[18px]" />
        <div className="flex flex-col">
          {NAV_ITEMS.map((item) => (
            <div
              key={item.key}
              className={`flex cursor-pointer items-center gap-2.5 border-l-[3px] px-5 py-2.5 text-[15px] transition-colors ${
                screen === item.key
                  ? 'border-teal bg-cream font-semibold text-ink'
                  : 'border-transparent text-ink-soft hover:bg-cream hover:text-ink'
              }`}
              onClick={() => onNavigate(item.key)}
            >
              <item.Icon className="h-4 w-4 flex-none" strokeWidth={1.75} aria-hidden />
              {item.label}
            </div>
          ))}
        </div>
        <div className="mt-auto flex flex-col gap-3">
          <div
            className={`flex cursor-pointer items-center gap-2.5 border-l-[3px] px-5 py-2.5 text-[15px] transition-colors ${
              screen === 'settings'
                ? 'border-teal bg-cream font-semibold text-ink'
                : 'border-transparent text-ink-soft hover:bg-cream hover:text-ink'
            }`}
            onClick={() => onNavigate('settings')}
          >
            <Settings className="h-4 w-4 flex-none" strokeWidth={1.75} aria-hidden />
            Settings
          </div>
          <div className="mx-5 mt-1 flex items-center gap-2.5 border-t border-line pt-4">
            <div className="flex h-8 w-8 flex-none items-center justify-center rounded-full bg-sage text-[13px] font-semibold text-teal">
              {initials || 'U'}
            </div>
            <div className="flex min-w-0 flex-col">
              <div className="truncate text-sm font-semibold text-ink" title={user?.name}>{user?.name}</div>
              <div className="text-xs text-ink-soft">{user?.role}</div>
            </div>
          </div>
          <div className="cursor-pointer px-5 pb-1 text-[13px] text-ink-soft hover:text-ink" onClick={onSignOut}>Sign out</div>
        </div>
      </nav>

      <div className="flex min-w-0 flex-1 flex-col bg-cream">
        {/* Padding lives on an inner wrapper (not the scrollport) so position:sticky
            children can stick flush to the top with no padding gap above them.
            has-[.cat-screen]: Catalogue.jsx manages its own internal scroll. */}
        <div className="min-h-0 flex-1 overflow-y-auto has-[.cat-screen]:flex has-[.cat-screen]:flex-col has-[.cat-screen]:overflow-hidden">
          <div className="p-[30px] px-8 has-[.cat-screen]:flex has-[.cat-screen]:min-h-0 has-[.cat-screen]:flex-1 has-[.cat-screen]:flex-col has-[.cat-screen]:overflow-hidden">
            {children}
          </div>
        </div>
      </div>
    </div>
  )
}
