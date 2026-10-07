// Attendance tab. Day view: every employee with today's check-in and check-out; each person
// taps Check in when they arrive and Check out when they leave (the server records the time).
// Month view: days present, hours worked and missed check-outs per employee, with a CSV for
// payroll. An admin (TeamAdmin.tsx) can set or correct any day's times and delete a record.
// Everything is saved on the server, so every signed-in device sees the same register.
import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '../../api/client'
import {
  checkIn,
  checkOut,
  deleteRecord,
  fetchDay,
  fetchMonth,
  setRecord,
  type AttendanceRecord,
  type MonthSummary,
  type RegisterRow,
  type Role,
} from '../../api/team'
import {
  STATUS_TEXT,
  dayLabel,
  dayStatus,
  daysBetween,
  duration,
  istClock,
  istHHMM,
  monthCsv,
  monthLabel,
  monthOf,
  shiftDay,
  shiftMonth,
  type DayStatus,
} from '../../lib/attendance'
import { REFRESH_MS } from '../../lib/designers'
import { saveBlob } from '../../lib/download'
import { EMPLOYEES, useAppNav } from '../../nav'
import { Dialog } from '../Dialog'
import { StaffCancelled, useStaff } from '../StaffLoginDialog'
import { useToast } from '../Toast'
import { AdminToggle, TEAM, describeTeamError, isCancel, useTeamAdmin } from './TeamAdmin'

const stopsPolling = (err: unknown) =>
  err instanceof StaffCancelled ||
  (err instanceof ApiError && ['AUTH_REQUIRED', 'STORAGE_DISABLED', 'TEAM_NOT_SET_UP'].includes(err.code))

const CHIP: Record<DayStatus, string> = {
  in: 'bg-save-wash text-save',
  out: 'bg-cyan-wash text-cyan-deep',
  missing_out: 'bg-warn-wash text-warn',
  absent: 'bg-sheet text-ink-soft',
  not_in: 'bg-sheet text-ink-soft',
}

export function AttendancePage() {
  const { go } = useAppNav()
  const [view, setView] = useState<'day' | 'month'>('day')
  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="type-expanded text-2xl font-bold">Attendance</h1>
          <p className="mt-1 text-ink-soft">Check in when you arrive and check out when you leave. Times are IST.</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" className="rounded-md px-3 py-1.5 text-sm font-semibold ring-1 ring-rule" onClick={() => go(EMPLOYEES)}>
            Employees
          </button>
          <AdminToggle />
        </div>
      </div>
      <div role="tablist" aria-label="Attendance view" className="flex w-fit rounded-md bg-stock p-1 ring-1 ring-rule">
        {(['day', 'month'] as const).map((v) => (
          <button
            key={v}
            type="button"
            role="tab"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={`rounded px-4 py-1.5 text-sm font-semibold ${view === v ? 'bg-ink text-stock' : 'text-ink-soft hover:text-ink'}`}
          >
            {v === 'day' ? 'Day' : 'Month'}
          </button>
        ))}
      </div>
      {view === 'day' ? <DayView /> : <MonthView />}
    </main>
  )
}

function useLive<T>(key: unknown[], fn: () => Promise<T>, enabled = true) {
  const withStaff = useStaff()
  return useQuery({
    queryKey: [TEAM, ...key],
    queryFn: () => withStaff(fn),
    enabled,
    placeholderData: keepPreviousData,
    refetchInterval: (query) => (stopsPolling(query.state.error) ? false : REFRESH_MS),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: 'always',
    retry: (count, err) => !stopsPolling(err) && !(err instanceof ApiError) && count < 2,
    staleTime: 0,
  })
}

function Problem({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div role="alert" className="flex flex-wrap items-center gap-3 text-stop">
      <span>{describeTeamError(error)}</span>
      <button type="button" className="rounded-md bg-ink px-3 py-1 text-sm font-semibold text-stock" onClick={onRetry}>
        Retry
      </button>
    </div>
  )
}

// ---------------------------------------------------------------- day

