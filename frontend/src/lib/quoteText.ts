import type { QuoteData } from '../api/types'
import { money, qtyWithUnit } from './format'

/** Plain-text quote for WhatsApp or email (FR-8, frontend item 9). */
export function quoteText(q: QuoteData): string {
  const unit = q.quantity.sale_unit
  const lines = [
    `*Printevr quote*`,
    `${q.product.name}: ${q.product.description}`,
    `Quantity: ${qtyWithUnit(q.quantity.billed, unit)}` +
      (q.quantity.billed !== q.quantity.requested ? ` (minimum order; ${q.quantity.requested} requested)` : ''),
    `Unit price: ${money(q.pricing.unit_price)} per ${unit}` +
      (q.pricing.micro_unit_price
        ? ` (${q.pricing.micro_approx ? 'approx. ' : ''}${money(q.pricing.micro_unit_price)} ${q.pricing.micro_uom})`
        : ''),
  ]
  for (const a of q.addons) {
    lines.push(`+ ${a.name}: ${money(a.price)} ${a.basis === 'per_unit' ? `per ${unit}` : 'per order'}`)
  }
  lines.push(`Subtotal: ${money(q.totals.subtotal)}`)
  if (q.totals.billing_type === 'gst') lines.push(`GST ${q.totals.gst_rate_percent}%: ${money(q.totals.gst_amount)}`)
  lines.push(`*Total: ${money(q.totals.grand_total)}*`)
  lines.push(`Production time: ${q.production_time}`)
  if (q.pricing.custom_estimate) lines.push('Custom size: estimate, final price confirmed after design review')
  lines.push('', ...q.notes.map((n) => `- ${n}`))
  return lines.join('\n')
}
