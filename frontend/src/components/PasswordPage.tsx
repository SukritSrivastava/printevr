import { useState } from 'react'
import { ApiError, login } from '../api/client'

interface Props {
  onUnlocked: () => void
}

export function PasswordPage({ onUnlocked }: Props) {
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!password) {
      setError('Enter the password')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await login(password)
      onUnlocked()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Can't reach the server. Check your connection and try again.")
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-dvh place-items-center bg-sheet px-4 py-10">
      <form onSubmit={submit} className="ticket w-full max-w-sm px-6 py-8 sm:px-8" aria-labelledby="password-title">
        {['tl', 'tr', 'bl', 'br'].map((c) => (
          <span key={c} className={`reg ${c}`} aria-hidden="true">
            <span />
          </span>
        ))}
        <h1 id="password-title" className="type-expanded text-xl font-extrabold tracking-tight">
          Printevr <span className="font-normal text-cyan">Quote Desk</span>
        </h1>
        <p className="mt-1 text-ink-soft">Enter the password to open the quote desk.</p>

        <div className="mt-6 flex flex-col gap-1.5">
          <label htmlFor="password" className="text-sm font-semibold text-ink-soft">
            Password
          </label>
          <input
            id="password"
            type="password"
            className="field"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={error ? 'true' : undefined}
            aria-describedby={error ? 'password-error' : undefined}
          />
          {error && (
            <p id="password-error" role="alert" className="text-sm text-stop">
              {error}
            </p>
          )}
        </div>

        <button
          type="submit"
          disabled={busy}
          className="mt-5 w-full rounded-md bg-ink px-4 py-2.5 font-semibold text-stock disabled:opacity-60"
        >
          {busy ? 'Checking…' : 'Open quote desk'}
        </button>
      </form>
    </main>
  )
}
