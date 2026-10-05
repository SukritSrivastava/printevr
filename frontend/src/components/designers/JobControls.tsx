// The pieces of a job that both views show: status dropdown, vendor field, times, history.
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { fetchHistory, type Job } from '../../api/designers'
import { FINAL_VENDOR_WARNING, istDateTime, JOB_STATUSES, missingFinalVendor, timeAgo, type JobStatus } from '../../lib/designers'
import { Dialog } from '../Dialog'
import { useStaff } from '../StaffLoginDialog'
import { describe, ROOT, useJobUpdate } from './live'

export const VENDOR_LIST_ID = 'vendor-suggestions'
const VENDOR_MAX = 80

export const invoiceLabel = (job: Pick<Job, 'series' | 'bill_no'>) => `${job.series === 'gst' ? 'GST ' : ''}#${job.bill_no}`

export function When({ iso, now, inline }: { iso: string; now: number; inline?: boolean }) {
  if (inline)
    return (
      <span>
        <time dateTime={iso}>{istDateTime(iso)}</time> <span className="text-ink-soft">· {timeAgo(iso, now)}</span>
      </span>
    )
  return (
    <span className="flex flex-col leading-tight">
      <time dateTime={iso} className="whitespace-nowrap">
        {istDateTime(iso)}
      </time>
      <span className="text-xs text-ink-soft">{timeAgo(iso, now)}</span>
    </span>
  )
}

export function StatusSelect({ job }: { job: Job }) {
  const update = useJobUpdate()
  return (
    <>
      <select
        className={`field !py-1.5 text-sm ${job.pending ? '' : 'text-save'}`}
        aria-label={`Progress of invoice ${invoiceLabel(job)}`}
        value={job.status}
        onChange={(e) => update.mutate({ id: job.id, change: { status: Number(e.target.value) as JobStatus } })}
      >
        {JOB_STATUSES.map((s) => (
          <option key={s.value} value={s.value}>
            {s.value}. {s.label}
          </option>
        ))}
      </select>
      {missingFinalVendor(job) && (
        <span role="status" className="mt-1 block text-xs text-warn">
          {FINAL_VENDOR_WARNING}
        </span>
      )}
    </>
  )
}

/** Saves on Enter or when the field loses focus; Escape puts the saved name back. */
export function VendorInput({ job }: { job: Job }) {
  const update = useJobUpdate()
  // While typing, the field keeps its own text, so a refresh in the background can't overwrite it.
  const [draft, setDraft] = useState<string | null>(null)
  const saved = job.vendor_name ?? ''
  const save = () => {
    if (draft === null) return
    const value = draft.trim().replace(/\s+/g, ' ')
    setDraft(null)
    if (value !== saved) update.mutate({ id: job.id, change: { vendor_name: value || null } })
  }
  return (
    <input
      type="text"
      className="field !py-1.5 text-sm"
      list={VENDOR_LIST_ID}
      maxLength={VENDOR_MAX}
      placeholder="Vendor"
      aria-label={`Vendor for invoice ${invoiceLabel(job)}`}
      value={draft ?? saved}
      onFocus={() => setDraft(saved)}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={save}
      onKeyDown={(e) => {
        if (e.key === 'Enter') {
          e.preventDefault()
          ;(e.target as HTMLInputElement).blur()
        } else if (e.key === 'Escape') {
          setDraft(saved)
          e.stopPropagation()
        }
      }}
    />
  )
}

export function HistoryDialog({ job, now, onClose }: { job: Job; now: number; onClose: () => void }) {
  const withStaff = useStaff()
  const query = useQuery({ queryKey: [ROOT, 'history', job.id, job.status], queryFn: () => withStaff(() => fetchHistory(job.id)) })
  return (
    <Dialog title={`Invoice ${invoiceLabel(job)} · ${job.customer_name}`} onClose={onClose}>
      <p className="text-sm text-ink-soft">
        {job.designer_name ?? 'Unassigned'} · {job.items_summary}
      </p>
      {query.isPending && <p className="mt-4 text-ink-soft">Loading…</p>}
      {query.isError && (
        <p role="alert" className="mt-4 text-stop">
          {describe(query.error)}
        </p>
      )}
      {query.data && (
        <ol className="mt-4 flex flex-col gap-3 border-l-2 border-rule pl-4">
          {query.data.history.map((h, i) => (
            <li key={i} className="relative">
              <span className="absolute top-1.5 -left-[1.4rem] size-2.5 rounded-full bg-cyan" aria-hidden />
              <p className="font-semibold">
                {h.new_status}. {h.new_label}
                {h.old_status !== null && h.old_status > h.new_status && <span className="ml-2 text-xs font-normal text-warn">moved back</span>}
              </p>
              <When iso={h.changed_at} now={now} />
            </li>
          ))}
        </ol>
      )}
      {query.data && query.data.product_history.length > 0 && (
        <>
          <h3 className="mt-5 font-semibold">Products</h3>
          <ol className="mt-2 flex flex-col gap-3 border-l-2 border-rule pl-4">
            {query.data.product_history.map((h, i) => (
              <li key={i} className="relative">
                <span className="absolute top-1.5 -left-[1.4rem] size-2.5 rounded-full bg-cyan-soft" aria-hidden />
                <p className="text-sm text-ink-soft">{h.title}</p>
                <p className="font-semibold">
                  {h.new_status}. {h.new_label}
                  {h.old_status !== null && h.old_status > h.new_status && <span className="ml-2 text-xs font-normal text-warn">moved back</span>}
                </p>
                <When iso={h.changed_at} now={now} />
              </li>
            ))}
          </ol>
        </>
      )}
      <div className="mt-5 flex justify-end">
        <button type="button" className="rounded-md px-4 py-2 font-semibold ring-1 ring-rule" onClick={onClose} data-close>
          Close
        </button>
      </div>
    </Dialog>
  )
}
