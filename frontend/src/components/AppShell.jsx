// Persistent app shell: logo, tri-color accent bar, primary nav, user card.
// Wraps every in-app screen (Dashboard / Console / Catalogue / Settings).
import dharaLogo from '../assets/dhara-logo.png'

export function DharaLogo({ compact }) {
  return (
    <img
      className={`dhara-logo${compact ? ' dhara-logo-compact' : ''}`}
      src={dharaLogo}
      alt="Data Dhara"
    />
  )
}

export function TriBar() {
  return (
    <div className="dhara-tribar">
      <div className="dhara-tribar-seg dhara-tribar-yellow" />
      <div className="dhara-tribar-seg dhara-tribar-green" />
      <div className="dhara-tribar-seg dhara-tribar-coral" />
    </div>
  )
}

const NAV_ITEMS = [
  { key: 'dashboard', label: 'Dashboard' },
  { key: 'console', label: 'Management Console' },
  { key: 'catalogue', label: 'Catalogue' },
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
    <div className="app-shell">
      <nav className="app-shell-nav">
        <div className="app-shell-logo-box">
          <DharaLogo compact />
        </div>
        <TriBar />
        <div className="app-shell-nav-list">
          {NAV_ITEMS.map((item) => (
            <div
              key={item.key}
              className={`app-shell-nav-item${screen === item.key ? ' app-shell-nav-item-active' : ''}`}
              onClick={() => onNavigate(item.key)}
            >
              {item.label}
            </div>
          ))}
        </div>
        <div className="app-shell-nav-bottom">
          <div
            className={`app-shell-nav-item${screen === 'settings' ? ' app-shell-nav-item-active' : ''}`}
            onClick={() => onNavigate('settings')}
          >
            Settings
          </div>
          <div className="app-shell-user">
            <div className="app-shell-user-avatar">{initials || 'U'}</div>
            <div className="app-shell-user-info">
              <div className="app-shell-user-name" title={user?.name}>{user?.name}</div>
              <div className="app-shell-user-role">{user?.role}</div>
            </div>
          </div>
          <div className="app-shell-signout" onClick={onSignOut}>Sign out</div>
        </div>
      </nav>

      <div className="app-shell-body">
        <div className="app-shell-content">{children}</div>
      </div>
    </div>
  )
}
