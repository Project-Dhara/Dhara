import { useState } from 'react'
import { DharaLogo, TriBar } from './AppShell'
import { isValidOrgEmail, login, signup } from '../auth'

// Login / signup split-pane. Signup is a dev convenience (backend
// ENABLE_SIGNUP) — accounts can also be admin-provisioned via
// backend/create_user.py once this stops being a dev deployment.
export default function Auth({ onSuccess }) {
  const [screen, setScreen] = useState('login') // 'login' | 'signup'
  const isSignup = screen === 'signup'
  const [form, setForm] = useState({ name: '', dept: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))

  const toggle = () => {
    setError('')
    setScreen((s) => (s === 'signup' ? 'login' : 'signup'))
  }

  const submit = async () => {
    setError('')
    const email = form.email.trim().toLowerCase()
    if (!isValidOrgEmail(email)) {
      setError('Enter a valid email in name@organization.domain format')
      return
    }
    if (isSignup && form.password.length < 8) {
      setError('Password must be at least 8 characters')
      return
    }
    if (!isSignup && !form.password) {
      setError('Enter your password')
      return
    }
    setBusy(true)
    try {
      const data = isSignup
        ? await signup(email, form.password, form.name.trim(), form.dept.trim())
        : await login(email, form.password)
      onSuccess(data)
    } catch (e) {
      setError(e.message || 'Something went wrong')
    } finally {
      setBusy(false)
    }
  }

  const onKeyDown = (e) => {
    if (e.key === 'Enter') submit()
  }

  return (
    <div className="auth-screen">
      <div className="auth-side">
        <div className="auth-side-logo">
          <DharaLogo />
        </div>
        <div className="auth-side-mid">
          <TriBar />
          <div className="auth-side-tagline">Data harnessed for AI-ready advancements</div>
          <div className="auth-side-sub">
            Inventory, metadata, harmonisation, cataloguing and API enablement — dataset by dataset.
          </div>
        </div>
        <div className="auth-side-footer">EkStep Foundation · data.dhara@ekstep.org</div>
      </div>

      <div className="auth-form-pane">
        <div className="auth-form">
          <div className="auth-form-head">
            <div className="auth-title">{isSignup ? 'Create an account' : 'Sign in'}</div>
            <div className="auth-sub">
              {isSignup ? 'Departmental access to the DHARA toolkit.' : 'Use your departmental email address.'}
            </div>
          </div>

          <div className="auth-fields">
            {isSignup && (
              <div className="auth-field">
                <label className="auth-label">Full name</label>
                <input className="auth-input" type="text" value={form.name} onChange={set('name')} placeholder="Your name" />
              </div>
            )}
            {isSignup && (
              <div className="auth-field">
                <label className="auth-label">Department (optional)</label>
                <input className="auth-input" type="text" value={form.dept} onChange={set('dept')} placeholder="e.g. Directorate of Economics and Statistics" />
              </div>
            )}
            <div className="auth-field">
              <label className="auth-label">Email</label>
              <input
                className="auth-input"
                type="email"
                value={form.email}
                onChange={set('email')}
                onKeyDown={onKeyDown}
                placeholder="name@organization.domain"
                autoComplete="username"
              />
            </div>
            <div className="auth-field">
              <label className="auth-label">Password</label>
              <input
                className="auth-input"
                type="password"
                value={form.password}
                onChange={set('password')}
                onKeyDown={onKeyDown}
                placeholder="••••••••"
                autoComplete={isSignup ? 'new-password' : 'current-password'}
              />
            </div>
          </div>

          {error && <div className="auth-error">{error}</div>}

          <button className="auth-cta" onClick={submit} disabled={busy}>
            {busy ? (isSignup ? 'Creating account…' : 'Signing in…') : isSignup ? 'Create account' : 'Sign in'}
          </button>

          <div className="auth-switch">
            <span>{isSignup ? 'Already have an account?' : 'No account yet?'}</span>
            <span className="auth-switch-cta" onClick={toggle}>{isSignup ? 'Sign in' : 'Sign up'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
