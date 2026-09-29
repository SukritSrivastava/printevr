// Cart lines and invoices (docs/BRD-cart-invoice.md sections 4 and 8.4). Money is always a string.
import type { CalculateRequest, QuoteWarning } from './types'

export interface SpecLine {
  label: string | null
  value: string
  emphasis: boolean
}

export type Middle =
  | { kind: 'none' }
  | { kind: 'note'; text: string }
  | { kind: 'reference_price'; amount: string }

export type LineSource = 'catalogue' | 'custom' | 'addon'

/** What /api/calculate returns in data.invoice_lines. */
export interface InvoiceLineDraft {
  source: LineSource
  addon_id?: string
  title: string
  specs: SpecLine[]
  customisations: SpecLine[]
  quantity: number
  unit_label: string
  middle: Middle
  catalogue_unit_price: string | null
  unit_price: string
  warnings: QuoteWarning[]
}

export interface CartLine extends InvoiceLineDraft {
  id: string
  parent_id: string | null
  calc_request: CalculateRequest | null
}

export type InvoiceBilling = 'without_gst' | 'with_gst'
export type PaymentMode = 'upi' | 'cash' | 'bank_transfer' | 'cheque'

export interface Customer {
  business_name: string
  contact_person: string
  address: string
  phone: string
}

export interface PaymentInput {
  amount: string
  date: string // YYYY-MM-DD
  mode: PaymentMode
  note: string | null
}

export interface InvoiceCreate {
  bill_no: number | null
  invoice_date: string
  billing_type: InvoiceBilling
  customer: Customer
  lines: CartLine[]
  payments: PaymentInput[]
  saving_amount: string | null
  print_mode: 'unpaid' | 'paid'
}

export type InvoiceStatus = 'unpaid' | 'part_paid' | 'paid'

export interface InvoiceSummary {
  bill_no: number
  invoice_date: string
  business_name: string
  billing_type: InvoiceBilling
  total: string
  payable: string
  received: string
  status: InvoiceStatus
  version: number
}

export interface InvoiceList {
  invoices: InvoiceSummary[]
  total: number
  limit: number
  offset: number
}

/** GET /api/invoice-settings: open to the site, no staff token needed. */
export interface InvoiceSettings {
  enabled: boolean
  /** false: invoices are rendered and downloaded but not stored (no list, Bill No typed in). */
  storage: boolean
  gst_rate: string | null
  advance_pct: string | null
}

export interface NextBillNo {
  next_bill_no: number
  gst_rate: string
  advance_pct: string
}

export interface ChangedLine {
  id: string
  quantity: number
  catalogue_unit_price: string
  warnings: QuoteWarning[]
}

/** A PDF answer: the file plus the headers the server sends with it. */
export interface InvoicePdf {
  blob: Blob
  filename: string
  billNo: number
  status: InvoiceStatus
}
