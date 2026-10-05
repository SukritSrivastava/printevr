// The products of one order, each with its own designer, status and vendor. Shown under the
// order on the jobs board; a change to one product never touches another or the order itself.
import { useState } from 'react'
import type { Designer, Job, ProductDesign } from '../../api/designers'
import { FINAL_VENDOR_WARNING, JOB_STATUSES, missingFinalVendor, type JobStatus } from '../../lib/designers'
import { invoiceLabel, VENDOR_LIST_ID } from './JobControls'
import { useProductUpdate } from './live'

const VENDOR_MAX = 80

export function ProductDesigns({ job, designers }: { job: Job; designers: Designer[] }) {
  const products = job.products ?? []
  const [open, setOpen] = useState(products.length <= 3)
  if (products.length === 0) return null
  const pending = products.filter((p) => p.pending).length
  return (
    <section aria-label={`Products in invoice ${invoiceLabel(job)}`} className="flex flex-col gap-2">
      <button
        type="button"
        className="self-start text-sm font-semibold text-cyan-deep underline-offset-2 hover:underline"
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        {open ? '▾' : '▸'} {products.length} product{products.length === 1 ? '' : 's'}
        <span className="font-normal text-ink-soft"> · {pending} pending</span>
      </button>
      {open && (
        <ul className="flex flex-col gap-2">
          {products.map((p, i) => (
            <ProductRow key={p.line_no} job={job} product={p} index={i} designers={designers} />
          ))}
        </ul>
      )}
    </section>
  )
}

function ProductRow({ job, product, index, designers }: { job: Job; product: ProductDesign; index: number; designers: Designer[] }) {
  const update = useProductUpdate()
  const name = `${product.title} (invoice ${invoiceLabel(job)})`
  const set = (change: Parameters<typeof update.mutate>[0]['change']) => update.mutate({ id: job.id, lineNo: product.line_no, change })
  // A product can name a designer who has since been paused; keep them selectable.
  const listed = product.designer_id === null || designers.some((d) => d.id === product.designer_id)
  return (
    <li className="grid gap-2 rounded-md bg-sheet p-2.5 md:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1.2fr)_minmax(0,1fr)] md:items-center">
      <div className="min-w-0">
        <p className="font-semibold">
          <span className="text-ink-soft">{index + 1}.</span> {product.title}{' '}
          <span className="text-sm font-normal text-ink-soft">
            × {product.quantity} {product.unit_label}
          </span>
        </p>
        {(product.details.length > 0 || product.addons.length > 0) && (
          <p className="truncate text-xs text-ink-soft" title={[...product.details, ...product.addons.map((a) => `+ ${a}`)].join(' · ')}>
            {[...product.details, ...product.addons.map((a) => `+ ${a}`)].join(' · ')}
          </p>
        )}
      </div>
      <label className="flex flex-col gap-0.5 text-xs md:text-sm">
        <span className="font-semibold text-ink-soft md:sr-only">Designer</span>
        <select
          className="field !py-1.5 text-sm"
          aria-label={`Designer for ${name}`}
          value={product.designer_id ?? ''}
          onChange={(e) => set({ designer_id: e.target.value ? Number(e.target.value) : null })}
        >
          <option value="">Order's designer ({job.designer_name ?? 'unassigned'})</option>
          {designers.map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
              {d.active ? '' : ' (paused)'}
            </option>
          ))}
          {!listed && <option value={product.designer_id!}>{product.designer_name ?? `Designer ${product.designer_id}`}</option>}
        </select>
      </label>
      <label className="flex flex-col gap-0.5 text-xs md:text-sm">
        <span className="font-semibold text-ink-soft md:sr-only">Status</span>
        <select
          className={`field !py-1.5 text-sm ${product.pending ? '' : 'text-save'}`}
          aria-label={`Progress of ${name}`}
          value={product.status}
          onChange={(e) => set({ status: Number(e.target.value) as JobStatus })}
        >
          {JOB_STATUSES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.value}. {s.label}
            </option>
          ))}
        </select>
        {missingFinalVendor(product) && (
          <span role="status" className="text-xs text-warn">
            {FINAL_VENDOR_WARNING}
          </span>
        )}
      </label>
      <label className="flex flex-col gap-0.5 text-xs md:text-sm">
        <span className="font-semibold text-ink-soft md:sr-only">Vendor</span>
        <ProductVendor product={product} name={name} onSave={(vendor_name) => set({ vendor_name })} />
      </label>
    </li>
  )
}

/** Saves on Enter or when the field loses focus; Escape puts the saved name back. */
function ProductVendor({ product, name, onSave }: { product: ProductDesign; name: string; onSave: (v: string | null) => void }) {
  const [draft, setDraft] = useState<string | null>(null)
  const saved = product.vendor_name ?? ''
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
      aria-label={`Vendor for ${name}`}
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
