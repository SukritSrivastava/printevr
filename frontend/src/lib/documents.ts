/**
 * Quotation, Non-GST invoice and GST invoice rules for the cart: what each button still needs,
 * the GST invoice's non-blocking warnings, and the request the server gets. Pure functions.
 * The server checks everything again; these only keep the buttons and hints honest.
 */
import type { CartLine, GstDetails, GstFieldDefaults, GstSlab, InvoiceCreate, Party, PaymentInput } from '../api/invoiceTypes'
import type { Checkout } from '../cart/CartProvider'
import { toPaise } from './invoiceMoney'

const PHONE = /^[0-9 +-]{7,20}$/
const PHONE_CHARS = /^[0-9 +-]*$/
export const GSTIN = /^[0-9]{2}[0-9A-Z]{13}$/

export type CheckoutErrors = Partial<Record<keyof Checkout, string>>

/** A line is ready to print: priced, titled, every spec filled in. */
export const lineReady = (l: CartLine) =>
  (toPaise(l.unit_price) ?? 0n) > 0n &&
  !!l.title.trim() &&
  Number(l.quantity) >= 1 &&
  [...l.specs, ...l.customisations].every((s) => s.value.trim()) &&
  (l.middle.kind !== 'note' || !!l.middle.text.trim()) &&
  (l.middle.kind !== 'reference_price' || (toPaise(l.middle.amount) ?? 0n) > 0n)

/** The catalogue product a line (or an add-on's article) was priced from. */
function productOf(line: CartLine, lines: CartLine[]): string | null {
  const source = line.source === 'addon' ? lines.find((l) => l.id === line.parent_id) : line
  const req = source?.calc_request
  if (!req) return null
  return req.product_id ?? req.item_id?.split('/')[0] ?? null
}

/** The HSN code a line prints with: typed in the cart, else its product's from config. */
export function lineHsn(line: CartLine, lines: CartLine[], hsnCodes: Record<string, string>): string {
  if (line.hsn_code !== undefined) return line.hsn_code
  const product = productOf(line, lines)
  return (product && hsnCodes[product]) || ''
}

/** Field errors for the form. What is required depends on the bill type. */
export function checkoutErrors(c: Checkout, opts: { billNoRequired?: boolean; quoteNoRequired?: boolean } = {}): CheckoutErrors {
  const e: CheckoutErrors = {}
  const gst = c.billing_type === 'gst'
  if (c.billing_type === 'non_gst') {
    if (!c.business_name.trim()) e.business_name = 'Enter the business name'
    if (!c.address.trim()) e.address = 'Enter the address'
    if (!PHONE.test(c.phone.trim())) e.phone = '7–20 digits, spaces, + or -'
  } else {
    if (gst && !c.business_name.trim()) e.business_name = "Enter the buyer's name"
    if (c.phone.trim() && !PHONE_CHARS.test(c.phone.trim())) e.phone = 'Digits, spaces, + or -'
  }
  if (gst) {
    if (c.buyer_gstin.trim() && !GSTIN.test(c.buyer_gstin.trim().toUpperCase())) e.buyer_gstin = '15 characters: state code, then letters and digits'
    if (!c.consignee_same) {
      if (!c.consignee_name.trim()) e.consignee_name = "Enter the consignee's name"
      if (c.consignee_phone.trim() && !PHONE_CHARS.test(c.consignee_phone.trim())) e.consignee_phone = 'Digits, spaces, + or -'
      if (c.consignee_gstin.trim() && !GSTIN.test(c.consignee_gstin.trim().toUpperCase()))
        e.consignee_gstin = '15 characters: state code, then letters and digits'
    }
  }
  if (c.billing_type && opts.billNoRequired && !c.bill_no) e.bill_no = 'Enter the Bill No'
  else if (c.bill_no && !/^[1-9]\d{0,6}$/.test(c.bill_no)) e.bill_no = 'Whole number from 1'
  if (opts.quoteNoRequired && !/^[1-9]\d{0,6}$/.test(c.quote_no)) e.quote_no = 'Whole number from 1'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(c.invoice_date)) e.invoice_date = 'Pick a date'
  if (c.saving_amount && toPaise(c.saving_amount) === null) e.saving_amount = 'Amount, up to 2 decimals'
  if (c.split_payment && c.advance_pct !== null) {
    const pct = toPaise(c.advance_pct)
    if (pct === null || pct <= 0n || pct >= 10000n) e.advance_pct = 'A percent above 0 and below 100'
  }
  return e
}

/** Percent due before printing: the split typed (or the config's), else 100 (pay in full). */
export function advancePercent(c: Checkout, configured: string): string {
  return c.split_payment ? (c.advance_pct ?? configured).trim() : '100'
}

const QUOTE_FIELDS: (keyof Checkout)[] = ['phone', 'quote_no', 'invoice_date', 'saving_amount']

/** What the Quotation button still needs (empty = ready). Bill type plays no part. */
export function quotationMissing(lines: CartLine[], errors: CheckoutErrors): string[] {
  const out: string[] = []
  if (!lines.length) out.push('add an item to the cart')
  else if (!lines.every(lineReady)) out.push('give every line a price')
  if (QUOTE_FIELDS.some((f) => errors[f])) out.push('fix the fields marked in red')
  return out
}

