'use client'

import { useState } from 'react'
import { DharaLogo, TriBar } from './AppShell'
import { isValidOrgEmail, login, signup } from '../lib/auth'

const inputClass =
  'h-11 rounded-xl border border-line bg-cream/40 px-3.5 font-body text-[15px] text-ink transition-all duration-150 outline-none focus:border-teal focus:bg-surface focus:shadow-focus-ring'

const HEADLINE = 'Data harnessed for AI-ready advancements'
const SUBTEXT = 'Inventory, metadata, harmonisation, cataloguing and API enablement — dataset by dataset.'

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
    <div className="flex h-screen w-full">
      <div className="selection-invert relative flex w-[420px] flex-none flex-col justify-between overflow-hidden bg-teal-deep p-11 px-10">
        <div
          className="pointer-events-none absolute inset-0"
          style={{ background: 'radial-gradient(120% 90% at 0% 0%, rgba(23,107,107,0.45) 0%, rgba(18,64,62,0) 60%)' }}
          aria-hidden
        />
        <div className="relative z-10 self-start">
          <DharaLogo variant="light" />
        </div>
        <div className="relative z-10 flex animate-fade-up flex-col gap-[18px]">
          <TriBar className="overflow-hidden rounded-full" />
          <div className="text-pretty font-display text-[26px] font-medium leading-[1.2] text-cream">{HEADLINE}</div>
          <div className="text-[15px] leading-relaxed text-[#a8bdb3]">{SUBTEXT}</div>
        </div>
        <div className="relative z-10 text-xs text-[#7d9891]">EkStep Foundation · data.dhara@ekstep.org</div>
      </div>

      <div className="flex flex-1 items-center justify-center bg-outer-bg">
        <div className="flex w-[400px] animate-fade-up flex-col gap-6 rounded-2xl border border-line/90 bg-surface p-8">
          <div className="flex flex-col gap-1.5">
            <div className="font-display text-[24px] font-medium tracking-tight text-ink">{isSignup ? 'Create an account' : 'Sign in'}</div>
            <div className="text-[14.5px] leading-relaxed text-ink-soft">
              {isSignup ? 'Departmental access to the DHARA toolkit.' : 'Use your departmental email address.'}
            </div>
          </div>

          <div className="flex flex-col gap-4">
            {isSignup && (
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-semibold text-ink">Full name</label>
                <input className={inputClass} type="text" value={form.name} onChange={set('name')} placeholder="Your name" />
              </div>
            )}
            {isSignup && (
              <div className="flex flex-col gap-1.5">
                <label className="text-[13px] font-semibold text-ink">Department (optional)</label>
                <input className={inputClass} type="text" value={form.dept} onChange={set('dept')} placeholder="e.g. Directorate of Economics and Statistics" />
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-semibold text-ink">Email</label>
              <input
                className={inputClass}
                type="email"
                value={form.email}
                onChange={set('email')}
                onKeyDown={onKeyDown}
                placeholder="name@organization.domain"
                autoComplete="username"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[13px] font-semibold text-ink">Password</label>
              <input
                className={inputClass}
                type="password"
                value={form.password}
                onChange={set('password')}
                onKeyDown={onKeyDown}
                placeholder="••••••••"
                autoComplete={isSignup ? 'new-password' : 'current-password'}
              />
            </div>
          </div>

          {error && <div className="rounded-xl border border-coral/25 bg-[#FDF6F5] px-3.5 py-2.5 text-sm text-[#b3423a]">{error}</div>}

          <button
            className="flex h-11 items-center justify-center rounded-xl bg-teal text-[14.5px] font-semibold tracking-tight text-white transition-colors duration-150 hover:bg-teal-dark active:scale-[0.985] disabled:cursor-default disabled:opacity-60 disabled:active:scale-100"
            onClick={submit}
            disabled={busy}
          >
            {busy ? (isSignup ? 'Creating account…' : 'Signing in…') : isSignup ? 'Create account' : 'Sign in'}
          </button>

          <div className="flex items-center justify-center gap-2 text-[14.5px] text-ink-soft">
            <span>{isSignup ? 'Already have an account?' : 'No account yet?'}</span>
            <span className="cursor-pointer font-semibold text-teal transition-colors hover:text-teal-dark" onClick={toggle}>{isSignup ? 'Sign in' : 'Sign up'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
