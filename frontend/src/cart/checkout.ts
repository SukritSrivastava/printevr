// The unsaved checkout form, and which of its fields are customer details.
import type { BillType } from '../api/invoiceTypes'

export interface Checkout {
  /** Ship To; on a GST invoice, the buyer (Billed to). */
  business_name: string
  contact_person: string
  address: string
  phone: string
  /** The invoice number for the chosen bill type ('' = assign the next one on print). */
  bill_no: string
  /** Without storage only: the next quotation number on this device. */
  quote_no: string
  invoice_date: string // YYYY-MM-DD
  billing_type: BillType | '' // '' = not chosen yet (no default)
  gst_slab: string // a GstSlab key; '' = not picked yet
  // GST invoice only
  buyer_gstin: string
  consignee_same: boolean
  consignee_name: string
  consignee_address: string
  consignee_phone: string
  consignee_gstin: string
  delivery_terms: string
  /** null = not touched: shows (and sends) the default from config/invoice.yaml */
  payment_terms: string | null
  po_date: string // YYYY-MM-DD or ''
  gr_rr_no: string
  transport: string | null
  vehicle_no: string
  eway_bill_no: string
  station: string | null
  saving_amount: string
  /** Off = pay in full before printing (the default); on = advance_pct now, the rest before dispatch. */
  split_payment: boolean
  /** null = not touched: shows (and sends) the config's advance percent */
  advance_pct: string | null
}

/** The GST invoice fields whose blank start shows a default (gst_field_defaults). */
export const DEFAULTED = ['payment_terms', 'transport', 'station'] as const

/** Today's date in India (YYYY-MM-DD), whatever the device's time zone. */
export function todayIST(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
}

export const emptyCheckout = (): Checkout => ({
  business_name: '',
  contact_person: '',
  address: '',
  phone: '',
  bill_no: '',
  quote_no: '1',
  invoice_date: todayIST(),
  billing_type: '',
  gst_slab: '',
  buyer_gstin: '',
  consignee_same: true,
  consignee_name: '',
  consignee_address: '',
  consignee_phone: '',
  consignee_gstin: '',
  delivery_terms: '',
  payment_terms: null,
  po_date: '',
  gr_rr_no: '',
  transport: null,
  vehicle_no: '',
  eway_bill_no: '',
  station: null,
  saving_amount: '',
  split_payment: false,
  advance_pct: null,
})

/**
 * Who the order is for and how it ships: names, addresses, phone numbers, GSTINs and the GST
 * invoice's order and transport fields. These are cleared on sign-out and after the retention
 * period (cart/storage.ts). Everything else in the form (document type, numbering, date, GST
 * slab, saving, payment split) is about the cart, not the customer, and is kept.
 */
export const CUSTOMER_FIELDS = [
  'business_name',
  'contact_person',
  'address',
  'phone',
  'buyer_gstin',
  'consignee_same',
  'consignee_name',
  'consignee_address',
  'consignee_phone',
  'consignee_gstin',
  'delivery_terms',
  'payment_terms',
  'po_date',
  'gr_rr_no',
  'transport',
  'vehicle_no',
  'eway_bill_no',
  'station',
] as const satisfies readonly (keyof Checkout)[]

/** The form with every customer field back at its blank start. */
export function withoutCustomer(checkout: Checkout): Checkout {
  const blank = emptyCheckout()
  const next = { ...checkout }
  for (const key of CUSTOMER_FIELDS) (next as Record<string, unknown>)[key] = blank[key]
  return next
}

export function hasCustomerDetails(checkout: Checkout): boolean {
  const blank = emptyCheckout()
  return CUSTOMER_FIELDS.some((key) => checkout[key] !== blank[key])
}
