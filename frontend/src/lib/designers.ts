// Designer Assignment: job stages and IST time formatting.

export type JobStatus = 1 | 2 | 3 | 4 | 5 | 6

export const JOB_STATUSES: { value: JobStatus; label: string }[] = [
  { value: 1, label: 'Work assigned' },
  { value: 2, label: 'Sent to customer for approval' },
  { value: 3, label: 'Approval received' },
  { value: 4, label: 'Sent for sampling' },
  { value: 5, label: 'Final design' },
  { value: 6, label: 'Final vendor' },
]

/** Stages that still need the designer; only stage 6 (the last) is done.
 *  Same as PENDING_STATUSES in backend/app/designers/models.py (a backend test checks). */
export const PENDING_STATUSES: readonly JobStatus[] = [1, 2, 3, 4, 5]

/** Stage 6 names the final vendor: with the Vendor field empty the UI asks for it (the save still goes through). */
export const FINAL_VENDOR_STATUS: JobStatus = 6
export const missingFinalVendor = (x: { status: number; vendor_name: string | null }) =>
  x.status === FINAL_VENDOR_STATUS && !x.vendor_name?.trim()
export const FINAL_VENDOR_WARNING = 'Fill in the final vendor.'

export const statusLabel = (s: number) => JOB_STATUSES.find((x) => x.value === s)?.label ?? `Stage ${s}`

/** How often the open Designer Assignment tab refetches. */
export const REFRESH_MS = 10_000

const IST = 'Asia/Kolkata'
const dateTime = new Intl.DateTimeFormat('en-IN', {
  timeZone: IST,
  day: 'numeric',
  month: 'short',
  year: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  hour12: true,
})

/** "3 Oct 2026, 4:35 PM" in IST, whatever the device's time zone. */
export function istDateTime(iso: string): string {
  const parts = Object.fromEntries(dateTime.formatToParts(new Date(iso)).map((p) => [p.type, p.value]))
  return `${parts.day} ${parts.month} ${parts.year}, ${parts.hour}:${parts.minute} ${String(parts.dayPeriod).toUpperCase()}`
}

/** "just now", "5 minutes ago", "2 hours ago", "3 days ago". */
export function timeAgo(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (seconds < 45) return 'just now'
  const steps: [number, string][] = [
    [60, 'minute'],
    [3600, 'hour'],
    [86400, 'day'],
  ]
  let unit = 'minute'
  let size = 60
  for (const [s, u] of steps) if (seconds >= s) [size, unit] = [s, u]
  const n = Math.max(1, Math.round(seconds / size))
  return `${n} ${unit}${n === 1 ? '' : 's'} ago`
}

/** "2 days" / "5 hours": how long something has been waiting. */
export function age(iso: string, now: number = Date.now()): string {
  return timeAgo(iso, now).replace(/ ago$/, '').replace('just now', 'under a minute')
}
