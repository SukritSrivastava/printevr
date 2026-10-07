// Admin passcode for the Team tab, a stand-in until role-based login: asked the first time
// someone changes an employee or corrects attendance; the token lives in sessionStorage. A
// rejected token (ADMIN_REQUIRED) asks again and retries once, like the staff passcode.
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { adminLogin, adminToken, fetchTeamSettings, setAdminToken, type Role, type TeamSettings } from '../../api/team'
import { Dialog } from '../Dialog'
import { StaffCancelled, useStaff } from '../StaffLoginDialog'

export class AdminCancelled extends Error {
  constructor() {
    super('Admin sign-in cancelled')
  }
}

/** Every Team query starts with this, so one invalidate refreshes them all. */
export const TEAM = 'team'

interface TeamAdmin {
  settings: TeamSettings | undefined
  settingsError: unknown
  isAdmin: boolean
  /** Runs `fn` with the staff and admin tokens, asking for either when missing. */
  withAdmin: <T>(fn: () => Promise<T>) => Promise<T>
  unlock: () => Promise<void>
  lock: () => void
  roleLabel: (role: Role) => string
}

const Context = createContext<TeamAdmin | null>(null)

export function TeamAdminProvider({ children }: { children: React.ReactNode }) {
  const withStaff = useStaff()
  const qc = useQueryClient()
  const [asking, setAsking] = useState(false)
  const [hasToken, setHasToken] = useState(() => adminToken() !== null)
  const waiting = useRef<{ resolve: () => void; reject: (e: Error) => void }[]>([])

  const settingsQuery = useQuery({
    queryKey: [TEAM, 'settings', hasToken],
    queryFn: () => withStaff(fetchTeamSettings),
    staleTime: 60_000,
    retry: (count, err) => !(err instanceof StaffCancelled) && !(err instanceof ApiError) && count < 2,
  })
  const settings = settingsQuery.data

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
    if (ok) setHasToken(true)
    pending.forEach((p) => (ok ? p.resolve() : p.reject(new AdminCancelled())))
  }

  const withAdmin = useCallback(
    <T,>(fn: () => Promise<T>): Promise<T> =>
      withStaff(async () => {
        if (!adminToken()) await ask()
        try {
          return await fn()
        } catch (err) {
          if (err instanceof ApiError && err.code === 'ADMIN_REQUIRED') {
            setAdminToken(null)
            setHasToken(false)
            await ask()
            return fn()
          }
          throw err
        }
      }),
    [ask, withStaff],
  )

  const unlock = useCallback(() => withAdmin(async () => undefined), [withAdmin])

  const lock = useCallback(() => {
    setAdminToken(null)
    setHasToken(false)
    qc.invalidateQueries({ queryKey: [TEAM, 'settings'] })
  }, [qc])

  const roleLabel = useCallback(
    (role: Role) => settings?.roles.find((r) => r.value === role)?.label ?? role,
    [settings],
  )

  const value: TeamAdmin = {
    settings,
    settingsError: settingsQuery.error,
    // The server has the last word: a stale or wrong token shows as locked.
    isAdmin: hasToken && (settings?.is_admin ?? true),
    withAdmin,
    unlock,
    lock,
    roleLabel,
  }

  return (
    <Context.Provider value={value}>
      {children}
      {asking && <AdminLoginDialog onDone={() => finish(true)} onCancel={() => finish(false)} />}
    </Context.Provider>
  )
}

export function useTeamAdmin(): TeamAdmin {
  const ctx = useContext(Context)
  if (!ctx) throw new Error('useTeamAdmin outside TeamAdminProvider')
  return ctx
}

/** "Admin" button: unlocks admin changes, or shows that they're unlocked and offers to lock. */
export function AdminToggle() {
  const { isAdmin, unlock, lock, settings } = useTeamAdmin()
  if (settings && !settings.admin_configured) {
    return <span className="text-sm text-ink-soft">Admin changes are off on this server</span>
  }
  return isAdmin ? (
    <button
      type="button"
      onClick={lock}
      className="flex items-center gap-2 rounded-md bg-save-wash px-3 py-1.5 text-sm font-semibold text-save ring-1 ring-save/40"
      title="Admin changes are unlocked in this tab. Click to lock them again."
    >
      <span aria-hidden>●</span> Admin unlocked · Lock
    </button>
  ) : (
    <button
      type="button"
      onClick={() => unlock().catch(() => {})}
      className="rounded-md border-[1.5px] border-ink px-3 py-1.5 text-sm font-semibold"
    >
      Unlock admin
    </button>
  )
}

function AdminLoginDialog({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const [passcode, setPasscode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!passcode) return setError('Enter the admin passcode')
    setBusy(true)
    setError(null)
    try {
      await adminLogin(passcode)
      onDone()
    } catch (err) {
      setPasscode('')
      setError(err instanceof ApiError ? err.message : "Can't reach the server. Check your connection and try again.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title="Admin passcode" onClose={onCancel}>
      <form onSubmit={submit} className="flex flex-col gap-3">
        <p className="text-ink-soft">Adding, editing or removing employees and correcting attendance need the admin passcode.</p>
        <label htmlFor="team-admin-passcode" className="text-sm font-semibold text-ink-soft">
          Passcode
        </label>
        <input
          id="team-admin-passcode"
          type="password"
          className="field"
          autoComplete="current-password"
          value={passcode}
          onChange={(e) => setPasscode(e.target.value)}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby={error ? 'team-admin-passcode-error' : undefined}
        />
        {error && (
          <p id="team-admin-passcode-error" role="alert" className="text-sm text-stop">
            {error}
          </p>
        )}
        <button type="submit" disabled={busy} className="mt-2 rounded-md bg-ink px-4 py-2.5 font-semibold text-stock disabled:opacity-60">
          {busy ? 'Checking…' : 'Unlock'}
        </button>
      </form>
    </Dialog>
  )
}

/** A readable message for a Team error. */
export function describeTeamError(err: unknown): string {
  if (err instanceof StaffCancelled) return 'Enter the staff passcode to see the team.'
  if (err instanceof AdminCancelled) return 'Unlock admin to make this change.'
  if (err instanceof ApiError && err.code === 'TEAM_NOT_SET_UP')
    return "The team tables aren't in the database yet. Run the migrations (see README), then retry."
  if (err instanceof ApiError && err.code === 'STORAGE_DISABLED') return "This server doesn't store employees or attendance (no database)."
  if (err instanceof ApiError) return err.message
  return "Can't reach the server. Check your connection and try again."
}

export const isCancel = (err: unknown) => err instanceof StaffCancelled || err instanceof AdminCancelled
