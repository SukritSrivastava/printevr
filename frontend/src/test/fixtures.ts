import type { Catalog, QuoteResponse } from '../api/types'

const rigidBreakpoints = [100, 250, 500, 1000, 2000].map((q) => ({ qty_from: q, label: `${q} qty` }))

export const catalog: Catalog = {
  loaded_at: '2026-09-26T00:00:00Z',
  show_invoice_billing: false,
  categories: [
    {
      name: 'Rigid Boxes',
      products: [
        {
          id: 'rigid_boxes',
          name: 'Rigid Boxes',
          sale_unit: 'box',
          custom_dims: 'box',
          anchor_match: ['option_1'],
          size_label: 'Size',
          option_labels: { option_1: 'Box type' },
          yield_factor: 1,
          micro_uom: null,
          micro_unit: null,
          micro_approx: false,
          min_qty: 100,
          max_qty: null,
          production_time: '10-12 days',
          breakpoints: rigidBreakpoints,
          addons: [],
          suggest_more: true,
          notes: ['Delivery and design charges extra'],
          items: [
            { id: 'rigid_boxes/3x3x2-in/top-bottom', size: '3 × 3 × 2 in', option_1: 'Top-Bottom', option_2: null, breakpoints: rigidBreakpoints, production_time: '10-12 days', has_sample: false },
            { id: 'rigid_boxes/3x3x2-in/magnetic-slider', size: '3 × 3 × 2 in', option_1: 'Magnetic / Slider', option_2: null, breakpoints: rigidBreakpoints, production_time: '10-12 days', has_sample: false },
            { id: 'rigid_boxes/5x3x2-in/top-bottom', size: '5 × 3 × 2 in', option_1: 'Top-Bottom', option_2: null, breakpoints: rigidBreakpoints, production_time: '10-12 days', has_sample: false },
          ],
        },
      ],
    },
  ],
}

const base = {
  product: { id: 'rigid_boxes', name: 'Rigid Boxes', category: 'Rigid Boxes', item_id: 'rigid_boxes/3x3x2-in/top-bottom', description: '3 × 3 × 2 in, Top-Bottom' },
  addons: [],
  production_time: '10-12 days',
  notes: ['Delivery and design charges extra'],
}

/** Real API responses for BRD tests T1, T5 and C1. */
export const T1: QuoteResponse = {
  status: 'success',
  data: {
    ...base,
    quantity: { requested: 350, billed: 350, sale_unit: 'box' },
    pricing: {
      tier_applied: { qty_from: 250, label: '250 qty', range: '250-499' },
      unit_price: '75.00', micro_unit_price: null, micro_uom: null, micro_approx: false,
      next_tier: { qty_from: 500, units_to_next: 150, unit_price: '55.00' },
      better_option: null, custom_estimate: null,
    },
    totals: { subtotal: '26250.00', billing_type: 'gst', gst_rate_percent: '18', gst_amount: '4725.00', grand_total: '30975.00' },
    warnings: [],
  },
}

export const T5: QuoteResponse = {
  status: 'success',
  data: {
    ...base,
    quantity: { requested: 450, billed: 450, sale_unit: 'box' },
    pricing: {
      tier_applied: { qty_from: 250, label: '250 qty', range: '250-499' },
      unit_price: '75.00', micro_unit_price: null, micro_uom: null, micro_approx: false,
      next_tier: { qty_from: 500, units_to_next: 50, unit_price: '55.00' },
      better_option: { qty: 500, subtotal: '27500.00', saving: '6250.00' },
      custom_estimate: null,
    },
    totals: { subtotal: '33750.00', billing_type: 'gst', gst_rate_percent: '18', gst_amount: '6075.00', grand_total: '39825.00' },
    warnings: [],
  },
}

export const C1: QuoteResponse = {
  status: 'success',
  data: {
    ...base,
    product: { ...base.product, item_id: null, description: 'Top-Bottom, custom 3.5 × 3.5 × 2 in' },
    quantity: { requested: 300, billed: 300, sale_unit: 'box' },
    pricing: {
      tier_applied: { qty_from: 250, label: '250 qty', range: '250-499' },
      unit_price: '88.50', micro_unit_price: null, micro_uom: null, micro_approx: false,
      next_tier: { qty_from: 500, units_to_next: 200, unit_price: '68.50' },
      better_option: null,
      custom_estimate: {
        method: 'interpolate', metric: '52.50', metric_unit: 'sq in',
        anchors: [
          { size: '3 × 3 × 2 in', metric: '42.00', unit_price: '75.00' },
          { size: '5 × 3 × 2 in', metric: '62.00', unit_price: '100.00' },
        ],
        raw_unit_price: '88.125', surcharge_pct: '0', round_step: '0.50',
      },
    },
    totals: { subtotal: '26550.00', billing_type: 'gst', gst_rate_percent: '18', gst_amount: '4779.00', grand_total: '31329.00' },
    warnings: [{ code: 'CUSTOM_ESTIMATE', message: 'Estimate - final price confirmed after design review' }],
  },
}
