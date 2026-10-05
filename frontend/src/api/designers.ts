// Designer Assignment API. Staff routes, like /api/invoices; the browser only ever talks to these.
import type { JobStatus } from '../lib/designers'
import { json } from './invoices'

export interface Designer {
  id: number
  name: string
  active: boolean
  rotation_order: number
}

export interface Job {
  id: number
  series: 'non_gst' | 'gst'
  bill_no: number
  customer_name: string
  invoice_total: string
  items_summary: string
  designer_id: number | null
  designer_name: string | null
  assigned_at: string
  status: JobStatus
  status_label: string
  pending: boolean
  vendor_name: string | null
  updated_at: string
  /** The order's products, each with its own design (jobs board and history only). */
  products?: ProductDesign[]
}

/** One product of the order (a non-add-on invoice line) and its own design. */
export interface ProductDesign {
  /** Position of the line in the invoice; identifies the product. */
  line_no: number
  title: string
  quantity: string
  unit_label: string
  details: string[]
  addons: string[]
  /** The product's own designer; null = the order's designer. */
  designer_id: number | null
  /** Who designs it (its own designer, else the order's). */
  designer_name: string | null
  designer_inherited: boolean
  status: JobStatus
  status_label: string
  pending: boolean
  vendor_name: string | null
  updated_at: string | null
}

export interface ProductChange {
  designer_id?: number | null
  status?: JobStatus
  vendor_name?: string | null
}

export interface ProductHistoryEntry extends HistoryEntry {
  line_no: number
  title: string
}

export interface JobFilters {
  designer?: number | null
  status?: JobStatus | null
  pending?: boolean
  q?: string
}

export interface HistoryEntry {
  old_status: JobStatus | null
  new_status: JobStatus
  new_label: string
  changed_at: string
}

export interface DesignerLoad extends Designer {
  pending: number
  by_status: Record<'1' | '2' | '3' | '4' | '5' | '6', number>
  oldest_pending_at: string | null
  jobs: Job[]
}

export interface JobChange {
  status?: JobStatus
  vendor_name?: string | null
}

export const fetchDesigners = () => json<{ designers: Designer[] }>('/api/designers').then((r) => r.designers)

export const addDesigner = (name: string) =>
  json<Designer>('/api/designers', { method: 'POST', body: JSON.stringify({ name }) })

export const updateDesigner = (id: number, change: { name?: string; active?: boolean }) =>
  json<Designer>(`/api/designers/${id}`, { method: 'PATCH', body: JSON.stringify(change) })

export function fetchJobs(filters: JobFilters): Promise<{ jobs: Job[]; total: number }> {
  const search = new URLSearchParams()
  if (filters.designer != null) search.set('designer', String(filters.designer))
  if (filters.status != null) search.set('status', String(filters.status))
  if (filters.pending) search.set('pending', 'true')
  if (filters.q?.trim()) search.set('q', filters.q.trim())
  return json(`/api/jobs?${search}`)
}

export const updateJob = (id: number, change: JobChange) =>
  json<Job>(`/api/jobs/${id}`, { method: 'PATCH', body: JSON.stringify(change) })

export const fetchHistory = (id: number) =>
  json<{ job: Job; history: HistoryEntry[]; product_history: ProductHistoryEntry[] }>(`/api/jobs/${id}/history`)

export const updateProduct = (id: number, lineNo: number, change: ProductChange) =>
  json<Job>(`/api/jobs/${id}/products/${lineNo}`, { method: 'PATCH', body: JSON.stringify(change) })

export const fetchWorkload = () =>
  json<{ designers: DesignerLoad[]; unassigned_pending: number }>('/api/workload')

export const fetchNextDesigner = () =>
  json<{ designer: Designer | null }>('/api/rotation/next').then((r) => r.designer)

export const fetchVendors = () => json<{ vendors: string[] }>('/api/vendors').then((r) => r.vendors)
