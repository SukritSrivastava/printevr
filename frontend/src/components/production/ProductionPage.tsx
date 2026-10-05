// Production tab: invoices in production. Each order shows its details, then each of its
// products with its own ten stages: one line per stage with that stage's vendor, Sent to
// vendor, Picked up / received and Completed. A product's current stage is its first stage
// not ticked Completed. Everything is saved on the server, so every
// signed-in device sees the same progress (refreshed every REFRESH_MS while the tab is open).
import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryKey } from '@tanstack/react-query'
import { useState } from 'react'
import { ApiError, NetworkError } from '../../api/client'
import {
  addProductionJob,
  deleteProductionJob,
  fetchEmployees,
  fetchProductionJobs,
  updateProductStage,
  updateProductionJob,
  type Employee,
  type ProductProgress,
  type Progress,
  type ProductionJob,
  type ProductionJobs,
  type StageChange,
  type StageLine,
} from '../../api/production'
import { REFRESH_MS, istDateTime, timeAgo } from '../../lib/designers'
import { money } from '../../lib/format'
import { STAGES, stageLabel, type Stage } from '../../lib/production'
import { productionJobMessage, productionListMessage } from '../../lib/whatsapp'
import { Dialog } from '../Dialog'
import { StaffCancelled, useStaff } from '../StaffLoginDialog'
import { useToast } from '../Toast'
import { WhatsAppShare } from '../WhatsAppShare'
import { ManageEmployees } from './ManageEmployees'

/** Every Production query starts with this, so one invalidate refreshes them all. */
export const ROOT = 'production'
const JOBS_KEY = [ROOT, 'jobs']
const VENDOR_LIST_ID = 'production-vendor-suggestions'
const VENDOR_MAX = 80

const stopsPolling = (err: unknown) =>
  err instanceof StaffCancelled ||
  (err instanceof ApiError && ['AUTH_REQUIRED', 'STORAGE_DISABLED', 'PRODUCTION_NOT_SET_UP'].includes(err.code))

/** Refreshes every REFRESH_MS while the tab is open and visible, like Designer Assignment. */
function useLive<T>(key: QueryKey, fn: () => Promise<T>) {
  const withStaff = useStaff()
  return useQuery({
    queryKey: [ROOT, ...key],
    queryFn: () => withStaff(fn),
    placeholderData: keepPreviousData,
    refetchInterval: (query) => (stopsPolling(query.state.error) ? false : REFRESH_MS),
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: 'always',
    retry: (count, err) => !stopsPolling(err) && !(err instanceof ApiError) && count < 2,
    staleTime: 0,
  })
}

export function describe(err: unknown): string {
  if (err instanceof StaffCancelled) return 'Enter the staff passcode to see production.'
  if (err instanceof NetworkError) return "Can't reach the server."
  if (err instanceof ApiError && err.code === 'PRODUCTION_NOT_SET_UP')
    return "The production tables aren't in the database yet. Run the migrations (see README), then retry."
  if (err instanceof ApiError && err.code === 'STORAGE_DISABLED') return "This server doesn't store production jobs (no database)."
  return err instanceof Error ? err.message : String(err)
}

const reference = (job: Pick<ProductionJob, 'series' | 'bill_no'>) => `${job.series === 'gst' ? 'GST ' : ''}#${job.bill_no}`

