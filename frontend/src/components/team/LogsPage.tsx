// Logs tab (admin only): every change made on the website, newest first. Who made it (staff
// or admin passcode, with the device and IP, until role-based login names each person), what
// changed and when (IST). Filter by date, area and text; open an entry for its details.
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError } from '../../api/client'
import { fetchLogs, type LogEntry, type LogFilter } from '../../api/team'
import { istDateTime } from '../../lib/designers'
import { AdminCancelled, TEAM, describeTeamError, useTeamAdmin } from './TeamAdmin'

const PAGE = 50

const ROLE_CHIP: Record<string, string> = {
  admin: 'bg-save-wash text-save',
  staff: 'bg-cyan-wash text-cyan-deep',
  site: 'bg-sheet text-ink-soft',
}
const ROLE_TEXT: Record<string, string> = { admin: 'Admin', staff: 'Staff', site: 'Site login' }

/** "Chrome on Android" from a user agent, or the first words when it isn't recognised. */
export function device(ua: string | null): string {
  if (!ua) return 'Unknown device'
  const browser = /Edg\//.test(ua) ? 'Edge' : /OPR\//.test(ua) ? 'Opera' : /Chrome\//.test(ua) ? 'Chrome' : /Firefox\//.test(ua) ? 'Firefox' : /Safari\//.test(ua) ? 'Safari' : null
  const os = /Android/.test(ua) ? 'Android' : /iPhone|iPad/.test(ua) ? 'iPhone/iPad' : /Windows/.test(ua) ? 'Windows' : /Mac OS X/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux' : null
  if (browser && os) return `${browser} on ${os}`
  return ua.split(/[\s/;()]+/).slice(0, 3).join(' ')
}

export function LogsPage() {
  const { isAdmin, withAdmin, unlock, settings } = useTeamAdmin()
  const [draft, setDraft] = useState<LogFilter>({})
  const [filter, setFilter] = useState<LogFilter>({})
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<number | null>(null)

  const logs = useQuery({
    queryKey: [TEAM, 'logs', filter, offset, isAdmin],
    queryFn: () => withAdmin(() => fetchLogs({ ...filter, limit: PAGE, offset })),
    enabled: isAdmin,
    placeholderData: keepPreviousData,
    refetchInterval: 30_000,
    retry: false,
  })
  const data = logs.data
  const categories = data?.categories ?? []
  const categoryLabel = (c: string) => categories.find((x) => x.value === c)?.label ?? c

  const apply = (e: React.FormEvent) => {
    e.preventDefault()
    setOffset(0)
    setFilter({ ...draft, q: draft.q?.trim() || undefined })
  }

  if (!isAdmin) {
    return (
      <main className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6">
        <h1 className="type-expanded text-2xl font-bold">Logs</h1>
        <div className="flex flex-col items-start gap-3 rounded-md bg-stock p-5 ring-1 ring-rule">
          <p className="text-ink-soft">The activity log shows every change made on the website. Only the admin can see it.</p>
          {settings && !settings.admin_configured ? (
            <p className="text-sm text-ink-soft">Admin access isn't set up on this server yet.</p>
          ) : (
            <button type="button" className="rounded-md bg-ink px-4 py-2 font-semibold text-stock" onClick={() => unlock().catch(() => {})}>
              Unlock admin
            </button>
          )}
        </div>
      </main>
    )
  }

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="type-expanded text-2xl font-bold">Logs</h1>
          <p className="mt-1 text-ink-soft">Every change made on the website: who, what and when (IST).</p>
        </div>
        <button type="button" className="rounded-md px-3 py-1.5 text-sm font-semibold ring-1 ring-rule" onClick={() => logs.refetch()}>
          Refresh
        </button>
      </div>

      <form onSubmit={apply} className="grid grid-cols-2 gap-3 rounded-md bg-stock p-3 ring-1 ring-rule sm:grid-cols-5 sm:items-end">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">From</span>
          <input type="date" className="field" value={draft.from ?? ''} onChange={(e) => setDraft({ ...draft, from: e.target.value })} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">To</span>
          <input type="date" className="field" value={draft.to ?? ''} onChange={(e) => setDraft({ ...draft, to: e.target.value })} />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Area</span>
          <select className="field" value={draft.category ?? ''} onChange={(e) => setDraft({ ...draft, category: e.target.value })}>
            <option value="">Everything</option>
            {categories.map((c) => (
              <option key={c.value} value={c.value}>
                {c.label}
              </option>
            ))}
          </select>
        </label>
        <label className="col-span-2 flex flex-col gap-1 text-sm sm:col-span-1">
          <span className="font-semibold text-ink-soft">Search</span>
          <input className="field" placeholder="Customer, bill no, name…" value={draft.q ?? ''} onChange={(e) => setDraft({ ...draft, q: e.target.value })} />
        </label>
        <button type="submit" className="col-span-2 rounded-md bg-ink px-4 py-2.5 font-semibold text-stock sm:col-span-1">
          Show
        </button>
      </form>

      {logs.isError ? (
        <p role="alert" className="text-stop">
          {logs.error instanceof AdminCancelled ? 'Unlock admin to see the log.' : logs.error instanceof ApiError && logs.error.code === 'LOGS_NOT_SET_UP'
            ? "The activity log table isn't in the database yet. Run the migrations (see README)."
            : describeTeamError(logs.error)}
        </p>
      ) : !data ? (
        <p className="text-ink-soft">Loading the log…</p>
      ) : data.entries.length === 0 ? (
        <p className="rounded-md bg-stock p-4 text-ink-soft ring-1 ring-rule">Nothing matches these filters.</p>
      ) : (
        <section aria-label="Activity log" className="flex flex-col gap-2">
          <p className="text-sm text-ink-soft" data-testid="log-count">
            {data.offset + 1}–{data.offset + data.entries.length} of {data.total} changes
          </p>
          <ul className="flex flex-col gap-2">
            {data.entries.map((e) => (
              <LogRow key={e.id} entry={e} area={categoryLabel(e.category)} open={open === e.id} onToggle={() => setOpen(open === e.id ? null : e.id)} />
            ))}
          </ul>
          <div className="flex items-center justify-between gap-2">
            <button
              type="button"
              className="rounded-md px-3 py-1.5 text-sm font-semibold ring-1 ring-rule disabled:opacity-40"
              disabled={offset === 0}
              onClick={() => setOffset(Math.max(0, offset - PAGE))}
            >
              ‹ Newer
            </button>
            <button
              type="button"
              className="rounded-md px-3 py-1.5 text-sm font-semibold ring-1 ring-rule disabled:opacity-40"
              disabled={offset + data.entries.length >= data.total}
              onClick={() => setOffset(offset + PAGE)}
            >
              Older ›
            </button>
          </div>
        </section>
      )}
    </main>
  )
}

