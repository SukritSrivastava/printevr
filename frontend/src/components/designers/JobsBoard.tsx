// View A: every job, newest first, with filters. A table on wide screens, cards on phones.
import { Fragment, useEffect, useState } from 'react'
import { fetchJobs, type Designer, type Job, type JobFilters } from '../../api/designers'
import { JOB_STATUSES, PENDING_STATUSES, type JobStatus } from '../../lib/designers'
import { money } from '../../lib/format'
import { HistoryDialog, invoiceLabel, StatusSelect, VendorInput, When } from './JobControls'
import { describe, useLive, useNow } from './live'
import { ProductDesigns } from './ProductDesigns'

const SEARCH_DEBOUNCE_MS = 300
// This browser's last "Pending only" choice, so a refresh doesn't hide jobs that just reached the
// last stage. A convenience only: unreadable storage (private window, blocked) means the default.
const PENDING_ONLY_KEY = 'printevr.designers.pendingOnly'

function savedPendingOnly(): boolean {
  try {
    return localStorage.getItem(PENDING_ONLY_KEY) !== 'false'
  } catch {
    return true
  }
}

function savePendingOnly(value: boolean) {
  try {
    localStorage.setItem(PENDING_ONLY_KEY, String(value))
  } catch {
    // Not remembered; the board still works.
  }
}