export function ProductionPage() {
  const [managing, setManaging] = useState(false)
  const [removing, setRemoving] = useState<ProductionJob | null>(null)
  const employees = useLive(['employees'], fetchEmployees)
  const jobs = useLive(['jobs'], fetchProductionJobs)
  const list = jobs.data?.jobs ?? []
  const staff = employees.data ?? []

  return (
    <main className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="type-expanded text-2xl font-bold">Production</h1>
          <p className="mt-1 text-ink-soft">Track each invoice through the {STAGES.length} production stages.</p>
        </div>
        <button
          type="button"
          className="rounded-md border-[1.5px] border-ink px-3 py-1.5 text-sm font-semibold disabled:opacity-50"
          disabled={!employees.data}
          onClick={() => setManaging(true)}
        >
          Manage employees
        </button>
      </div>

      {employees.isError || jobs.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-stop">
          <span>{describe(employees.error ?? jobs.error)}</span>
          <button
            type="button"
            className="rounded-md bg-ink px-3 py-1 text-sm font-semibold text-stock"
            onClick={() => {
              employees.refetch()
              jobs.refetch()
            }}
          >
            Retry
          </button>
        </div>
      ) : (
        <>
          <AddJob employees={staff} disabled={!employees.data} onManage={() => setManaging(true)} />
          <div className="flex justify-end">
            <WhatsAppShare label="Share list on WhatsApp" disabled={list.length === 0} message={() => productionListMessage(list)} />
          </div>

          {jobs.isPending && <p className="text-ink-soft">Loading production jobs…</p>}
          {jobs.data && list.length === 0 && (
            <p className="rounded-md bg-stock p-4 text-ink-soft ring-1 ring-rule">
              No production jobs yet. Enter an invoice's bill number above to start tracking it.
            </p>
          )}
          {list.length > 0 && (
            <section className="flex flex-col gap-4" aria-label="Production jobs">
              <p className="text-sm text-ink-soft">
                {list.length} job{list.length === 1 ? '' : 's'} in production
              </p>
              {list.map((job) => (
                <JobCard key={job.id} job={job} employees={staff} onRemove={() => setRemoving(job)} />
              ))}
            </section>
          )}
        </>
      )}

      <datalist id={VENDOR_LIST_ID}>
        {(jobs.data?.vendors ?? []).map((v) => (
          <option key={v} value={v} />
        ))}
      </datalist>

      {managing && employees.data && <ManageEmployees employees={employees.data} onClose={() => setManaging(false)} />}
      {removing && <RemoveJob job={removing} onClose={() => setRemoving(null)} />}
    </main>
  )
}

