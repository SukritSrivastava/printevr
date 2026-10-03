// Shapes of the pricing API (BRD section 7). Money is always a string.
import type { InvoiceLineDraft } from './invoiceTypes'

export type CustomDimsKind = 'none' | 'box' | 'bag' | 'flat' | 'area_sqft'
export type OptionKey = 'option_1' | 'option_2'

export interface Breakpoint {
  qty_from: number
  label: string
}

export interface CatalogItem {
  id: string
  size: string
  option_1: string | null
  option_2: string | null
  breakpoints: Breakpoint[]
  production_time: string
  has_sample: boolean
}

export interface CatalogAddon {
  id: string
  name: string
  price: string | null
  basis: 'per_unit' | 'per_order'
  from_sheet: boolean
}

export interface CatalogProduct {
  id: string
  name: string
  sale_unit: string
  custom_dims: CustomDimsKind
  anchor_match: OptionKey[]
  size_label: string
  option_labels: Partial<Record<OptionKey, string>>
  yield_factor: number
  micro_uom: string | null
  micro_unit: string | null
  micro_approx: boolean
  min_qty: number
  max_qty: number | null
  production_time: string
  breakpoints: Breakpoint[]
  addons: CatalogAddon[]
  suggest_more: boolean
  notes: string[]
  items: CatalogItem[]
}

export interface Catalog {
  loaded_at: string
  show_invoice_billing: boolean
  categories: { name: string; products: CatalogProduct[] }[]
}

export type BillingType = 'gst' | 'invoice'

export interface CustomDimensions {
  length?: number
  width?: number
  height?: number
  side?: number
  unit: 'in' | 'cm'
}

export interface OutdoorSize {
  width: number
  height: number
  pieces: number
}

export interface CalculateRequest {
  product_id: string
  item_id: string | null
  options: Partial<Record<OptionKey, string | null>>
  custom_dimensions: CustomDimensions | null
  quantity: number
  addons: string[]
  billing_type: BillingType
  /** Outdoor only: what the UI multiplied into square feet (for the invoice line's Size text). */
  outdoor?: OutdoorSize | null
}

export interface QuoteWarning {
  code: 'PRICE_UNDER_REVIEW' | 'CUSTOM_ESTIMATE' | 'MOQ_APPLIED' | 'PRODUCTION_TIME_UNKNOWN' | string
  message: string
  flags?: string[]
}

export interface Anchor {
  size: string
  metric: string
  unit_price: string
}

/** One tier on the slider. unit_price includes the per-unit add-ons chosen (BRD-tier-slider-back-nav 7). */
export interface TierSpan {
  qty_from: number
  qty_to: number | null
  unit_price: string
  /** First quantity in this tier where a higher breakpoint costs less in total; null = none. */
  overpay_from: number | null
}

export interface TierSchedule {
  sale_unit: string
  min_qty: number
  below_min_policy: 'bill_at_min' | 'block'
  max_qty: number | null
  slider_max: number
  suggest_more: boolean
  tiers: TierSpan[]
}

export interface QuoteData {
  product: { id: string; name: string; category?: string; item_id?: string | null; description: string }
  quantity: {
    requested: number
    billed: number
    sale_unit: string
    micro?: { amount: number; unit: string; approx: boolean }
  }
  pricing: {
    tier_applied: { qty_from: number; label: string; range: string }
    unit_price: string
    micro_unit_price: string | null
    micro_uom: string | null
    micro_approx: boolean
    next_tier: { qty_from: number; units_to_next: number; unit_price: string } | null
    better_option: { qty: number; subtotal: string; saving: string } | null
    custom_estimate: {
      method: 'floor' | 'interpolate'
      metric: string
      metric_unit: string
      anchors: Anchor[]
      raw_unit_price: string
      surcharge_pct: string
      round_step: string
    } | null
  }
  addons: { id: string; name: string; price: string; basis: 'per_unit' | 'per_order' }[]
  totals: {
    subtotal: string
    billing_type: BillingType
    gst_rate_percent: string
    gst_amount: string
    grand_total: string
  }
  production_time: string
  warnings: QuoteWarning[]
  notes: string[]
  /** Invoice line drafts: [0] is the article, the rest are its per-order add-ons. */
  invoice_lines?: InvoiceLineDraft[]
  tier_schedule?: TierSchedule
}

export type QuoteResponse =
  | { status: 'success'; data: QuoteData }
  | {
      status: 'manual_quote'
      reason: 'MANUAL_QUOTE' | 'CUSTOM_OUT_OF_RANGE'
      message: string
      data: { product: { id: string; name: string; description: string }; tier_schedule?: TierSchedule }
    }

export interface ApiErrorBody {
  status: 'error'
  error: { code: string; message: string; details: Record<string, unknown> }
}
