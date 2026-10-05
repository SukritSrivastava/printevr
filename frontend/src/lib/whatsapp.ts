// WhatsApp messages for Designer Assignment and Production: one job, or the list on screen.
// Built from the API data, never from the page. They go to designers and vendors, so they
// never carry prices, amounts or invoice totals.
import type { Job } from '../api/designers'
import type { ProductionJob, ProductProgress } from '../api/production'
import { istDateTime } from './designers'
import { STAGES } from './production'

/** A shared list stops after this many jobs and says how many it left out. */
export const LIST_MAX = 30
/** "#30" or "GST #111", as both tabs show it. */
const ref = (job: { series: 'non_gst' | 'gst'; bill_no: number }) => `${job.series === 'gst' ? 'GST ' : ''}#${job.bill_no}`

/** wa.me link: straight to that number when there is one, else WhatsApp asks for the chat. */
export function whatsappUrl(message: string, phone?: string | null): string {
  const number = (phone ?? '').replace(/\D/g, '')
  return `https://wa.me/${number}?text=${encodeURIComponent(message)}`
}

export function openWhatsApp(message: string, phone?: string | null) {
  window.open(whatsappUrl(message, phone), '_blank', 'noopener,noreferrer')
}

const dateOnly = new Intl.DateTimeFormat('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', year: 'numeric' })

/** "6 Oct 2026" in IST. */
export function istDate(at: Date = new Date()): string {
  const parts = Object.fromEntries(dateOnly.formatToParts(at).map((p) => [p.type, p.value]))
  return `${parts.day} ${parts.month} ${parts.year}`
}

const jobsCount = (n: number) => `${n} job${n === 1 ? '' : 's'}`

/** "Size: 3*3*2 in", or the product's own first spec ("Paper: 300 GSM") when it has no size. */
function sizeLine(details: string[]): string | null {
  return details.find((d) => /^size:/i.test(d)) ?? details[0] ?? null
}

/** Numbered lines, at most LIST_MAX, then "…and N more". */
function numbered<T>(items: T[], line: (item: T) => string): string[] {
  const out = items.slice(0, LIST_MAX).map((item, i) => `${i + 1}. ${line(item)}`)
  if (items.length > LIST_MAX) out.push(`…and ${items.length - LIST_MAX} more`)
  return out
}

// ---------- Designer Assignment ----------

const designStatus = (x: { status: number; status_label: string }) => `${x.status}. ${x.status_label}`

/** The first product as "Title × qty", from the products, else from the job's item summary. */
function firstDesignProduct(job: Job): string {
  const p = job.products?.[0]
  if (p) return `${p.title} × ${p.quantity}`
  return job.items_summary.split('; ')[0]
}

export function designJobMessage(job: Job): string {
  const lines = [
    `*Design job – Invoice ${ref(job)}*`,
    `Customer: ${job.customer_name}`,
    `Designer: ${job.designer_name ?? 'Unassigned'}`,
    `Status: ${designStatus(job)}`,
  ]
  const products = job.products ?? []
  if (products.length > 0) {
    lines.push('', 'Products:')
    products.forEach((p, i) => {
      lines.push(`${i + 1}. ${p.title} × ${p.quantity} ${p.unit_label}`.trimEnd())
      const size = sizeLine(p.details)
      if (size) lines.push(`   ${size}`)
      lines.push(`   Designer: ${p.designer_name ?? 'Unassigned'}`, `   Status: ${designStatus(p)}`)
    })
  }
  lines.push('', `Updated: ${istDateTime(job.updated_at)}`)
  return lines.join('\n')
}

export function designListMessage(jobs: Job[], designer: string | null, today: Date = new Date()): string {
  return [
    `*Designer jobs – ${designer ?? 'All'} (${jobsCount(jobs.length)})*`,
    istDate(today),
    '',
    ...numbered(jobs, (j) =>
      [ref(j), j.customer_name, firstDesignProduct(j), designStatus(j), j.designer_name ?? 'Unassigned'].join(' · '),
    ),
  ].join('\n')
}

// ---------- Production ----------

/** What the job's status chip says. */
function productionJobStatus(job: ProductionJob): string {
  if (job.products.length === 0) return 'No products (invoice deleted)'
  if (job.complete) return 'All products complete'
  return `${job.products_complete} of ${job.products.length} product${job.products.length === 1 ? '' : 's'} complete`
}

/** What the product's status chip says. */
const productStage = (p: ProductProgress) => (p.complete ? 'Complete' : `${p.current_stage}. ${p.current_label}`)

export function productionJobMessage(job: ProductionJob): string {
  const lines = [
    `*Production job – Invoice ${ref(job)}*`,
    `Customer: ${job.invoice_found ? job.customer_name : 'Invoice deleted'}`,
    `Employee: ${job.employee_name ?? 'Unassigned'}`,
    `Status: ${productionJobStatus(job)}`,
  ]
  if (job.products.length > 0) {
    lines.push('', 'Products:')
    job.products.forEach((p, i) => {
      lines.push(`${i + 1}. ${p.title} × ${p.quantity} ${p.unit_label}`.trimEnd())
      const size = sizeLine(p.details)
      if (size) lines.push(`   ${size}`)
      lines.push(`   Stage: ${productStage(p)} (${p.completed_count} of ${STAGES.length} stages done)`)
    })
  }
  lines.push('', `Added: ${istDateTime(job.created_at)}`, `Updated: ${istDateTime(job.updated_at)}`)
  return lines.join('\n')
}

export function productionListMessage(jobs: ProductionJob[], today: Date = new Date()): string {
  return [
    `*Production jobs (${jobsCount(jobs.length)})*`,
    istDate(today),
    '',
    ...numbered(jobs, (j) => {
      const first = j.products[0]
      return [
        ref(j),
        j.invoice_found ? j.customer_name : 'Invoice deleted',
        ...(first ? [`${first.title} × ${first.quantity}`] : []),
        productionJobStatus(j),
        j.employee_name ?? 'Unassigned',
      ].join(' · ')
    }),
  ].join('\n')
}