/** Puts an issued invoice (Non-GST or GST) into production. */
function AddJob({ employees, disabled, onManage }: { employees: Employee[]; disabled: boolean; onManage: () => void }) {
  const qc = useQueryClient()
  const withStaff = useStaff()
  const [series, setSeries] = useState<'non_gst' | 'gst'>('non_gst')
  const [billNo, setBillNo] = useState('')
  const [employee, setEmployee] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    const n = Number(billNo)
    if (!billNo.trim() || !Number.isInteger(n) || n < 1) return setError('Enter the bill number')
    setBusy(true)
    setError(null)
    try {
      await withStaff(() => addProductionJob({ series, bill_no: n, employee_id: employee }))
      setBillNo('')
      await qc.invalidateQueries({ queryKey: [ROOT] })
    } catch (err) {
      if (!(err instanceof StaffCancelled)) setError(describe(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-3 rounded-md bg-stock p-3 ring-1 ring-rule" aria-label="Add a production job">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 sm:items-end">
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Document</span>
          <select className="field" value={series} onChange={(e) => setSeries(e.target.value as 'non_gst' | 'gst')}>
            <option value="non_gst">Invoice (Non-GST)</option>
            <option value="gst">GST invoice</option>
          </select>
        </label>
        <label className="flex flex-col gap-1 text-sm">
          <span className="font-semibold text-ink-soft">Bill No</span>
          <input
            className="field"
            inputMode="numeric"
            pattern="[0-9]*"
            value={billNo}
            onChange={(e) => setBillNo(e.target.value.replace(/\D/g, ''))}
          />
        </label>
        <label className="col-span-2 flex flex-col gap-1 text-sm sm:col-span-1">
          <span className="font-semibold text-ink-soft">Employee</span>
          <EmployeeSelect employees={employees} value={employee} onChange={setEmployee} label="Employee for the new job" />
        </label>
        <button
          type="submit"
          className="col-span-2 rounded-md bg-ink px-4 py-2.5 font-semibold text-stock disabled:opacity-50 sm:col-span-1"
          disabled={busy || disabled}
        >
          Add to production
        </button>
      </div>
      {employees.length === 0 && !disabled && (
        <p className="text-sm text-warn">
          No employees yet.{' '}
          <button type="button" className="font-semibold underline" onClick={onManage}>
            Add one
          </button>{' '}
          to assign jobs.
        </p>
      )}
      {error && (
        <p role="alert" className="text-sm text-stop">
          {error}
        </p>
      )}
    </form>
  )
}

function EmployeeSelect({
  employees,
  value,
  onChange,
  label,
  compact,
}: {
  employees: Employee[]
  value: number | null
  onChange: (id: number | null) => void
  label: string
  compact?: boolean
}) {
  // A job can point at someone the list hasn't loaded yet; keep them selectable.
  const known = value === null || employees.some((e) => e.id === value)
  return (
    <select
      className={`field ${compact ? '!py-1.5 text-sm' : ''}`}
      aria-label={label}
      value={value ?? ''}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
    >
      <option value="">Unassigned</option>
      {employees.map((e) => (
        <option key={e.id} value={e.id}>
          {e.name}
        </option>
      ))}
      {!known && <option value={value}>Employee {value}</option>}
    </select>
  )
}

/** The product with one stage line changed, and its current stage worked out again. */
function withStage(product: ProductProgress, stage: Stage, change: StageChange): ProductProgress {
  const stages = product.stages.map((line) =>
    line.stage !== stage
      ? line
      : {
          ...line,
          ...change,
          vendor_name: change.vendor_name !== undefined ? change.vendor_name?.trim().replace(/\s+/g, ' ') || null : line.vendor_name,
        },
  )
  const current = stages.find((line) => !line.completed)?.stage ?? null
  return {
    ...product,
    stages,
    current_stage: current,
    current_label: current ? stageLabel(current) : null,
    complete: current === null,
    completed_count: stages.filter((line) => line.completed).length,
  }
}

function withProductStage(job: ProductionJob, lineNo: number, stage: Stage, change: StageChange): ProductionJob {
  const products = job.products.map((p) => (p.line_no === lineNo ? withStage(p, stage, change) : p))
  const done = products.filter((p) => p.complete).length
  return { ...job, products, products_complete: done, complete: products.length > 0 && done === products.length }
}

/** Saves a change at once; the screen shows it first and puts it back if the save fails. */
function useJobMutation<V extends { id: number }>(
  save: (vars: V) => Promise<ProductionJob>,
  patch: (job: ProductionJob, vars: V, names: Map<number, string>) => ProductionJob,
) {
  const qc = useQueryClient()
  const withStaff = useStaff()
  const toast = useToast()
  return useMutation({
    mutationFn: (vars: V) => withStaff(() => save(vars)),
    onMutate: async (vars) => {
      await qc.cancelQueries({ queryKey: JOBS_KEY })
      const before = qc.getQueryData<ProductionJobs>(JOBS_KEY)
      const names = new Map((qc.getQueryData<Employee[]>([ROOT, 'employees']) ?? []).map((e) => [e.id, e.name]))
      qc.setQueryData<ProductionJobs>(JOBS_KEY, (d) =>
        d ? { ...d, jobs: d.jobs.map((j) => (j.id === vars.id ? patch(j, vars, names) : j)) } : d,
      )
      return { before }
    },
    onError: (err, _vars, ctx) => {
      if (ctx?.before) qc.setQueryData(JOBS_KEY, ctx.before)
      if (!(err instanceof StaffCancelled)) toast(`Not saved: ${describe(err)}`)
    },
    onSettled: () => qc.invalidateQueries({ queryKey: [ROOT] }),
  })
}

function useStageUpdate() {
  return useJobMutation<{ id: number; lineNo: number; stage: Stage; change: StageChange }>(
    ({ id, lineNo, stage, change }) => updateProductStage(id, lineNo, stage, change),
    (job, { lineNo, stage, change }) => withProductStage(job, lineNo, stage, change),
  )
}

function useEmployeeUpdate() {
  return useJobMutation<{ id: number; employee_id: number | null }>(
    ({ id, employee_id }) => updateProductionJob(id, { employee_id }),
    (job, { employee_id }, names) => ({ ...job, employee_id, employee_name: employee_id === null ? null : names.get(employee_id) ?? null }),
  )
}

/** One segment per stage, filled for each stage ticked Completed. */
function ProgressBar({ progress, label }: { progress: Progress; label: string }) {
  return (
    <div className="flex gap-0.5" role="img" aria-label={`${label}: ${progress.completed_count} of ${STAGES.length} stages complete`}>
      {STAGES.map(({ value }) => {
        const done = progress.stages.find((l) => l.stage === value)?.completed
        return (
          <span
            key={value}
            className={`h-1.5 flex-1 rounded-full ${done ? (progress.complete ? 'bg-save' : 'bg-cyan') : value === progress.current_stage ? 'bg-cyan-soft' : 'bg-rule'}`}
          />
        )
      })}
    </div>
  )
}

function StatusChip({ progress }: { progress: Pick<Progress, 'complete' | 'current_stage' | 'current_label'> }) {
  return (
    <span
      className={`shrink-0 rounded px-2 py-0.5 text-sm font-semibold ${progress.complete ? 'bg-save-wash text-save' : 'bg-cyan-wash text-cyan-deep'}`}
      data-testid="product-status"
    >
      {progress.complete ? 'Complete ✓' : `Current: ${progress.current_stage}. ${progress.current_label}`}
    </span>
  )
}

function JobCard({ job, employees, onRemove }: { job: ProductionJob; employees: Employee[]; onRemove: () => void }) {
  const update = useEmployeeUpdate()
  const ref = reference(job)
  const many = job.products.length > 2
  return (
    <article className="flex flex-col rounded-md bg-stock shadow-sm ring-1 ring-rule" aria-label={`Order ${ref}`}>
      <header className="flex flex-col gap-3 border-b border-rule p-3 sm:p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <h2 className="min-w-0 text-lg font-bold">
            <span className="text-cyan-deep">{ref}</span>{' '}
            {job.invoice_found ? job.customer_name : <span className="text-warn">Invoice deleted</span>}
            {job.invoice_total && <span className="ml-2 text-sm font-normal text-ink-soft">{money(job.invoice_total)}</span>}
          </h2>
          {job.products.length > 0 && (
            <span
              className={`shrink-0 rounded px-2 py-1 text-sm font-semibold ${job.complete ? 'bg-save-wash text-save' : 'bg-sheet text-ink'}`}
              data-testid="job-status"
            >
              {job.complete
                ? 'All products complete ✓'
                : `${job.products_complete} of ${job.products.length} product${job.products.length === 1 ? '' : 's'} complete`}
            </span>
          )}
        </div>
        <span className="text-xs text-ink-soft">
          Updated {istDateTime(job.updated_at)} ({timeAgo(job.updated_at)})
        </span>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <label className="flex min-w-48 flex-col gap-1 text-sm">
            <span className="font-semibold text-ink-soft">Employee</span>
            <EmployeeSelect
              employees={employees}
              value={job.employee_id}
              compact
              label={`Employee for ${ref}`}
              onChange={(id) => update.mutate({ id: job.id, employee_id: id })}
            />
          </label>
          <div className="flex items-center gap-2">
            <WhatsAppShare message={() => productionJobMessage(job)} ariaLabel={`Share ${ref} on WhatsApp`} />
            <button
              type="button"
              className="rounded-md px-3 py-1.5 text-sm font-semibold text-stop ring-1 ring-rule"
              aria-label={`Remove ${ref} from production`}
              onClick={onRemove}
            >
              Remove
            </button>
          </div>
        </div>
        {job.order_record && <OrderRecord record={job.order_record} />}
      </header>

      {job.products.length === 0 ? (
        <p className="p-4 text-sm text-ink-soft">No products to track: the invoice has been deleted.</p>
      ) : (
        <ol className="flex flex-col gap-3 p-3 sm:p-4" aria-label={`Products in ${ref}`}>
          {job.products.map((product, i) => (
            <ProductCard key={product.line_no} job={job} product={product} index={i} startOpen={!many || (!product.complete && i === job.products.findIndex((p) => !p.complete))} />
          ))}
        </ol>
      )}
    </article>
  )
}

/** Progress recorded for the whole order before products had their own stages (read only). */
function OrderRecord({ record }: { record: Progress }) {
  return (
    <div className="rounded-md bg-warn-wash px-3 py-2 text-sm">
      <p className="font-semibold text-warn">
        Recorded for the whole order before products were tracked separately: {record.completed_count} of {STAGES.length} stages complete
        {record.current_label ? ` (was at ${record.current_label})` : ''}.
      </p>
      {record.stages.some((s) => s.vendor_name || s.sent_to_vendor || s.received) && (
        <ul className="mt-1 text-xs text-ink-soft">
          {record.stages
            .filter((s) => s.vendor_name || s.sent_to_vendor || s.received)
            .map((s) => (
              <li key={s.stage}>
                {s.label}: {[s.vendor_name, s.sent_to_vendor && 'sent', s.received && 'picked up'].filter(Boolean).join(' · ')}
              </li>
            ))}
        </ul>
      )}
      <p className="mt-1 text-xs text-ink-soft">Kept for reference; it isn't copied to the products below.</p>
    </div>
  )
}

function ProductCard({ job, product, index, startOpen }: { job: ProductionJob; product: ProductProgress; index: number; startOpen: boolean }) {
  const [open, setOpen] = useState(startOpen)
  const name = `${product.title} (${reference(job)})`
  const panel = `product-${job.id}-${product.line_no}`
  return (
    <li className="overflow-hidden rounded-md ring-1 ring-rule" aria-label={`Product ${index + 1}: ${product.title}`}>
      <button
        type="button"
        className="flex w-full flex-col gap-2 bg-sheet px-3 py-2.5 text-left"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => setOpen(!open)}
      >
        <span className="flex w-full flex-wrap items-start justify-between gap-2">
          <span className="min-w-0">
            <span className="mr-1 text-ink-soft" aria-hidden>
              {open ? '▾' : '▸'}
            </span>
            <span className="font-semibold">{product.title}</span>{' '}
            <span className="text-sm text-ink-soft">
              × {product.quantity} {product.unit_label}
            </span>
          </span>
          <StatusChip progress={product} />
        </span>
        {(product.details.length > 0 || product.addons.length > 0) && (
          <span className="text-xs text-ink-soft">
            {[...product.details, ...product.addons.map((a) => `+ ${a}`)].join(' · ')}
          </span>
        )}
        <span className="flex w-full flex-col gap-1">
          <ProgressBar progress={product} label={name} />
          <span className="text-xs text-ink-soft">
            {product.completed_count} of {STAGES.length} stages complete
          </span>
        </span>
      </button>
      {open && (
        <div id={panel}>
          {/* Column headings, wide screens only (each control has its own label on phones). */}
          <div className="hidden grid-cols-[minmax(0,14rem)_minmax(0,1fr)_7rem_8rem_6rem] gap-3 border-y border-rule px-4 py-2 text-xs font-semibold text-ink-soft md:grid">
            <span>Stage</span>
            <span>Vendor</span>
            <span className="text-center">Sent to vendor</span>
            <span className="text-center">Picked up / received</span>
            <span className="text-center">Completed</span>
          </div>
          <ol aria-label={`Stages of ${name}`}>
            {product.stages.map((line) => (
              <StageRow key={line.stage} job={job} product={product} line={line} name={name} />
            ))}
          </ol>
        </div>
      )}
    </li>
  )
}

function StageRow({ job, product, line, name }: { job: ProductionJob; product: ProductProgress; line: StageLine; name: string }) {
  const update = useStageUpdate()
  const current = line.stage === product.current_stage
  const set = (change: StageChange) => update.mutate({ id: job.id, lineNo: product.line_no, stage: line.stage, change })
  const tick = (field: 'sent_to_vendor' | 'received' | 'completed', text: string) => (
    <label className="flex items-center gap-2 text-sm md:justify-center">
      <input
        type="checkbox"
        className="size-5 shrink-0 accent-cyan"
        checked={line[field]}
        aria-label={`${text}: ${line.label}, ${name}`}
        onChange={(e) => set({ [field]: e.target.checked })}
      />
      <span className="md:sr-only">{text}</span>
    </label>
  )
  return (
    <li
      className={`grid grid-cols-2 gap-x-3 gap-y-2 border-b border-rule px-3 py-3 last:border-0 md:grid-cols-[minmax(0,14rem)_minmax(0,1fr)_7rem_8rem_6rem] md:items-center md:px-4 md:py-2 ${current ? 'bg-cyan-wash' : ''}`}
      aria-current={current ? 'step' : undefined}
    >
      <div className="col-span-2 flex items-center gap-2 md:col-span-1">
        <span
          className={`flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${line.completed ? 'bg-save text-stock' : current ? 'bg-cyan text-stock' : 'bg-sheet text-ink-soft'}`}
          aria-hidden
        >
          {line.completed ? '✓' : line.stage}
        </span>
        <span className={`font-semibold ${line.completed ? 'text-save' : ''}`}>{line.label}</span>
        {current && <span className="ml-auto rounded bg-cyan px-1.5 py-0.5 text-xs font-semibold text-stock md:hidden">Current</span>}
      </div>
      <div className="col-span-2 md:col-span-1">
        <VendorInput line={line} name={name} onSave={(vendor_name) => set({ vendor_name })} />
      </div>
      {tick('sent_to_vendor', 'Sent to vendor')}
      {tick('received', 'Picked up / received')}
      <div className="col-span-2 md:col-span-1">{tick('completed', 'Completed')}</div>
    </li>
  )
}

/** Saves on Enter or when the field loses focus; Escape puts the saved name back. */
function VendorInput({ line, name, onSave }: { line: StageLine; name: string; onSave: (vendor: string | null) => void }) {
  // While typing, the field keeps its own text, so a background refresh can't overwrite it.
  const [draft, setDraft] = useState<string | null>(null)
  const saved = line.vendor_name ?? ''
  const save = () => {
    if (draft === null) return
    const value = draft.trim().replace(/\s+/g, ' ')
    setDraft(null)
    if (value !== saved) onSave(value || null)
  }
  return (
    <input
      type="text"
      className="field !py-1.5 text-sm"
      list={VENDOR_LIST_ID}
      maxLength={VENDOR_MAX}
      placeholder="Vendor"
      aria-label={`Vendor for ${line.label}, ${name}`}
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

function RemoveJob({ job, onClose }: { job: ProductionJob; onClose: () => void }) {
  const qc = useQueryClient()
  const withStaff = useStaff()
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const remove = async () => {
    setBusy(true)
    setError(null)
    try {
      await withStaff(() => deleteProductionJob(job.id))
      await qc.invalidateQueries({ queryKey: [ROOT] })
      onClose()
    } catch (err) {
      if (!(err instanceof StaffCancelled)) setError(describe(err))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog title={`Remove ${reference(job)} from production?`} onClose={onClose}>
      <p className="text-ink-soft">Its products' stage vendors and progress are forgotten. The invoice itself isn't changed.</p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-stop">
          {error}
        </p>
      )}
      <div className="mt-5 flex justify-end gap-2">
        <button type="button" className="rounded-md px-4 py-2 font-semibold ring-1 ring-rule" onClick={onClose} data-close>
          Cancel
        </button>
        <button type="button" className="rounded-md bg-stop px-4 py-2 font-semibold text-stock disabled:opacity-50" disabled={busy} onClick={remove}>
          Remove
        </button>
      </div>
    </Dialog>
  )
}
