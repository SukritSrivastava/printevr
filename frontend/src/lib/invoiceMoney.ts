/**
 * Invoice money rules (BRD-cart-invoice 6.1-6.2) for display in the cart. The server's
 * numbers are the real ones; these use the same rules so the summary box agrees.
 *
 * All sums are done in integer paise with BigInt. Money is never a float.
 */
import type { GstComponent, GstOption } from '../api/invoiceTypes'

/** "88.5" -> 8850n (paise). Accepts up to 2 decimals; anything else parses as null. */
export function toPaise(value: string | number | null | undefined): bigint | null {
  if (value === null || value === undefined) return null
  const text = String(value).trim()
  const m = /^(\d+)(?:\.(\d{0,2}))?$/.exec(text)
  if (!m) return null
  return BigInt(m[1]) * 100n + BigInt((m[2] ?? '').padEnd(2, '0'))
}

/** 8850n -> "88.50" (plain; format for display with lib/format money()). */
export function fromPaise(p: bigint): string {
  const neg = p < 0n
  const abs = neg ? -p : p
  const rupees = abs / 100n
  const paise = (abs % 100n).toString().padStart(2, '0')
  return `${neg ? '-' : ''}${rupees}.${paise}`
}

/** Divide and round half up (for non-negative numbers). */
function divRound(n: bigint, d: bigint): bigint {
  return (n * 2n + d) / (2n * d)
}

/** "0.18" -> [18n, 100n]; "80" -> [80n, 1n]; "9" -> [9n, 1n]. */
function ratio(value: string): [bigint, bigint] {
  const [whole, frac = ''] = value.trim().split('.')
  const scale = 10n ** BigInt(frac.length)
  return [BigInt(whole || '0') * scale + BigInt(frac || '0'), scale]
}

/** quantity × unit price, rounded to paise. Quantity may carry 2 decimals (square feet). */
export function lineSubtotal(quantity: number | string, unitPrice: string): bigint {
  const q = toPaise(quantity) // quantity in hundredths
  const p = toPaise(unitPrice)
  if (q === null || p === null) return 0n
  return divRound(q * p, 100n)
}

export interface TaxRow {
  name: string
  rate: string // percent
  amount: bigint
}

export interface InvoiceMoney {
  total: bigint
  /** One per GST component; empty without GST billing. */
  taxes: TaxRow[]
  gst: bigint
  payable: bigint
  advance: bigint
  balance: bigint
  received: bigint
  status: 'unpaid' | 'part_paid' | 'paid' | 'overpaid'
}

export interface MoneySettings {
  gstOptions: GstOption[] // from the server; empty until loaded
  advancePct: string // "80"
}

export const DEFAULT_MONEY_SETTINGS: MoneySettings = { gstOptions: [], advancePct: '80' }

/** The GST option picked for With GST billing, or undefined (without GST, or none picked yet). */
export function chosenGst(billing: string, key: string, options: GstOption[]): GstOption | undefined {
  return billing === 'with_gst' ? options.find((o) => o.key === key) : undefined
}

/**
 * `gst` is the chosen option's components (empty = no GST). Each is charged on the total and
 * rounded half up to paise on its own, exactly like the server (backend/app/invoice/gst.py).
 */
export function invoiceMoney(
  lines: { quantity: number | string; unit_price: string }[],
  gst: GstComponent[],
  settings: MoneySettings = DEFAULT_MONEY_SETTINGS,
  payments: (string | null)[] = [],
): InvoiceMoney {
  const total = lines.reduce((sum, l) => sum + lineSubtotal(l.quantity, l.unit_price), 0n)
  const taxes = gst.map((c) => {
    const [rn, rd] = ratio(c.rate)
    return { name: c.name, rate: c.rate, amount: divRound(total * rn, rd * 100n) }
  })
  const gstTotal = taxes.reduce((sum, t) => sum + t.amount, 0n)
  const payable = total + gstTotal
  const [an, ad] = ratio(settings.advancePct)
  const advance = divRound(payable * an, ad * 100n)
  const received = payments.reduce((sum, p) => sum + (toPaise(p) ?? 0n), 0n)
  const status = received > payable ? 'overpaid' : received === 0n ? 'unpaid' : received === payable ? 'paid' : 'part_paid'
  return { total, taxes, gst: gstTotal, payable, advance, balance: payable - advance, received, status }
}

/**
 * The "Use suggested" saving: Σ (reference price − unit price) × quantity over lines whose
 * middle column is a reference price above the unit price, rounded down to the nearest 100.
 */
export function suggestedSaving(
  lines: { quantity: number | string; unit_price: string; middle: { kind: string; amount?: string } }[],
): bigint {
  let saving = 0n
  for (const l of lines) {
    if (l.middle.kind !== 'reference_price') continue
    const ref = toPaise(l.middle.amount)
    const price = toPaise(l.unit_price)
    if (ref === null || price === null || ref <= price) continue
    saving += lineSubtotal(l.quantity, fromPaise(ref - price))
  }
  const hundred = 100n * 100n
  return (saving / hundred) * hundred
}
