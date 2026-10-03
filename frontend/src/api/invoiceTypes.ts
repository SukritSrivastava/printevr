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
  /** GST invoices: typed in the cart; undefined = the product's code from config/products.yaml. */
  hsn_code?: string
}

export interface CartLine extends InvoiceLineDraft {
  id: string
  parent_id: string | null
  calc_request: CalculateRequest | null
}

/** The invoice's bill type: the Printevr invoice, or the BASTTA GST invoice. */
export type BillType = 'non_gst' | 'gst'

/** Each numbered on its own. */
export type Series = 'quotation' | 'non_gst' | 'gst'

/**
 * A GST slab for GST invoices. Defined once, in config/invoice.yaml (gst_slabs); the cart gets
 * them from GET /api/invoice-settings, grouped for the dropdown, and sends back only the key.
 */
export interface GstSlab {
  key: string // "intra_18"
  label: string // "9% CGST + 9% SGST/UTGST (18%)"
  components: GstComponent[] // always CGST, UGST, IGST
}

export interface GstSlabGroup {
  key: string // "intra" | "inter"
  label: string
  slabs: GstSlab[]
}

export interface Party {
  name: string
  address: string
  phone: string
  gstin: string
}

/** A GST invoice's own fields. Blank text prints blank. */
export interface GstDetails {
  buyer: Party
  consignee_same: boolean
  consignee: Party | null
  delivery_terms: string
  payment_terms: string
  po_date: string | null // YYYY-MM-DD
  gr_rr_no: string
  transport: string
  vehicle_no: string
  eway_bill_no: string
  station: string
}

export type GstFieldDefaults = Partial<Record<'payment_terms' | 'transport' | 'station', string>>

export interface GstComponent {
  name: string // "CGST"
  rate: string // percent: "9"
}
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
  document_type: 'quotation' | 'invoice'
  /** Invoices only; null on a quotation. */
  bill_type: BillType | null
  /** A GstSlab key; GST invoices only (400 otherwise). */
  gst_slab: string | null
  gst: GstDetails | null
  bill_no: number | null
  invoice_date: string
  customer: Customer
  lines: CartLine[]
  payments: PaymentInput[]
  saving_amount: string | null
  /** Invoices only; a quotation has no payment state. */
  print_mode: 'unpaid' | 'paid' | null
  /** Invoices only: percent due before printing when the payment is split; null = pay in full. */
  advance_pct: string | null
}

/** "issued": a quotation, which has no payment state. */
export type InvoiceStatus = 'unpaid' | 'part_paid' | 'paid' | 'issued'

export interface InvoiceSummary {
  series: Series
  bill_no: number
  invoice_date: string
  business_name: string
  billing_type: string
  gst_slab: string | null
  total: string
  payable: string
  received: string
  status: InvoiceStatus
  version: number
}

export interface InvoiceList {
  series: Series
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
  /** false: no separate staff passcode; the site password covers invoicing. */
  staff_passcode: boolean
  gst_slab_groups: GstSlabGroup[]
  /** A buyer GSTIN starting with this is intra-state ("04", Chandigarh). */
  seller_state_code: string
  gst_field_defaults: GstFieldDefaults
  /** product id -> HSN code (blank until set in config/products.yaml) */
  hsn_codes: Record<string, string>
  advance_pct: string | null
  /** false: printed invoices carry no payment details (config print_payment_details). */
  print_payment_details?: boolean
}

export interface NextBillNo {
  /** The Non-GST invoice's next number (also in `next`). */
  next_bill_no: number
  next: Record<Series, number>
  gst_slab_groups: GstSlabGroup[]
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
  series: Series
  /** The invoice's design job (X-Job-Id / X-Designer / X-Assigned-At); null for quotations or without one. */
  assignment: JobAssignment | null
}

export interface JobAssignment {
  jobId: number
  /** null: no designer was active, so the job is unassigned. */
  designer: string | null
  /** UTC ISO time. */
  assignedAt: string
}