/** What the two Print buttons still need (empty = ready). */
export function printMissing(c: Checkout, lines: CartLine[], errors: CheckoutErrors, slab: GstSlab | undefined): string[] {
  const out: string[] = []
  if (!lines.length) out.push('add an item to the cart')
  else if (!lines.every(lineReady)) out.push('give every line a price')
  if (!c.billing_type) return [...out, 'choose a bill type']
  if (c.billing_type === 'non_gst' && (errors.business_name || errors.address || errors.phone)) out.push('fill in Ship To')
  if (c.billing_type === 'gst') {
    if (!slab) out.push('select a GST slab')
    if (errors.business_name) out.push("enter the buyer's name")
    if (errors.consignee_name) out.push("enter the consignee's name")
    if (errors.buyer_gstin || errors.consignee_gstin) out.push('check the GSTIN')
  }
  if (errors.advance_pct) out.push('check the advance %')
  if (errors.bill_no) out.push('enter the Bill No')
  if (errors.invoice_date || errors.saving_amount || (c.billing_type === 'gst' && errors.phone)) out.push('fix the fields marked in red')
  return out
}

/**
 * GST invoice warnings that never block printing: lines without an HSN code, and a buyer
 * GSTIN whose state doesn't match the slab (04 is intra-state for a Chandigarh seller).
 */
export function gstWarnings(c: Checkout, slab: GstSlab | undefined, lines: CartLine[], hsnCodes: Record<string, string>, stateCode: string): string[] {
  if (c.billing_type !== 'gst') return []
  const out: string[] = []
  const missing = lines.filter((l) => !lineHsn(l, lines, hsnCodes).trim()).length
  if (missing) out.push(`${missing === 1 ? '1 line has' : `${missing} lines have`} no HSN code; the HSN CODE column will print blank.`)
  const gstin = c.buyer_gstin.trim().toUpperCase()
  if (slab && stateCode && GSTIN.test(gstin)) {
    const state = gstin.slice(0, 2)
    const intra = slab.key.startsWith('intra')
    if (intra && state !== stateCode)
      out.push(`The buyer's GSTIN is from state ${state}, but an intra-state slab is chosen (intra-state is ${stateCode}).`)
    if (!intra && state === stateCode)
      out.push(`The buyer's GSTIN is from state ${stateCode} (same state), but an inter-state slab is chosen.`)
  }
  return out
}

const party = (name: string, address: string, phone: string, gstin: string): Party => ({
  name: name.trim(),
  address: address.trim(),
  phone: phone.trim(),
  gstin: gstin.trim().toUpperCase(),
})

/** A default-backed field: what was typed, else the config default. */
export const withDefault = (value: string | null, fallback: string | undefined) => (value ?? fallback ?? '')

export function gstDetails(c: Checkout, defaults: GstFieldDefaults): GstDetails {
  return {
    buyer: party(c.business_name, c.address, c.phone, c.buyer_gstin),
    consignee_same: c.consignee_same,
    consignee: c.consignee_same ? null : party(c.consignee_name, c.consignee_address, c.consignee_phone, c.consignee_gstin),
    delivery_terms: c.delivery_terms.trim(),
    payment_terms: withDefault(c.payment_terms, defaults.payment_terms).trim(),
    po_date: c.po_date || null,
    gr_rr_no: c.gr_rr_no.trim(),
    transport: withDefault(c.transport, defaults.transport).trim(),
    vehicle_no: c.vehicle_no.trim(),
    eway_bill_no: c.eway_bill_no.trim(),
    station: withDefault(c.station, defaults.station).trim(),
  }
}

export interface RequestContext {
  storage: boolean
  /** config advance_pct: what a split starts at */
  advancePct: string
  slab: GstSlab | undefined
  defaults: GstFieldDefaults
  hsnCodes: Record<string, string>
}

/** The POST /api/invoices body for a quotation, or an invoice of the chosen bill type. */
export function documentRequest(
  kind: 'quotation' | 'unpaid' | 'paid',
  c: Checkout,
  lines: CartLine[],
  ctx: RequestContext,
  payments: PaymentInput[] = [],
): InvoiceCreate {
  const quotation = kind === 'quotation'
  const gst = !quotation && c.billing_type === 'gst'
  const number = quotation ? (ctx.storage ? '' : c.quote_no) : c.bill_no
  return {
    document_type: quotation ? 'quotation' : 'invoice',
    bill_type: quotation ? null : c.billing_type || null,
    gst_slab: gst ? (ctx.slab?.key ?? null) : null,
    gst: gst ? gstDetails(c, ctx.defaults) : null,
    bill_no: number ? Number(number) : null,
    invoice_date: c.invoice_date,
    customer: {
      business_name: c.business_name.trim(),
      contact_person: c.contact_person.trim(),
      address: c.address.trim(),
      phone: c.phone.trim(),
    },
    lines: gst ? lines.map((l) => ({ ...l, hsn_code: lineHsn(l, lines, ctx.hsnCodes).trim() })) : lines,
    payments,
    saving_amount: c.saving_amount && toPaise(c.saving_amount) ? c.saving_amount : null,
    print_mode: quotation ? null : kind,
    advance_pct: !quotation && c.split_payment ? advancePercent(c, ctx.advancePct) : null,
  }
}
