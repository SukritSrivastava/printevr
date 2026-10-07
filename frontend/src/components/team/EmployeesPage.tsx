// Employees tab: the current workforce. Everyone signed in as staff can see it; adding,
// editing, removing and restoring need the admin passcode (TeamAdmin.tsx). Removing keeps the
// person's attendance history, so they can be restored later.
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import {
  addEmployee,
  fetchEmployees,
  removeEmployee,
  restoreEmployee,
  updateEmployee,
  type Employee,
  type EmployeeInput,
  type Role,
} from '../../api/team'
import { useAppNav, ATTENDANCE } from '../../nav'
import { Dialog } from '../Dialog'
import { useStaff } from '../StaffLoginDialog'
import { useToast } from '../Toast'
import { AdminToggle, TEAM, describeTeamError, isCancel, useTeamAdmin } from './TeamAdmin'

const NAME_MAX = 80

export function EmployeesPage() {
  const withStaff = useStaff()
  const { go } = useAppNav()
  const { isAdmin, withAdmin, roleLabel, settings } = useTeamAdmin()
  const qc = useQueryClient()
  const toast = useToast()
  const [showRemoved, setShowRemoved] = useState(false)
  const [editing, setEditing] = useState<Employee | 'new' | null>(null)
  const [removing, setRemoving] = useState<Employee | null>(null)
  const [roleFilter, setRoleFilter] = useState<Role | ''>('')
  const [search, setSearch] = useState('')

  const list = useQuery({
    queryKey: [TEAM, 'employees', showRemoved],
    queryFn: () => withStaff(() => fetchEmployees(showRemoved)),
    placeholderData: keepPreviousData,
    retry: false,
  })
  const employees = list.data ?? []
  const shown = employees.filter(
    (e) => (!roleFilter || e.role === roleFilter) && e.name.toLowerCase().includes(search.trim().toLowerCase()),
  )
  const active = employees.filter((e) => e.active)
  const removed = employees.filter((e) => !e.active)

  const restore = async (e: Employee) => {
    try {
      await withAdmin(() => restoreEmployee(e.id))
      toast(`${e.name} is back on the team`)
      await qc.invalidateQueries({ queryKey: [TEAM] })
    } catch (err) {
      if (!isCancel(err)) toast(describeTeamError(err))
    }
  }

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="type-expanded text-2xl font-bold">Employees</h1>
          <p className="mt-1 text-ink-soft">The current workforce. Everyone here appears on the attendance register.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="rounded-md px-3 py-1.5 text-sm font-semibold ring-1 ring-rule" onClick={() => go(ATTENDANCE)}>
            Attendance
          </button>
          <AdminToggle />
          <button
            type="button"
            className="rounded-md bg-ink px-4 py-1.5 text-sm font-semibold text-stock disabled:opacity-50"
            disabled={settings ? !settings.admin_configured : false}
            onClick={() => withAdmin(async () => setEditing('new')).catch(() => {})}
          >
            + Add employee
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-end gap-3 rounded-md bg-stock p-3 ring-1 ring-rule">
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Search</span>
          <input className="field" placeholder="Name" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Role</span>
          <select className="field" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value as Role | '')}>
            <option value="">All roles</option>
            {settings?.roles.map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-h-11 items-center gap-2 text-sm font-semibold">
          <input type="checkbox" className="size-4 accent-cyan" checked={showRemoved} onChange={(e) => setShowRemoved(e.target.checked)} />
          Show removed
        </label>
      </div>

      {list.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-stop">
          <span>{describeTeamError(list.error)}</span>
          <button type="button" className="rounded-md bg-ink px-3 py-1 text-sm font-semibold text-stock" onClick={() => list.refetch()}>
            Retry
          </button>
        </div>
      ) : list.isPending ? (
        <p className="text-ink-soft">Loading employees…</p>
      ) : employees.length === 0 ? (
        <p className="rounded-md bg-stock p-4 text-ink-soft ring-1 ring-rule">
          No employees yet. {isAdmin ? 'Add the first one with “+ Add employee”.' : 'Unlock admin to add the first one.'}
        </p>
      ) : (
        <section aria-label="Employees" className="flex flex-col gap-2">
          <p className="text-sm text-ink-soft">
            {active.length} on the team{showRemoved && removed.length ? ` · ${removed.length} removed` : ''}
            {shown.length !== employees.length ? ` · showing ${shown.length}` : ''}
          </p>
          <ul className="flex flex-col gap-2">
            {shown.map((e) => (
              <li
                key={e.id}
                className={`flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md bg-stock px-4 py-3 ring-1 ring-rule ${e.active ? '' : 'opacity-70'}`}
              >
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{e.name}</span>
                    <span className="rounded-full bg-cyan-wash px-2 py-0.5 text-xs font-semibold text-cyan-deep">{roleLabel(e.role)}</span>
                    {!e.active && <span className="rounded-full bg-sheet px-2 py-0.5 text-xs font-semibold text-ink-soft">Removed</span>}
                  </span>
                  <span className="mt-0.5 text-sm text-ink-soft">
                    {[e.phone, e.email, e.joined_on && `Joined ${joined(e.joined_on)}`].filter(Boolean).join(' · ') || 'No contact details'}
                  </span>
                </div>
                {e.active ? (
                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="rounded-md px-3 py-1.5 text-sm font-semibold ring-1 ring-rule"
                      onClick={() => withAdmin(async () => setEditing(e)).catch(() => {})}
                      aria-label={`Edit ${e.name}`}
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      className="rounded-md px-3 py-1.5 text-sm font-semibold text-stop ring-1 ring-rule"
                      onClick={() => withAdmin(async () => setRemoving(e)).catch(() => {})}
                      aria-label={`Remove ${e.name}`}
                    >
                      Remove
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    className="rounded-md px-3 py-1.5 text-sm font-semibold ring-1 ring-rule"
                    onClick={() => restore(e)}
                    aria-label={`Restore ${e.name}`}
                  >
                    Restore
                  </button>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {editing && <EmployeeDialog employee={editing === 'new' ? null : editing} onClose={() => setEditing(null)} />}
      {removing && <RemoveDialog employee={removing} onClose={() => setRemoving(null)} />}
    </main>
  )
}

const joined = (ymd: string) =>
  new Date(`${ymd}T00:00:00Z`).toLocaleDateString('en-IN', { timeZone: 'UTC', day: 'numeric', month: 'short', year: 'numeric' })

function EmployeeDialog({ employee, onClose }: { employee: Employee | null; onClose: () => void }) {
  const { withAdmin, settings } = useTeamAdmin()
  const qc = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState<EmployeeInput>({
    name: employee?.name ?? '',
    role: employee?.role ?? 'staff',
    phone: employee?.phone ?? '',
    email: employee?.email ?? '',
    joined_on: employee?.joined_on ?? '',
  })
  const [error, setError] = useState<{ field: string | null; message: string } | null>(null)
  const [busy, setBusy] = useState(false)
  const set = (key: keyof EmployeeInput) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    setForm((f) => ({ ...f, [key]: e.target.value }))
    setError(null)
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim()) return setError({ field: 'name', message: 'Enter a name' })
    const body: EmployeeInput = {
      name: form.name.trim(),
      role: form.role,
      phone: form.phone?.trim() || null,
      email: form.email?.trim() || null,
      joined_on: form.joined_on || null,
    }
    setBusy(true)
    try {
      const saved = await withAdmin(() => (employee ? updateEmployee(employee.id, body) : addEmployee(body)))
      toast(employee ? `${saved.name} updated` : `${saved.name} added to the team`)
      await qc.invalidateQueries({ queryKey: [TEAM] })
      onClose()
    } catch (err) {
      if (isCancel(err)) return
      const field = (err as { details?: { field?: string } }).details?.field ?? null
      setError({ field, message: describeTeamError(err) })
    } finally {
      setBusy(false)
    }
  }

  const invalid = (field: string) => (error?.field === field ? 'true' : undefined)

  return (
    <Dialog title={employee ? `Edit ${employee.name}` : 'Add employee'} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-3" noValidate>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Name</span>
          <input className="field" maxLength={NAME_MAX} value={form.name} onChange={set('name')} aria-invalid={invalid('name')} autoComplete="off" />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Role</span>
          <select className="field" value={form.role} onChange={set('role')} aria-invalid={invalid('role')}>
            {(settings?.roles ?? []).map((r) => (
              <option key={r.value} value={r.value}>
                {r.label}
              </option>
            ))}
          </select>
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-semibold text-ink-soft">Phone (optional)</span>
            <input className="field" type="tel" inputMode="tel" maxLength={20} value={form.phone ?? ''} onChange={set('phone')} aria-invalid={invalid('phone')} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-semibold text-ink-soft">Joined on (optional)</span>
            <input className="field" type="date" value={form.joined_on ?? ''} onChange={set('joined_on')} aria-invalid={invalid('joined_on')} />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Email (optional)</span>
          <input className="field" type="email" maxLength={120} value={form.email ?? ''} onChange={set('email')} aria-invalid={invalid('email')} />
        </label>
        {error && (
          <p role="alert" className="text-sm text-stop">
            {error.message}
          </p>
        )}
        <div className="mt-2 flex justify-end gap-2">
          <button type="button" className="rounded-md px-4 py-2 font-semibold ring-1 ring-rule" onClick={onClose} data-close>
            Cancel
          </button>
          <button type="submit" disabled={busy} className="rounded-md bg-ink px-4 py-2 font-semibold text-stock disabled:opacity-60">
            {busy ? 'Saving…' : employee ? 'Save changes' : 'Add employee'}
          </button>
        </div>
      </form>
    </Dialog>
  )
}

function RemoveDialog({ employee, onClose }: { employee: Employee; onClose: () => void }) {
  const { withAdmin } = useTeamAdmin()
  const qc = useQueryClient()
  const toast = useToast()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const confirm = async () => {
    setBusy(true)
    try {
      await withAdmin(() => removeEmployee(employee.id))
      toast(`${employee.name} removed from the team`)
      await qc.invalidateQueries({ queryKey: [TEAM] })
      onClose()
    } catch (err) {
      if (!isCancel(err)) setError(describeTeamError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog title={`Remove ${employee.name}?`} onClose={onClose}>
      <p className="text-ink-soft">
        {employee.name} leaves the attendance register. Their past attendance is kept, and you can restore them later from
        “Show removed”.
      </p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-stop">
          {error}
        </p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className="rounded-md px-4 py-2 font-semibold ring-1 ring-rule" onClick={onClose} data-close>
          Cancel
        </button>
        <button type="button" disabled={busy} className="rounded-md bg-stop px-4 py-2 font-semibold text-stock disabled:opacity-60" onClick={confirm}>
          {busy ? 'Removing…' : 'Remove'}
        </button>
      </div>
    </Dialog>
  )
}
