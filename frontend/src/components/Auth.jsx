'use client'

import { useState } from 'react'
import { DharaLogo, TriBar } from './AppShell'
import { isValidOrgEmail, login, signup } from '../lib/auth'

const inputClass = 'h-11 rounded-md border border-[#ddd3c0] bg-white px-3.5 font-sans text-[15px] text-ink'

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
      <div className="flex w-[420px] flex-none flex-col justify-between bg-teal-deep p-11 px-10">
        <div className="self-start rounded-lg bg-white px-[18px] py-3.5">
          <DharaLogo />
        </div>
        <div className="flex flex-col gap-[18px]">
          <TriBar />
          <div className="text-pretty font-display text-[32px] font-medium leading-[1.15] text-cream">Data harnessed for AI-ready advancements</div>
          <div className="text-[15px] leading-relaxed text-[#a8bdb3]">
            Inventory, metadata, harmonisation, cataloguing and API enablement — dataset by dataset.
          </div>
        </div>
        <div className="text-xs text-[#7d9891]">EkStep Foundation · data.dhara@ekstep.org</div>
      </div>

      <div className="flex flex-1 items-center justify-center bg-cream">
        <div className="flex w-[400px] flex-col gap-6">
          <div className="flex flex-col gap-1.5">
            <div className="text-[28px] font-semibold tracking-tight text-ink">{isSignup ? 'Create an account' : 'Sign in'}</div>
            <div className="text-[15px] text-ink-soft">
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

          {error && <div className="text-sm text-[#b3423a]">{error}</div>}

          <button
            className="flex h-[46px] items-center justify-center rounded-md bg-teal text-[15px] font-semibold text-white transition-colors hover:bg-teal-dark disabled:cursor-default disabled:opacity-60"
            onClick={submit}
            disabled={busy}
          >
            {busy ? (isSignup ? 'Creating account…' : 'Signing in…') : isSignup ? 'Create account' : 'Sign in'}
          </button>

          <div className="flex items-center justify-center gap-2 text-[15px] text-ink-soft">
            <span>{isSignup ? 'Already have an account?' : 'No account yet?'}</span>
            <span className="cursor-pointer font-semibold text-teal" onClick={toggle}>{isSignup ? 'Sign in' : 'Sign up'}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
