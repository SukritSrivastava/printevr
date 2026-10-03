// Production tab API. Staff routes, like /api/invoices and the designer routes.
import type { Stage } from '../lib/production'
import { json } from './invoices'

export interface Employee {
  id: number
  name: string
}

/** One job's record for one stage. */
export interface StageLine {
  stage: Stage
  label: string
  vendor_name: string | null
  completed: boolean
  sent_to_vendor: boolean
  received: boolean
  updated_at: string | null
}

/** Stage progress, worked out from the Completed ticks. */
export interface Progress {
  /** The first stage not ticked Completed; null when every stage is. */
  current_stage: Stage | null
  current_label: string | null
  complete: boolean
  completed_count: number
  stages: StageLine[]
}

/** One product of the order (a non-add-on invoice line) with its own ten stages. */
export interface ProductProgress extends Progress {
  /** Position of the line in the invoice; identifies the product. */
  line_no: number
  title: string
  quantity: string
  unit_label: string
  details: string[]
  addons: string[]
}

export interface ProductionJob {
  id: number
  series: 'non_gst' | 'gst'
  bill_no: number
  /** false when the invoice has since been deleted; customer and products are then empty. */
  invoice_found: boolean
  customer_name: string | null
  invoice_total: string | null
  products: ProductProgress[]
  products_complete: number
  /** Every product complete. */
  complete: boolean
  /** Progress recorded for the whole order before products had their own stages, where it
   *  couldn't be moved onto a single product. Read only; only stages with something recorded. */
  order_record: Progress | null
  employee_id: number | null
  employee_name: string | null
  created_at: string
  updated_at: string
}

export interface ProductionJobs {
  jobs: ProductionJob[]
  /** Vendor names already used on any stage, for suggestions. */
  vendors: string[]
}

export interface NewProductionJob {
  series: 'non_gst' | 'gst'
  bill_no: number
  employee_id: number | null
}

export interface StageChange {
  vendor_name?: string | null
  completed?: boolean
  sent_to_vendor?: boolean
  received?: boolean
}

export const fetchEmployees = () =>
  json<{ employees: Employee[] }>('/api/production/employees').then((r) => r.employees)

export const addEmployee = (name: string) =>
  json<Employee>('/api/production/employees', { method: 'POST', body: JSON.stringify({ name }) })

export const fetchProductionJobs = () => json<ProductionJobs>('/api/production/jobs')

export const addProductionJob = (job: NewProductionJob) =>
  json<ProductionJob>('/api/production/jobs', { method: 'POST', body: JSON.stringify(job) })

export const updateProductionJob = (id: number, change: { employee_id: number | null }) =>
  json<ProductionJob>(`/api/production/jobs/${id}`, { method: 'PATCH', body: JSON.stringify(change) })

export const updateProductStage = (id: number, lineNo: number, stage: Stage, change: StageChange) =>
  json<ProductionJob>(`/api/production/jobs/${id}/products/${lineNo}/stages/${stage}`, {
    method: 'PATCH',
    body: JSON.stringify(change),
  })

export const deleteProductionJob = (id: number) =>
  json<{ deleted: number }>(`/api/production/jobs/${id}`, { method: 'DELETE' })