function LogRow({ entry, area, open, onToggle }: { entry: LogEntry; area: string; open: boolean; onToggle: () => void }) {
  const details = Object.entries(entry.details ?? {}).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && v.length === 0))
  return (
    <li className="rounded-md bg-stock ring-1 ring-rule">
      <button type="button" className="flex w-full flex-wrap items-start gap-x-4 gap-y-1 px-4 py-3 text-left" onClick={onToggle} aria-expanded={open}>
        <span className="w-40 shrink-0 text-sm tabular-nums text-ink-soft">{istDateTime(entry.at)}</span>
        <span className="min-w-0 flex-1">
          <span className="block font-semibold">{entry.summary}</span>
          <span className="mt-1 flex flex-wrap items-center gap-2 text-xs">
            <span className={`rounded-full px-2 py-0.5 font-semibold ${ROLE_CHIP[entry.actor_role] ?? ROLE_CHIP.site}`}>
              {entry.actor_name ?? ROLE_TEXT[entry.actor_role] ?? entry.actor_role}
            </span>
            <span className="rounded-full bg-sheet px-2 py-0.5 text-ink-soft">{area}</span>
            <span className="text-ink-soft">
              {device(entry.user_agent)}
              {entry.ip ? ` · ${entry.ip}` : ''}
            </span>
          </span>
        </span>
        <span aria-hidden className="text-ink-soft">
          {open ? '▴' : '▾'}
        </span>
      </button>
      {open && (
        <div className="border-t border-rule px-4 py-3 text-sm">
          {details.length === 0 ? (
            <p className="text-ink-soft">No further details.</p>
          ) : (
            <dl className="grid gap-x-4 gap-y-1 sm:grid-cols-[12rem_1fr]">
              {details.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="font-semibold text-ink-soft">{k.replace(/_/g, ' ')}</dt>
                  <dd className="min-w-0 break-words">
                    <Value value={v} />
                  </dd>
                </div>
              ))}
            </dl>
          )}
          <p className="mt-2 text-xs text-ink-soft">
            {entry.method} {entry.path} · {entry.status}
          </p>
        </div>
      )}
    </li>
  )
}

function Value({ value }: { value: unknown }) {
  if (Array.isArray(value)) {
    return (
      <ul className="flex flex-col gap-0.5">
        {value.map((v, i) => (
          <li key={i}>
            <Value value={v} />
          </li>
        ))}
      </ul>
    )
  }
  if (value && typeof value === 'object') {
    const parts = Object.entries(value as Record<string, unknown>).filter(([, v]) => v !== null && v !== '')
    return (
      <span>
        {parts.map(([k, v], i) => (
          <span key={k}>
            {i > 0 && ' · '}
            <span className="text-ink-soft">{k.replace(/_/g, ' ')}:</span> {typeof v === 'object' ? JSON.stringify(v) : String(v)}
          </span>
        ))}
      </span>
    )
  }
  return <span>{typeof value === 'boolean' ? (value ? 'yes' : 'no') : String(value)}</span>
}