function DayView() {
  const [date, setDate] = useState<string | null>(null) // null = today, as the server sees it
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<RegisterRow | null>(null)
  const { isAdmin, roleLabel } = useTeamAdmin()
  const day = useLive(['day', date], () => fetchDay(date))
  const data = day.data
  const shownDate = date ?? data?.today ?? null
  const isToday = !!data && shownDate === data.today
  const rows = (data?.rows ?? []).filter((r) => r.employee.name.toLowerCase().includes(search.trim().toLowerCase()))

  return (
    <section className="flex flex-col gap-4" aria-label="Day register">
      <div className="flex flex-wrap items-end gap-3 rounded-md bg-stock p-3 ring-1 ring-rule">
        <div className="flex items-end gap-1">
          <button
            type="button"
            className="min-h-11 rounded-md px-3 font-semibold ring-1 ring-rule disabled:opacity-40"
            aria-label="Previous day"
            disabled={!shownDate}
            onClick={() => shownDate && setDate(shiftDay(shownDate, -1))}
          >
            ‹
          </button>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-semibold text-ink-soft">Date</span>
            <input
              type="date"
              className="field"
              value={shownDate ?? ''}
              max={data?.today}
              onChange={(e) => e.target.value && setDate(e.target.value === data?.today ? null : e.target.value)}
            />
          </label>
          <button
            type="button"
            className="min-h-11 rounded-md px-3 font-semibold ring-1 ring-rule disabled:opacity-40"
            aria-label="Next day"
            disabled={!shownDate || isToday}
            onClick={() => shownDate && setDate(shiftDay(shownDate, 1) === data?.today ? null : shiftDay(shownDate, 1))}
          >
            ›
          </button>
          {!isToday && data && (
            <button type="button" className="ml-1 min-h-11 rounded-md px-3 text-sm font-semibold text-cyan-deep" onClick={() => setDate(null)}>
              Today
            </button>
          )}
        </div>
        <label className="flex min-w-48 flex-1 flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Find</span>
          <input className="field" placeholder="Employee name" value={search} onChange={(e) => setSearch(e.target.value)} />
        </label>
      </div>

      {day.isError ? (
        <Problem error={day.error} onRetry={() => day.refetch()} />
      ) : !data ? (
        <p className="text-ink-soft">Loading the register…</p>
      ) : (
        <>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-lg font-bold">
              {dayLabel(data.date)}
              {isToday && <span className="ml-2 text-sm font-semibold text-cyan-deep">Today</span>}
            </h2>
            <p className="text-sm text-ink-soft" data-testid="attendance-counts">
              {data.counts.present} of {data.counts.employees} present
              {isToday ? ` · ${data.counts.checked_in_now} checked in now` : ''}
            </p>
          </div>
          {data.rows.length === 0 ? (
            <p className="rounded-md bg-stock p-4 text-ink-soft ring-1 ring-rule">
              No employees yet. Add the team on the Employees page first.
            </p>
          ) : (
            <ul className="flex flex-col gap-2">
              {rows.map((row) => (
                <RegisterLine
                  key={row.employee.id}
                  row={row}
                  isToday={isToday}
                  roleLabel={roleLabel(row.employee.role)}
                  canEdit={isAdmin}
                  onEdit={() => setEditing(row)}
                />
              ))}
            </ul>
          )}
        </>
      )}
      {editing && data && <RecordDialog row={editing} date={data.date} onClose={() => setEditing(null)} />}
    </section>
  )
}

function RegisterLine({
  row,
  isToday,
  roleLabel,
  canEdit,
  onEdit,
}: {
  row: RegisterRow
  isToday: boolean
  roleLabel: string
  canEdit: boolean
  onEdit: () => void
}) {
  const withStaff = useStaff()
  const qc = useQueryClient()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const { employee, record } = row
  const status = dayStatus(record, isToday)

  const act = async (kind: 'in' | 'out') => {
    setBusy(true)
    try {
      const r = await withStaff(() => (kind === 'in' ? checkIn(employee.id) : checkOut(employee.id)))
      const at = kind === 'in' ? r.record?.check_in : r.record?.check_out
      toast(`${employee.name} checked ${kind} at ${at ? istClock(at) : 'now'}`)
    } catch (err) {
      if (!isCancel(err)) toast(describeTeamError(err))
    } finally {
      setBusy(false)
      await qc.invalidateQueries({ queryKey: [TEAM] })
    }
  }

  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-md bg-stock px-4 py-3 ring-1 ring-rule">
      <div className="flex min-w-40 flex-1 flex-col">
        <span className="font-semibold">
          {employee.name}
          {!employee.active && <span className="ml-2 text-xs font-semibold text-ink-soft">(removed)</span>}
        </span>
        <span className="text-sm text-ink-soft">{roleLabel}</span>
      </div>
      <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${CHIP[status]}`}>{STATUS_TEXT[status]}</span>
      <dl className="grid grid-cols-3 gap-x-4 text-sm sm:w-72">
        <div>
          <dt className="text-ink-soft">In</dt>
          <dd className="font-semibold tabular-nums">{record ? istClock(record.check_in) : '–'}</dd>
        </div>
        <div>
          <dt className="text-ink-soft">Out</dt>
          <dd className="font-semibold tabular-nums">{record?.check_out ? istClock(record.check_out) : '–'}</dd>
        </div>
        <div>
          <dt className="text-ink-soft">Worked</dt>
          <dd className="font-semibold tabular-nums">{record?.minutes != null ? duration(record.minutes) : '–'}</dd>
        </div>
      </dl>
      <div className="flex gap-2">
        {isToday && employee.active && status === 'not_in' && (
          <button
            type="button"
            disabled={busy}
            onClick={() => act('in')}
            className="min-h-11 rounded-md bg-save px-4 font-semibold text-stock disabled:opacity-60"
            aria-label={`Check in ${employee.name}`}
          >
            Check in
          </button>
        )}
        {isToday && status === 'in' && (
          <button
            type="button"
            disabled={busy}
            onClick={() => act('out')}
            className="min-h-11 rounded-md bg-ink px-4 font-semibold text-stock disabled:opacity-60"
            aria-label={`Check out ${employee.name}`}
          >
            Check out
          </button>
        )}
        {canEdit && (
          <button
            type="button"
            onClick={onEdit}
            className="min-h-11 rounded-md px-3 text-sm font-semibold ring-1 ring-rule"
            aria-label={`Edit ${employee.name}'s attendance`}
          >
            Edit
          </button>
        )}
      </div>
      {(record?.note || record?.edited_by_admin) && (
        <p className="w-full text-sm text-ink-soft">
          {record.note}
          {record.note && record.edited_by_admin ? ' · ' : ''}
          {record.edited_by_admin && <span className="italic">Times set by admin</span>}
        </p>
      )}
    </li>
  )
}

