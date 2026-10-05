import { describe, expect, it } from 'vitest'
import type { Job } from '../api/designers'
import type { ProductionJob, StageLine } from '../api/production'
import { STAGES } from './production'
import { designJobMessage, designListMessage, istDate, productionJobMessage, productionListMessage, whatsappUrl } from './whatsapp'

const TODAY = new Date('2026-10-05T20:00:00Z') // 6 Oct in India

const job = (over: Partial<Job> = {}): Job => ({
  id: 1,
  series: 'non_gst',
  bill_no: 4004,
  customer_name: 'Sogat Jutti Store',
  invoice_total: '26250.00',
  items_summary: 'Customised rigid box printing ×350',
  designer_id: 1,
  designer_name: 'Namit',
  assigned_at: '2026-10-03T11:05:00Z',
  status: 5,
  status_label: 'Final design',
  pending: true,
  vendor_name: null,
  updated_at: '2026-10-03T11:05:00Z',
  products: [
    {
      line_no: 0,
      title: 'Customised rigid box printing',
      quantity: '350',
      unit_label: 'boxes',
      details: ['Size: 3*3*2 in (LxWxH)', 'Box type: Top-Bottom'],
      addons: [],
      designer_id: null,
      designer_name: 'Namit',
      designer_inherited: true,
      status: 6,
      status_label: 'Final vendor',
      pending: false,
      vendor_name: 'Sharma Printers',
      updated_at: null,
    },
    {
      line_no: 1,
      title: 'Customised standard visiting card printing',
      quantity: '500',
      unit_label: 'cards',
      details: ['Paper: 300 GSM'],
      addons: [],
      designer_id: 2,
      designer_name: 'Ajendra',
      designer_inherited: false,
      status: 1,
      status_label: 'Work assigned',
      pending: true,
      vendor_name: null,
      updated_at: null,
    },
  ],
  ...over,
})

const stages = (done: number, vendor?: { name: string; sent?: boolean }): StageLine[] =>
  STAGES.map(({ value, label }) => ({
    stage: value,
    label,
    vendor_name: value === done + 1 && vendor ? vendor.name : null,
    completed: value <= done,
    sent_to_vendor: value === done + 1 && !!vendor?.sent,
    received: false,
    updated_at: null,
  }))

const productionJob = (over: Partial<ProductionJob> = {}): ProductionJob => ({
  id: 7,
  series: 'gst',
  bill_no: 12,
  invoice_found: true,
  customer_name: 'Jairpur Handicrafts',
  invoice_total: '14160.00',
  products: [
    {
      line_no: 0,
      title: 'Customised rigid box printing',
      quantity: '100',
      unit_label: 'boxes',
      details: ['Size: 3*3*2 in (LxWxH)'],
      addons: [],
      current_stage: 3,
      current_label: 'Printing',
      complete: false,
      completed_count: 2,
      stages: stages(2, { name: 'Akal Packaging', sent: true }),
    },
  ],
  products_complete: 0,
  complete: false,
  order_record: null,
  employee_id: 1,
  employee_name: 'Vivek',
  created_at: '2026-10-03T11:05:00Z',
  updated_at: '2026-10-04T06:30:00Z',
  ...over,
})

describe('WhatsApp messages', () => {
  it('one design job', () => {
    expect(designJobMessage(job())).toBe(
      [
        '*Design job – Invoice #4004*',
        'Customer: Sogat Jutti Store',
        'Designer: Namit',
        'Status: 5. Final design',
        '',
        'Products:',
        '1. Customised rigid box printing × 350 boxes',
        '   Size: 3*3*2 in (LxWxH)',
        '   Designer: Namit',
        '   Status: 6. Final vendor',
        '2. Customised standard visiting card printing × 500 cards',
        '   Paper: 300 GSM',
        '   Designer: Ajendra',
        '   Status: 1. Work assigned',
        '',
        'Updated: 3 Oct 2026, 4:35 PM',
      ].join('\n'),
    )
  })

  it('the design list, with the designer filter in the title', () => {
    expect(designListMessage([job(), job({ series: 'gst', bill_no: 9, products: [], designer_name: null })], 'Namit', TODAY)).toBe(
      [
        '*Designer jobs – Namit (2 jobs)*',
        '6 Oct 2026',
        '',
        '1. #4004 · Sogat Jutti Store · Customised rigid box printing × 350 · 5. Final design · Namit',
        '2. GST #9 · Sogat Jutti Store · Customised rigid box printing ×350 · 5. Final design · Unassigned',
      ].join('\n'),
    )
    expect(designListMessage([job()], null, TODAY).split('\n')[0]).toBe('*Designer jobs – All (1 job)*')
  })

  it('one production job', () => {
    expect(productionJobMessage(productionJob())).toBe(
      [
        '*Production job – Invoice GST #12*',
        'Customer: Jairpur Handicrafts',
        'Employee: Vivek',
        'Status: 0 of 1 product complete',
        '',
        'Products:',
        '1. Customised rigid box printing × 100 boxes',
        '   Size: 3*3*2 in (LxWxH)',
        '   Stage: 3. Printing (2 of 10 stages done)',
        '',
        'Added: 3 Oct 2026, 4:35 PM',
        'Updated: 4 Oct 2026, 12:00 PM',
      ].join('\n'),
    )
  })

  it('the production list', () => {
    expect(productionListMessage([productionJob()], TODAY)).toBe(
      [
        '*Production jobs (1 job)*',
        '6 Oct 2026',
        '',
        '1. GST #12 · Jairpur Handicrafts · Customised rigid box printing × 100 · 0 of 1 product complete · Vivek',
      ].join('\n'),
    )
  })

  it('never names a vendor, even when one is saved', () => {
    const all = [designJobMessage(job()), productionJobMessage(productionJob())].join('\n')
    expect(all).not.toMatch(/Vendor:|Sharma Printers|Akal Packaging/)
  })

  it('never carries prices or totals', () => {
    const all = [
      designJobMessage(job()),
      designListMessage([job()], null),
      productionJobMessage(productionJob()),
      productionListMessage([productionJob()]),
    ].join('\n')
    expect(all).not.toMatch(/26250|14160|₹|\bRs\b|\btotal\b|\bamount\b/i)
  })

  it('stops a long list at 30 and says how many more', () => {
    const many = Array.from({ length: 33 }, (_, i) => job({ id: i, bill_no: 100 + i }))
    const lines = designListMessage(many, null, TODAY).split('\n')
    expect(lines[0]).toBe('*Designer jobs – All (33 jobs)*')
    expect(lines.filter((l) => /^\d+\. /.test(l))).toHaveLength(30)
    expect(lines.at(-1)).toBe('…and 3 more')
  })

  it('opens wa.me with the message encoded, to a number only when there is one', () => {
    expect(whatsappUrl('*Hi* & 50%\nnext')).toBe('https://wa.me/?text=*Hi*%20%26%2050%25%0Anext')
    expect(whatsappUrl('x', '+91 98765 43210')).toBe('https://wa.me/919876543210?text=x')
    expect(istDate(TODAY)).toBe('6 Oct 2026')
  })
})
