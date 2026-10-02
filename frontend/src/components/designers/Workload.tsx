// View B: one card per designer — pending count, count per stage, oldest pending job, their jobs.
import { useState } from 'react'
import { fetchWorkload, type Job } from '../../api/designers'
import { age, istDateTime, JOB_STATUSES, timeAgo } from '../../lib/designers'
import { HistoryDialog, invoiceLabel } from './JobControls'
import { describe, useLive, useNow } from './live'

export function Workload() {
  const now = useNow()
  const query = useLive(['workload'], fetchWorkload)
  const [open, setOpen] = useState<Job | null>(null)

  if (query.isError)
    return (
      <div role="alert" className="flex flex-wrap items-center gap-3 text-stop">
        <span>{describe(query.error)}</span>
        <button type="button" className="rounded-md bg-ink px-3 py-1 text-sm font-semibold text-stock" onClick={() => query.refetch()}>
          Retry
        </button>
      </div>
    )
  if (!query.data) return <p className="text-ink-soft">Loading workload…</p>

  const { designers, unassigned_pending } = query.data
  return (
    <section className="flex flex-col gap-4" aria-label="Designer workload">
      {unassigned_pending > 0 && (
        <p role="status" className="rounded-md bg-warn-wash px-4 py-3 text-warn">
          {unassigned_pending} pending job{unassigned_pending === 1 ? ' has' : 's have'} no designer (nobody was active when the invoice was printed).
        </p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        {designers.map((d) => (
          <article key={d.id} className="flex flex-col gap-3 rounded-md bg-stock p-4 shadow-sm ring-1 ring-rule" aria-label={d.name}>
            <header className="flex items-baseline justify-between gap-3">
              <h2 className="type-expanded text-lg font-bold">
                {d.name}
                {!d.active && <span className="ml-2 rounded bg-sheet px-1.5 py-0.5 align-middle text-xs font-semibold text-ink-soft">Paused</span>}
              </h2>
              <p className="text-right">
                <span className="text-3xl font-bold" data-testid={`pending-${d.name}`}>
                  {d.pending}
                </span>{' '}
                <span className="text-sm text-ink-soft">pending</span>
              </p>
            </header>

            <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm sm:grid-cols-4">
              {JOB_STATUSES.map((s) => (
                <div key={s.value} className="flex flex-col">
                  <dt className="text-xs text-ink-soft">{s.label}</dt>
                  <dd className="font-semibold">{d.by_status[String(s.value) as '1']}</dd>
                </div>
              ))}
            </dl>

            <p className="text-sm">
              {d.oldest_pending_at ? (
                <>
                  Oldest pending job waiting <strong>{age(d.oldest_pending_at, now)}</strong>{' '}
                  <span className="text-ink-soft">(since {istDateTime(d.oldest_pending_at)})</span>
                </>
              ) : (
                <span className="text-ink-soft">Nothing pending.</span>
              )}
            </p>

            {d.jobs.length > 0 && (
              <ul className="flex max-h-80 flex-col divide-y divide-rule overflow-y-auto rounded ring-1 ring-rule">
                {d.jobs.map((job) => (
                  <li key={job.id}>
                    <button
                      type="button"
                      className={`flex w-full items-start justify-between gap-3 px-3 py-2 text-left text-sm hover:bg-sheet ${job.pending ? '' : 'opacity-60'}`}
                      onClick={() => setOpen(job)}
                    >
                      <span>
                        <span className="font-semibold">{invoiceLabel(job)}</span> {job.customer_name}
                        <span className="block text-xs text-ink-soft">
                          {istDateTime(job.assigned_at)} · {timeAgo(job.assigned_at, now)}
                        </span>
                      </span>
                      <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold ${job.pending ? 'bg-cyan-wash text-cyan-deep' : 'bg-save-wash text-save'}`}>
                        {job.status_label}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </article>
        ))}
      </div>
      {open && <HistoryDialog job={open} now={now} onClose={() => setOpen(null)} />}
    </section>
  )
}
