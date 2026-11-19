import Landing from './Landing'
import Dashboard from './Dashboard'
import Conductor from './Conductor'
import ConductorAccounts from './ConductorAccounts'
import { useState } from 'react'
import { useEffect } from 'react'
import type { FormEvent, ReactNode } from 'react'
import './App.css'

const API = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? window.location.origin : 'http://localhost:8000')

export default function App() {
  if (window.location.pathname === '/') return <Landing />
  if (window.location.pathname === '/dashboard') return <Protected role="owner"><Dashboard /></Protected>
  if (window.location.pathname === '/conductor') return <Protected role="conductor"><Conductor /></Protected>
  if (window.location.pathname === '/conductors') return <Protected role="owner"><ConductorAccounts /></Protected>
  return <AccessPage />
}

function Protected({ role, children }: { role: 'owner' | 'conductor'; children: ReactNode }) {
  const [state, setState] = useState<'loading' | 'allowed' | 'denied'>('loading')
  useEffect(() => {
    fetch(`${API}/auth/me`, { credentials: 'include' }).then(async (response) => {
      if (!response.ok) { setState('denied'); return }
      const payload = await response.json()
      if (payload.user?.role !== role) { setState('denied'); return }
      setState('allowed')
    }).catch(() => setState('denied'))
  }, [role])
  useEffect(() => { if (state === 'denied') window.location.href = '/login' }, [state])
  if (state !== 'allowed') return <main className="auth-loading"><span className="status-dot" /> Checking your access…</main>
  return <>{children}</>
}

function AccessPage() {
  const registering = window.location.pathname === '/register'
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const fields = new FormData(event.currentTarget)

    if (registering && fields.get('password') !== fields.get('confirmPassword')) {
      setError('The passwords do not match.')
      return
    }

    setBusy(true)
    try {
      const response = await fetch(`${API}/auth/${registering ? 'register' : 'login'}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name: fields.get('name'), email: fields.get('email'), password: fields.get('password') }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? 'We could not complete that request.')
      window.location.href = payload.user?.role === 'conductor' ? '/conductor' : '/dashboard'
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : 'We could not complete that request.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="access">
      <section className="brand-panel" aria-label="About PSV-Radar">
        <a className="brand" href="/login">PSV<span>Radar</span></a>
        <div className="radar" aria-hidden="true"><i /><i /><i /></div>
        <div className="brand-copy">
          <h2>See what happens on every run.</h2>
          <p>Track passenger activity and compare expected fares with declared collections across your PSV operations.</p>
        </div>
      </section>

      <section className="form-panel" aria-labelledby="access-title">
        <div className="form-card">
          <h1 id="access-title">{registering ? 'Create your account' : 'Sign in to PSV-Radar'}</h1>
          <p>{registering ? 'Set up access to the operations dashboard.' : 'Access your vehicle and revenue reports.'}</p>

          <form onSubmit={handleSubmit} onInput={() => setError('')}>
            {registering && (
              <label>Full name
                <input name="name" autoComplete="name" required />
              </label>
            )}

            <label>Email address
              <input name="email" type="email" autoComplete="email" required />
            </label>

            <label htmlFor="password">Password</label>
            <div className="password-row">
              <input
                id="password"
                name="password"
                type={showPassword ? 'text' : 'password'}
                autoComplete={registering ? 'new-password' : 'current-password'}
                required
              />
              <button
                type="button"
                className="visibility"
                aria-controls="password"
                onClick={() => setShowPassword(!showPassword)}
              >
                {showPassword ? 'Hide password' : 'Show password'}
              </button>
            </div>

            {registering && (
              <label>Confirm password
                <input name="confirmPassword" type="password" autoComplete="new-password" required />
              </label>
            )}

            {error && <p className="feedback" role="alert">{error}</p>}
            <button className="primary" type="submit" disabled={busy}>
              {busy ? 'Please wait…' : registering ? 'Create account' : 'Sign in'}
            </button>
          </form>

          <p className="switch-link">
            {registering ? 'Already have an account? ' : 'New to PSV-Radar? '}
            <a href={registering ? '/login' : '/register'}>
              {registering ? 'Sign in' : 'Create an account'}
            </a>
          </p>
        </div>
      </section>
    </main>
  )
}
