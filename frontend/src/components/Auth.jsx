import { useState } from 'react'
import { DharaLogo, TriBar } from './AppShell'

// Login / signup split-pane. No backend auth exists (or is being added) —
// submitting just navigates into the app, matching the mockup's mock flow.
export default function Auth({ screen, onSubmit, onToggle }) {
  const isSignup = screen === 'signup'
  const [form, setForm] = useState({ name: '', email: '', password: '' })

  const set = (key) => (e) => setForm((prev) => ({ ...prev, [key]: e.target.value }))

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
            <div className="auth-field">
              <label className="auth-label">Email</label>
              <input className="auth-input" type="email" value={form.email} onChange={set('email')} placeholder="name@gov.in" />
            </div>
            <div className="auth-field">
              <label className="auth-label">Password</label>
              <input className="auth-input" type="password" value={form.password} onChange={set('password')} placeholder="••••••••" />
            </div>
          </div>

          <button className="auth-cta" onClick={() => onSubmit(form)}>
            {isSignup ? 'Create account' : 'Sign in'}
          </button>

          <div className="auth-switch">
            <span>{isSignup ? 'Already have an account?' : 'No account yet?'}</span>
            <span className="auth-switch-cta" onClick={onToggle}>{isSignup ? 'Sign in' : 'Sign up'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