function RecordDialog({ row, date, onClose }: { row: RegisterRow; date: string; onClose: () => void }) {
  const { withAdmin } = useTeamAdmin()
  const qc = useQueryClient()
  const toast = useToast()
  const rec = row.record
  const [inAt, setInAt] = useState(rec ? istHHMM(rec.check_in) : '09:00')
  const [outAt, setOutAt] = useState(rec?.check_out ? istHHMM(rec.check_out) : '')
  const [note, setNote] = useState(rec?.note ?? '')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true)
    setError(null)
    try {
      await withAdmin(fn)
      toast(done)
      await qc.invalidateQueries({ queryKey: [TEAM] })
      onClose()
    } catch (err) {
      if (!isCancel(err)) setError(describeTeamError(err))
    } finally {
      setBusy(false)
    }
  }

  const save = (e: React.FormEvent) => {
    e.preventDefault()
    if (!inAt) return setError('Enter the check-in time')
    if (outAt && outAt <= inAt) return setError('Check-out must be after check-in')
    run(
      () => setRecord(row.employee.id, date, { check_in: inAt, check_out: outAt || null, note: note.trim() || null }),
      `${row.employee.name}'s attendance saved`,
    )
  }

  return (
    <Dialog title={`${row.employee.name} · ${dayLabel(date)}`} onClose={onClose}>
      <form onSubmit={save} className="flex flex-col gap-3">
        <div className="grid grid-cols-2 gap-3">
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-semibold text-ink-soft">Check-in (IST)</span>
            <input type="time" className="field" value={inAt} onChange={(e) => setInAt(e.target.value)} required />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-semibold text-ink-soft">Check-out (IST)</span>
            <input type="time" className="field" value={outAt} onChange={(e) => setOutAt(e.target.value)} />
          </label>
        </div>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Note (optional)</span>
          <input className="field" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Forgot to check out" />
        </label>
        <p className="text-sm text-ink-soft">Leave check-out empty if they're still at work.</p>
        {error && (
          <p role="alert" className="text-sm text-stop">
            {error}
          </p>
        )}
        <div className="mt-2 flex flex-wrap justify-between gap-2">
          {rec ? (
            <button
              type="button"
              disabled={busy}
              className="rounded-md px-4 py-2 font-semibold text-stop ring-1 ring-rule disabled:opacity-60"
              onClick={() => run(() => deleteRecord(row.employee.id, date), `${row.employee.name}'s attendance deleted`)}
            >
              Delete record
            </button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <button type="button" className="rounded-md px-4 py-2 font-semibold ring-1 ring-rule" onClick={onClose} data-close>
              Cancel
            </button>
            <button type="submit" disabled={busy} className="rounded-md bg-ink px-4 py-2 font-semibold text-stock disabled:opacity-60">
              {busy ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </form>
    </Dialog>
  )
}

// ---------------------------------------------------------------- month

function MonthView() {
  const [month, setMonth] = useState<string | null>(null)
  const { roleLabel } = useTeamAdmin()
  const today = useLive(['day', null], () => fetchDay(null)).data?.today
  const current = month ?? (today ? monthOf(today) : null)
  const summary = useLive(['month', current], () => fetchMonth(current as string), current !== null)
  const data = current ? summary.data : undefined

  const download = () => {
    if (!data) return
    saveBlob(new Blob([monthCsv(data, roleLabel)], { type: 'text/csv;charset=utf-8' }), `Attendance_${data.month}.csv`)
  }

  return (
    <section className="flex flex-col gap-4" aria-label="Month summary">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-stock p-3 ring-1 ring-rule">
        <div className="flex items-center gap-1">
          <button
            type="button"
            className="min-h-11 rounded-md px-3 font-semibold ring-1 ring-rule disabled:opacity-40"
            aria-label="Previous month"
            disabled={!current}
            onClick={() => current && setMonth(shiftMonth(current, -1))}
          >
            ‹
          </button>
          <h2 className="min-w-44 text-center text-lg font-bold">{current ? monthLabel(current) : '…'}</h2>
          <button
            type="button"
            className="min-h-11 rounded-md px-3 font-semibold ring-1 ring-rule disabled:opacity-40"
            aria-label="Next month"
            disabled={!current || !today || current >= monthOf(today)}
            onClick={() => current && setMonth(shiftMonth(current, 1))}
          >
            ›
          </button>
        </div>
        <button
          type="button"
          className="rounded-md border-[1.5px] border-ink px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
          disabled={!data || data.rows.length === 0}
          onClick={download}
        >
          Download CSV
        </button>
      </div>
      {summary.isError && current ? (
        <Problem error={summary.error} onRetry={() => summary.refetch()} />
      ) : !data ? (
        <p className="text-ink-soft">Loading the month…</p>
      ) : data.rows.length === 0 ? (
        <p className="rounded-md bg-stock p-4 text-ink-soft ring-1 ring-rule">No employees yet.</p>
      ) : (
        <MonthTable data={data} roleLabel={roleLabel} />
      )}
    </section>
  )
}

function MonthTable({ data, roleLabel }: { data: MonthSummary; roleLabel: (r: Role) => string }) {
  const days = daysBetween(data.first, data.last)
  const cellClass = (rec: AttendanceRecord | undefined, d: string) => {
    if (d > data.today) return 'bg-transparent ring-1 ring-rule/50'
    if (!rec) return 'bg-sheet'
    if (!rec.check_out) return d === data.today ? 'bg-save' : 'bg-overpay'
    return 'bg-cyan'
  }
  const cellTitle = (rec: AttendanceRecord | undefined, d: string) =>
    `${dayLabel(d)}: ${
      rec ? `${istClock(rec.check_in)} – ${rec.check_out ? istClock(rec.check_out) : 'no check-out'}` : d > data.today ? '' : 'absent'
    }`

  return (
    <div className="flex flex-col gap-3">
      <div className="overflow-x-auto rounded-md bg-stock ring-1 ring-rule">
        <table className="w-full min-w-[40rem] text-sm">
          <thead>
            <tr className="border-b border-rule text-left text-ink-soft">
              <th scope="col" className="px-3 py-2 font-semibold">Employee</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Days</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Hours</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">Avg / day</th>
              <th scope="col" className="px-3 py-2 text-right font-semibold">No check-out</th>
              <th scope="col" className="px-3 py-2 font-semibold">Days of the month</th>
            </tr>
          </thead>
          <tbody>
            {data.rows.map((r) => {
              const complete = Object.values(r.days).filter((d) => d.minutes != null).length
              return (
                <tr key={r.employee.id} className="border-b border-rule last:border-0">
                  <th scope="row" className="px-3 py-2 text-left">
                    <span className="block font-semibold">
                      {r.employee.name}
                      {!r.employee.active && <span className="ml-1 text-xs text-ink-soft">(removed)</span>}
                    </span>
                    <span className="text-xs font-normal text-ink-soft">{roleLabel(r.employee.role)}</span>
                  </th>
                  <td className="px-3 py-2 text-right tabular-nums">{r.days_present}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{duration(r.minutes)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{complete ? duration(Math.round(r.minutes / complete)) : '–'}</td>
                  <td className={`px-3 py-2 text-right tabular-nums ${r.open_days ? 'font-semibold text-warn' : ''}`}>{r.open_days}</td>
                  <td className="px-3 py-2">
                    <div className="flex gap-0.5" aria-label={`${r.employee.name}: ${r.days_present} days present`}>
                      {days.map((d) => (
                        <span key={d} title={cellTitle(r.days[d], d)} className={`h-4 w-2.5 shrink-0 rounded-sm ${cellClass(r.days[d], d)}`} />
                      ))}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <ul className="flex flex-wrap gap-4 text-xs text-ink-soft" aria-label="Legend">
        <li className="flex items-center gap-1.5"><span className="h-3 w-2.5 rounded-sm bg-cyan" />Checked in and out</li>
        <li className="flex items-center gap-1.5"><span className="h-3 w-2.5 rounded-sm bg-save" />In now</li>
        <li className="flex items-center gap-1.5"><span className="h-3 w-2.5 rounded-sm bg-overpay" />No check-out</li>
        <li className="flex items-center gap-1.5"><span className="h-3 w-2.5 rounded-sm bg-sheet ring-1 ring-rule" />Absent</li>
      </ul>
    </div>
  )
}
