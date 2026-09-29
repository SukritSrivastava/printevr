// Staff passcode for invoicing (BRD-cart-invoice FR-P8). Asked the first time someone prints
// or opens Invoices; the token lives in sessionStorage. Any 401 asks again and retries once.
import { createContext, useCallback, useContext, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import { setStaffToken, staffLogin, staffToken } from '../api/invoices'
import { Dialog } from './Dialog'

export class StaffCancelled extends Error {
  constructor() {
    super('Staff sign-in cancelled')
  }
}

type WithStaff = <T>(fn: () => Promise<T>) => Promise<T>

const StaffContext = createContext<WithStaff | null>(null)

export function StaffProvider({ children }: { children: React.ReactNode }) {
  const [asking, setAsking] = useState(false)
  const waiting = useRef<{ resolve: () => void; reject: (e: Error) => void }[]>([])

  const ask = useCallback(
    () =>
      new Promise<void>((resolve, reject) => {
        waiting.current.push({ resolve, reject })
        setAsking(true)
      }),
    [],
  )

  const finish = (ok: boolean) => {
    const pending = waiting.current
    waiting.current = []
    setAsking(false)
    pending.forEach((p) => (ok ? p.resolve() : p.reject(new StaffCancelled())))
  }

  const withStaff = useCallback<WithStaff>(
    async (fn) => {
      if (!staffToken()) await ask()
      try {
        return await fn()
      } catch (err) {
        if (err instanceof ApiError && err.code === 'AUTH_REQUIRED') {
          setStaffToken(null)
          await ask()
          return fn()
        }
        throw err
      }
    },
    [ask],
  )

  return (
    <StaffContext.Provider value={withStaff}>
      {children}
      {asking && <StaffLoginDialog onDone={() => finish(true)} onCancel={() => finish(false)} />}
    </StaffContext.Provider>
  )
}

export function useStaff(): WithStaff {
  const ctx = useContext(StaffContext)
  if (!ctx) throw new Error('useStaff outside StaffProvider')
  return ctx
}

function StaffLoginDialog({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [passcode, setPasscode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!passcode) return setError('Enter the staff passcode')
    setBusy(true)
    setError(null)
    try {
      await staffLogin(passcode)
      onDone()
    } catch (err) {
      setPasscode('')
      if (err instanceof ApiError && err.code === 'INVOICING_DISABLED') setError("Invoicing isn't set up on this server.")
      else setError(err instanceof ApiError ? err.message : "Can't reach the server. Check your connection and try again.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title="Staff passcode" onClose={onCancel}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <p className="text-ink-soft">Invoices hold customer details, so they need the staff passcode.</p>
        <label htmlFor="staff-passcode" className="text-sm font-semibold text-ink-soft">
          Passcode
        </label>
        <input
          id="staff-passcode"
          type="password"
          className="field"
          autoComplete="current-password"
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? 'staff-passcode-error' : undefined}
        />
        {error && (
          <p id="staff-passcode-error" role="alert" className="text-sm text-stop">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy} className="mt-2 rounded-md bg-ink px-4 py-2.5 font-semibold text-stock disabled:opacity-60">
          {busy ? 'Checking…' : 'Continue'}
        </button>
      </form>
    </Dialog>
  )
}
