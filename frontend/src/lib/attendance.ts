// Attendance display rules. Days and times are IST, like the rest of the app (lib/designers.ts).
import type { AttendanceRecord, MonthSummary, Role } from '../api/team'

const IST = 'Asia/Kolkata'

const clock = new Intl.DateTimeFormat('en-IN', { timeZone: IST, hour: 'numeric', minute: '2-digit', hour12: true })
const clock24 = new Intl.DateTimeFormat('en-GB', { timeZone: IST, hour: '2-digit', minute: '2-digit', hour12: false })

/** "9:05 AM" in IST. */
export function istClock(iso: string): string {
  const parts = Object.fromEntries(clock.formatToParts(new Date(iso)).map((p) => [p.type, p.value]))
  return `${parts.hour}:${parts.minute} ${String(parts.dayPeriod).toUpperCase()}`
}

/** "09:05" in IST, for a time input. */
export function istHHMM(iso: string): string {
  return clock24.format(new Date(iso)).replace(/^24:/, '00:')
}

/** "8h 15m", "45m", "0m". */
export function duration(minutes: number): string {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`
}

export type DayStatus = 'in' | 'out' | 'missing_out' | 'absent' | 'not_in'

/** Where someone stands on a day: checked in, checked out, forgot to check out, or no record. */
export function dayStatus(record: AttendanceRecord | null, isToday: boolean): DayStatus {
  if (!record) return isToday ? 'not_in' : 'absent'
  if (record.check_out) return 'out'
  return isToday ? 'in' : 'missing_out'
}

export const STATUS_TEXT: Record<DayStatus, string> = {
  in: 'Checked in',
  out: 'Checked out',
  missing_out: 'No check-out',
  absent: 'Absent',
  not_in: 'Not checked in',
}

const toDate = (ymd: string) => {
  const [y, m, d] = ymd.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d))
}
const ymd = (d: Date) => d.toISOString().slice(0, 10)

export const shiftDay = (day: string, by: number) => {
  const d = toDate(day)
  d.setUTCDate(d.getUTCDate() + by)
  return ymd(d)
}

export const monthOf = (day: string) => day.slice(0, 7)

export function shiftMonth(month: string, by: number): string {
  const [y, m] = month.split('-').map(Number)
  const d = new Date(Date.UTC(y, m - 1 + by, 1))
  return ymd(d).slice(0, 7)
}

/** "Thu, 8 Oct 2026" */
export const dayLabel = (day: string) =>
  toDate(day).toLocaleDateString('en-IN', { timeZone: 'UTC', weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' })

/** "October 2026" */
export const monthLabel = (month: string) =>
  toDate(`${month}-01`).toLocaleDateString('en-IN', { timeZone: 'UTC', month: 'long', year: 'numeric' })

/** Every YYYY-MM-DD from `first` to `last`. */
export function daysBetween(first: string, last: string): string[] {
  const out: string[] = []
  for (let d = first; d <= last; d = shiftDay(d, 1)) out.push(d)
  return out
}

const cell = (value: string | number) => {
  const text = String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

/** The month as a spreadsheet: one row per employee, one column per day ("09:00-18:00"). */
export function monthCsv(summary: MonthSummary, roleLabel: (r: Role) => string): string {
  const days = daysBetween(summary.first, summary.last)
  const header = ['Employee', 'Role', 'Days present', 'Hours worked', 'Missing check-outs', ...days]
  const rows = summary.rows.map((r) => [
    r.employee.name + (r.employee.active ? '' : ' (removed)'),
    roleLabel(r.employee.role),
    r.days_present,
    (r.minutes / 60).toFixed(2),
    r.open_days,
    ...days.map((d) => {
      const rec = r.days[d]
      if (!rec) return ''
      return `${istHHMM(rec.check_in)}-${rec.check_out ? istHHMM(rec.check_out) : '?'}`
    }),
  ])
  return [header, ...rows].map((row) => row.map(cell).join(',')).join('\r\n') + '\r\n'
}