export function JobsBoard({ designers }: { designers: Designer[] }) {
  const now = useNow()
  const [designer, setDesigner] = useState<number | null>(null)
  const [status, setStatus] = useState<JobStatus | null>(null)
  const [pendingOnly, setPendingOnlyState] = useState(savedPendingOnly)
  const setPendingOnly = (value: boolean) => {
    setPendingOnlyState(value)
    savePendingOnly(value)
  }
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [open, setOpen] = useState<Job | null>(null)

  useEffect(() => {
    const t = setTimeout(() => setSearch(q), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [q])

  const filters: JobFilters = { designer, status, pending: pendingOnly, q: search }
  // The last list stays up while a new filter loads, so it doesn't flash empty.
  const query = useLive(['jobs', filters], () => fetchJobs(filters), true)
  const jobs = query.data?.jobs ?? []
  const filtered = designer !== null || status !== null || pendingOnly || search.trim() !== ''

  return (
    <section className="flex flex-col gap-4" aria-label="Jobs board">
      <div className="grid grid-cols-2 gap-3 rounded-md bg-stock p-3 ring-1 ring-rule sm:grid-cols-4 sm:items-end">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Designer</span>
          <select className="field" value={designer ?? ''} onChange={(e) => setDesigner(e.target.value ? Number(e.target.value) : null)}>
            <option value="">All</option>
            {designers.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
                {d.active ? '' : ' (paused)'}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Status</span>
          <select
            className="field"
            value={status ?? ''}
            onChange={(e) => {
              const s = e.target.value ? (Number(e.target.value) as JobStatus) : null
              setStatus(s)
              if (s !== null && !PENDING_STATUSES.includes(s)) setPendingOnly(false) // stage 6 is never pending
            }}
          >
            <option value="">Any</option>
            {JOB_STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.value}. {s.label}
              </option>
            ))}
          </select>
        </label>
        <label className="col-span-2 flex flex-col gap-1 text-sm sm:col-span-1">
          <span className="font-semibold text-ink-soft">Search customer or invoice #</span>
          <input type="search" className="field" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
        <label className="col-span-2 flex items-center gap-2 py-2 text-sm font-semibold sm:col-span-1">
          <input
            type="checkbox"
            className="size-5 accent-cyan"
            checked={pendingOnly}
            onChange={(e) => {
              setPendingOnly(e.target.checked)
              if (e.target.checked && status !== null && !PENDING_STATUSES.includes(status)) setStatus(null)
            }}
          />
          Pending only
        </label>
      </div>

      {query.isError && (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-stop">
          <span>{describe(query.error)}</span>
          <button type="button" className="rounded-md bg-ink px-3 py-1 text-sm font-semibold text-stock" onClick={() => query.refetch()}>
            Retry
          </button>
        </div>
      )}
      {query.isPending && !query.isError && <p className="text-ink-soft">Loading jobs…</p>}
      {query.data && jobs.length === 0 && (
        <p className="text-ink-soft">{filtered ? 'No jobs match these filters.' : 'No jobs yet. Every invoice you print becomes one.'}</p>
      )}

      {jobs.length > 0 && (
        <>
          <p className="text-sm text-ink-soft">
            {query.data!.total} job{query.data!.total === 1 ? '' : 's'}
            {query.data!.total > jobs.length ? ` (newest ${jobs.length} shown)` : ''}
          </p>

          {/* Wide screens */}
          <div className="hidden overflow-x-auto rounded-md bg-stock shadow-sm ring-1 ring-rule md:block">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-rule text-ink-soft">
                <tr>
                  <th className="px-3 py-2 font-semibold">Invoice</th>
                  <th className="px-3 py-2 font-semibold">Customer</th>
                  <th className="px-3 py-2 font-semibold">Designer</th>
                  <th className="px-3 py-2 font-semibold">Assigned</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                  <th className="px-3 py-2 font-semibold">Vendor</th>
                  <th className="px-3 py-2 font-semibold">Updated</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <Fragment key={job.id}>
                  <tr className={`align-top ${job.products?.length ? '' : 'border-b border-rule last:border-0'}`}>
                    <td className="px-3 py-2">
                      <button type="button" className="font-semibold text-cyan-deep underline-offset-2 hover:underline" onClick={() => setOpen(job)}>
                        {invoiceLabel(job)}
                      </button>
                      <div className="text-xs text-ink-soft">{money(job.invoice_total)}</div>
                    </td>
                    <td className="max-w-56 px-3 py-2">
                      <div className="font-semibold">{job.customer_name}</div>
                      <div className="truncate text-xs text-ink-soft" title={job.items_summary}>
                        {job.items_summary}
                      </div>
                    </td>
                    <td className="px-3 py-2">{job.designer_name ?? <span className="text-warn">Unassigned</span>}</td>
                    <td className="px-3 py-2">
                      <When iso={job.assigned_at} now={now} />
                    </td>
                    <td className="w-60 px-3 py-2">
                      <StatusSelect job={job} />
                    </td>
                    <td className="w-44 px-3 py-2">
                      <VendorInput job={job} />
                    </td>
                    <td className="px-3 py-2">
                      <When iso={job.updated_at} now={now} />
                    </td>
                  </tr>
                  {job.products && job.products.length > 0 && (
                    <tr className="border-b border-rule last:border-0">
                      <td colSpan={7} className="px-3 pb-3">
                        <ProductDesigns job={job} designers={designers} />
                      </td>
                    </tr>
                  )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {/* Phones */}
          <ul className="flex flex-col gap-3 md:hidden">
            {jobs.map((job) => (
              <li key={job.id} className="flex flex-col gap-2 rounded-md bg-stock p-3 shadow-sm ring-1 ring-rule">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <button type="button" className="font-semibold text-cyan-deep underline-offset-2 hover:underline" onClick={() => setOpen(job)}>
                      {invoiceLabel(job)}
                    </button>{' '}
                    <span className="font-semibold">{job.customer_name}</span>
                    <p className="text-xs text-ink-soft">{job.items_summary}</p>
                  </div>
                  <span className="shrink-0 rounded bg-sheet px-2 py-0.5 text-sm font-semibold">{job.designer_name ?? 'Unassigned'}</span>
                </div>
                <p className="text-sm">
                  <span className="text-ink-soft">Assigned </span>
                  <When iso={job.assigned_at} now={now} inline />
                </p>
                <StatusSelect job={job} />
                <VendorInput job={job} />
                <ProductDesigns job={job} designers={designers} />
                <p className="text-xs text-ink-soft">
                  Updated <When iso={job.updated_at} now={now} inline />
                </p>
              </li>
            ))}
          </ul>
        </>
      )}

      {open && <HistoryDialog job={jobs.find((j) => j.id === open.id) ?? open} now={now} onClose={() => setOpen(null)} />}
    </section>
  )
}
