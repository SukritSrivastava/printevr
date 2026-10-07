// BRD-cart-invoice 11.5 (U1-U7): cart and printing, API mocked.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { CartLine, GstSlabGroup, InvoiceCreate, InvoiceLineDraft } from './api/invoiceTypes'
import type { CalculateRequest, QuoteResponse } from './api/types'
import { STORAGE_KEY, todayIST } from './cart/CartProvider'
import { fromPaise, invoiceMoney, lineSubtotal, suggestedSaving } from './lib/invoiceMoney'
import { T1, catalog } from './test/fixtures'

const RIGID = 'rigid_boxes/3x3x2-in/top-bottom'

function draft(quantity: number, price = '75.00'): InvoiceLineDraft {
  return {
    source: 'catalogue',
    title: 'Customised rigid box printing',
    specs: [
      { label: 'Size', value: '3*3*2 in (LxWxH)', emphasis: true },
      { label: 'Box type', value: 'Top-Bottom', emphasis: false },
    ],
    customisations: [],
    quantity,
    unit_label: 'boxes',
    middle: { kind: 'none' },
    catalogue_unit_price: price,
    unit_price: price,
    warnings: [],
  }
}

function quoteFor(quantity: number, price = '75.00'): QuoteResponse {
  if (T1.status !== 'success') throw new Error('fixture')
  return {
    ...T1,
    data: { ...T1.data, quantity: { ...T1.data.quantity, requested: quantity, billed: quantity }, invoice_lines: [draft(quantity, price)] },
  }
}

const MANUAL: QuoteResponse = {
  status: 'manual_quote',
  reason: 'CUSTOM_OUT_OF_RANGE',
  message: 'Custom size is larger than the largest standard size',
  data: { product: { id: 'rigid_boxes', name: 'Rigid Boxes', description: 'custom' } },
}

interface Api {
  calls: CalculateRequest[]
  invoices: InvoiceCreate[]
  logins: number
}

type InvoiceAnswer = (body: InvoiceCreate) => Response

const pdfResponse = (billNo: number, status: string, name: string, series = 'non_gst') =>
  new Response(new Blob(['%PDF-1.4 test'], { type: 'application/pdf' }), {
    status: 201,
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="${name}"`,
      'X-Bill-No': String(billNo),
      'X-Invoice-Status': status,
      'X-Document-Series': series,
    },
  })

// As GET /api/invoice-settings sends them from config/invoice.yaml.
const slab = (key: string, label: string, cgst: string, ugst: string, igst: string) => ({
  key,
  label,
  components: [
    { name: 'CGST', rate: cgst },
    { name: 'UGST', rate: ugst },
    { name: 'IGST', rate: igst },
  ],
})
const SLAB_GROUPS: GstSlabGroup[] = [
  {
    key: 'intra',
    label: 'Intra-state (CGST + SGST/UTGST, IGST 0%)',
    slabs: [
      slab('intra_5', '2.5% CGST + 2.5% SGST/UTGST (5%)', '2.5', '2.5', '0'),
      slab('intra_12', '6% CGST + 6% SGST/UTGST (12%)', '6', '6', '0'),
      slab('intra_18', '9% CGST + 9% SGST/UTGST (18%)', '9', '9', '0'),
    ],
  },
  {
    key: 'inter',
    label: 'Inter-state (IGST)',
    slabs: [slab('inter_5', '5% IGST', '0', '0', '5'), slab('inter_12', '12% IGST', '0', '0', '12'), slab('inter_18', '18% IGST', '0', '0', '18')],
  },
]
const slabOf = (key: string) => SLAB_GROUPS.flatMap((g) => g.slabs).find((s) => s.key === key)!.components

// print_payment_details: false is config/invoice.yaml's (no payment details on printed invoices).
const settingsResponse = (storage: boolean, staffPasscode = true, printPaymentDetails = false) =>
  new Response(
    JSON.stringify({
      enabled: true,
      storage,
      staff_passcode: staffPasscode,
      gst_slab_groups: SLAB_GROUPS,
      seller_state_code: '04',
      gst_field_defaults: { payment_terms: 'Advance', transport: 'Self', station: 'Chandigarh' },
      hsn_codes: { rigid_boxes: '' },
      advance_pct: '80',
      print_payment_details: printPaymentDetails,
    }),
  )

const NAMES: Record<string, string> = { quotation: 'Quotation', non_gst: 'Invoice', gst: 'GST_Invoice' }
const seriesOf = (b: InvoiceCreate) => (b.document_type === 'quotation' ? 'quotation' : (b.bill_type ?? 'non_gst'))

function mockApi(
  opts: {
    quote?: (b: CalculateRequest) => QuoteResponse
    invoice?: InvoiceAnswer
    storage?: boolean
    staffPasscode?: boolean
    printPaymentDetails?: boolean
  } = {},
): Api {
  const api: Api = { calls: [], invoices: [], logins: 0 }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/session')) return new Response(JSON.stringify({ authenticated: true, password_required: false }))
      if (url.endsWith('/api/catalog')) return new Response(JSON.stringify(catalog))
      if (url.endsWith('/api/invoice-settings')) return settingsResponse(opts.storage ?? true, opts.staffPasscode ?? true, opts.printPaymentDetails ?? false)
      if (url.endsWith('/api/calculate')) {
        const body = JSON.parse(String(init?.body)) as CalculateRequest
        api.calls.push(body)
        return new Response(JSON.stringify((opts.quote ?? ((b) => quoteFor(b.quantity)))(body)))
      }
      if (url.endsWith('/api/staff/login')) {
        api.logins++
        return new Response(JSON.stringify({ token: '9999999999.sig', expires_at: '2026-10-01T00:00:00Z' }))
      }
      if (url.endsWith('/api/invoices/next-bill-no')) {
        const count = (series: string) => api.invoices.filter((b) => seriesOf(b) === series).length
        const next = { quotation: 1 + count('quotation'), non_gst: 19 + count('non_gst'), gst: 1 + count('gst') }
        return new Response(JSON.stringify({ next_bill_no: next.non_gst, next, gst_slab_groups: SLAB_GROUPS, advance_pct: '80' }))
      }
      if (url.endsWith('/api/invoices') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as InvoiceCreate
        const series = seriesOf(body)
        const no = api.invoices.filter((b) => seriesOf(b) === series).length + (series === 'non_gst' ? 19 : 1)
        api.invoices.push(body)
        const status = series === 'quotation' ? 'issued' : body.print_mode === 'paid' ? 'paid' : 'unpaid'
        const name = series === 'non_gst' && no === 19 ? 'Invoice_19_Sogat-Jutti-Store_Unpaid.pdf' : `${NAMES[series]}_${no}_Sogat-Jutti-Store.pdf`
        return (opts.invoice ?? (() => pdfResponse(no, status, name, series)))(body)
      }
      throw new Error(`unexpected ${url}`)
    }),
  )
  return api
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

function savedCart(lines: CartLine[], checkout: Record<string, string> = {}) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 2, saved_at: Date.now(), lines, checkout }))
}

const catalogueLine = (quantity = 350): CartLine => ({
  ...draft(quantity),
  id: 'line-1',
  parent_id: null,
  calc_request: { product_id: 'rigid_boxes', item_id: RIGID, options: {}, custom_dimensions: null, quantity, addons: [], billing_type: 'gst' },
})

const SHIP_TO = { business_name: 'Sogat Jutti Store', contact_person: '', address: 'Sector 67, Mohali', phone: '+91 95010 60618', billing_type: 'non_gst' }

let downloads: string[]

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  localStorage.clear()
  sessionStorage.clear()
  downloads = []
  URL.createObjectURL = vi.fn(() => 'blob:test')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
    downloads.push(this.download)
  })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

const setup = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

async function openCart(user: ReturnType<typeof setup>) {
  await user.click(await screen.findByRole('button', { name: /^Cart/ }))
  return screen.findByRole('heading', { name: 'Cart' })
}

describe('invoice money (display)', () => {
  it('matches the PDF rules in integer paise', () => {
    const lines = [
      { quantity: 1000, unit_price: '140', middle: { kind: 'note' } },
      { quantity: 1000, unit_price: '8', middle: { kind: 'reference_price', amount: '15' } },
    ]
    const m = invoiceMoney(lines, [])
    expect([m.total, m.payable, m.advance, m.balance].map(fromPaise)).toEqual(['148000.00', '148000.00', '118400.00', '29600.00'])
    const g = invoiceMoney(lines, slabOf('inter_18'))
    expect([g.gst, g.payable, g.advance, g.balance].map(fromPaise)).toEqual(['26640.00', '174640.00', '139712.00', '34928.00'])
    expect(fromPaise(lineSubtotal(1, '88.50'))).toBe('88.50')
    expect(fromPaise(invoiceMoney([{ quantity: 1, unit_price: '88.50' }], []).advance)).toBe('70.80')
    expect(fromPaise(suggestedSaving(lines))).toBe('7000.00')
  })

  // The same cases as backend/tests/test_quotation_gst.py (Step 8), so the preview matches the PDF.
  const taxed = (price: string, key: string) => {
    const m = invoiceMoney([{ quantity: 1, unit_price: price }], slabOf(key))
    return [...m.taxes.map((t) => fromPaise(t.amount)), fromPaise(m.payable)]
  }

  it('charges CGST, UGST and IGST on the taxable value, each rounded half up on its own', () => {
    const table: [string, string[], string[]][] = [
      ['intra_5', ['250.00', '250.00', '0.00', '10500.00'], ['2.50', '2.50', '0.00', '105.05']],
      ['intra_12', ['600.00', '600.00', '0.00', '11200.00'], ['6.00', '6.00', '0.00', '112.05']],
      ['intra_18', ['900.00', '900.00', '0.00', '11800.00'], ['9.00', '9.00', '0.00', '118.05']],
      ['inter_5', ['0.00', '0.00', '500.00', '10500.00'], ['0.00', '0.00', '5.00', '105.05']],
      ['inter_12', ['0.00', '0.00', '1200.00', '11200.00'], ['0.00', '0.00', '12.01', '112.06']],
      ['inter_18', ['0.00', '0.00', '1800.00', '11800.00'], ['0.00', '0.00', '18.01', '118.06']],
    ]
    for (const [key, at10000, at100] of table) {
      expect(taxed('10000', key)).toEqual(at10000)
      expect(taxed('100.05', key)).toEqual(at100)
    }
    expect(invoiceMoney([], slabOf('intra_18')).taxes.map((t) => t.amount)).toEqual([0n, 0n, 0n])
  })
})

describe('cart', () => {
  it('U1: Add to cart shows the badge, saves to localStorage and survives a remount', async () => {
    mockApi()
    const user = setup()
    const { unmount } = renderApp()
    const qty = await screen.findByLabelText(/Quantity/)
    await user.clear(qty)
    await user.type(qty, '350')
    await act(() => vi.advanceTimersByTimeAsync(300))
    const add = await screen.findByRole('button', { name: 'Add to cart' })
    await waitFor(() => expect(add).toBeEnabled())
    await user.click(add)
    expect(screen.getByTestId('cart-count')).toHaveTextContent('1')
    expect(await screen.findByText('Added to cart')).toBeInTheDocument()
    expect(qty).toHaveValue('350') // the calculator keeps its selection
    const saved = JSON.parse(localStorage.getItem(STORAGE_KEY)!)
    expect(saved.lines).toHaveLength(1)
    expect(saved.lines[0]).toMatchObject({ title: 'Customised rigid box printing', quantity: 350, unit_price: '75.00', parent_id: null })
    expect(saved.lines[0].calc_request).toMatchObject({ item_id: RIGID, quantity: 350 })
    unmount()
    renderApp()
    await waitFor(() => expect(screen.getByTestId('cart-count')).toHaveTextContent('1'))
  })

  it('U2: changing a quantity re-quotes once after typing stops', async () => {
    savedCart([catalogueLine()])
    const api = mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    await act(() => vi.advanceTimersByTimeAsync(50))
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    const field = screen.getByLabelText('Quantity')
    await user.clear(field)
    await user.type(field, '500')
    await act(() => vi.advanceTimersByTimeAsync(300))
    await waitFor(() => expect(screen.getByTestId('line-subtotal')).toHaveTextContent('₹37,500.00'))
    // 350 is the re-quote on opening the cart; 100 is the (hidden) calculator's own default quote.
    const typed = api.calls.map((c) => c.quantity).filter((q) => q !== 350 && q !== 100)
    expect(typed).toEqual([500])
  })

  it('U3: print buttons wait for a bill type, Ship To and a priced line', async () => {
    savedCart([{ ...catalogueLine(), unit_price: '' }])
    mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    const unpaid = screen.getByRole('button', { name: 'Print (Unpaid as of now)' })
    const paid = screen.getByRole('button', { name: 'Print (Paid)' })
    expect(unpaid).toBeDisabled()
    expect(screen.getByText('Print: give every line a price, choose a bill type.')).toBeInTheDocument()
    expect(screen.getByLabelText('Non-GST invoice')).not.toBeChecked() // no default
    expect(screen.getByLabelText('GST invoice')).not.toBeChecked()
    await user.click(screen.getByLabelText('Non-GST invoice'))
    await user.type(screen.getByLabelText('Business name'), SHIP_TO.business_name)
    await user.type(screen.getByLabelText(/^Address/), SHIP_TO.address)
    expect(unpaid).toBeDisabled()
    expect(screen.getByText('Print: give every line a price, fill in Ship To.')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^Phone/), SHIP_TO.phone)
    expect(unpaid).toBeDisabled() // the line still has no price
    expect(unpaid).toHaveAccessibleDescription('Print: give every line a price.')
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Edit price' }))
    await user.type(screen.getByLabelText('Unit price (₹)'), '70')
    expect(unpaid).toBeEnabled()
    expect(paid).toBeEnabled()
  })

  it('no salesperson: the field is gone and an old saved name is dropped', async () => {
    savedCart([catalogueLine()], { ...SHIP_TO, salesperson: 'Mr. X', billing_type: 'without_gst', gst_option: 'gst_18' })
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    expect(screen.queryByLabelText(/Salesperson/)).not.toBeInTheDocument()
    // An old cart's "Without GST billing" was the default, not a choice: the bill type starts unchosen.
    expect(screen.getByLabelText('Non-GST invoice')).not.toBeChecked()
    await user.click(screen.getByLabelText('Non-GST invoice'))
    await user.click(screen.getByRole('button', { name: 'Print (Unpaid as of now)' }))
    await waitFor(() => expect(api.invoices).toHaveLength(1))
    expect(api.invoices[0]).not.toHaveProperty('salesperson')
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).checkout).not.toHaveProperty('salesperson')
  })

  it('Quotation needs only a non-empty cart: no bill type, no Ship To, no payment state', async () => {
    savedCart([catalogueLine()])
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    const quote = screen.getByRole('button', { name: 'Quotation' })
    expect(quote).toBeEnabled()
    expect(screen.getByRole('button', { name: 'Print (Unpaid as of now)' })).toBeDisabled()
    await user.click(quote)
    await waitFor(() => expect(downloads).toEqual(['Quotation_1_Sogat-Jutti-Store.pdf']))
    expect(api.invoices[0]).toMatchObject({ document_type: 'quotation', bill_type: null, gst_slab: null, gst: null, print_mode: null, payments: [], bill_no: null })
    expect(await screen.findByText('Quotation 1 downloaded')).toBeInTheDocument()

    // A GST choice doesn't change a quotation.
    await user.click(screen.getByLabelText('GST invoice'))
    await user.selectOptions(screen.getByLabelText('GST slab'), 'intra_18')
    await user.click(quote)
    await waitFor(() => expect(api.invoices).toHaveLength(2))
    expect(api.invoices[1]).toMatchObject({ document_type: 'quotation', bill_type: null, gst_slab: null, gst: null })
  })

  it('customisations: charged per box, once for the order, or free, and all of them reach the quotation', async () => {
    savedCart([catalogueLine()])
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    const add = async (text: string, charge: RegExp, price?: string, details?: string) => {
      await user.click(screen.getByRole('button', { name: 'Add a customisation to Customised rigid box printing' }))
      const dialog = await screen.findByRole('dialog', { name: /Customise/ })
      await user.type(within(dialog).getByLabelText('Customisation'), text)
      if (details) await user.type(within(dialog).getByLabelText('Details (optional)'), details)
      await user.click(within(dialog).getByRole('radio', { name: charge }))
      if (price) {
        await user.type(within(dialog).getByLabelText(/Charge (per box|for the order)/), price)
        expect(within(dialog).getByTestId('customisation-total')).toBeInTheDocument()
      }
      await user.click(within(dialog).getByRole('button', { name: 'Add customisation' }))
    }

    // A charge is required unless the customisation is free.
    await user.click(screen.getByRole('button', { name: 'Add a customisation to Customised rigid box printing' }))
    let dialog = await screen.findByRole('dialog', { name: /Customise/ })
    await user.click(within(dialog).getByRole('button', { name: 'Add customisation' }))
    expect(within(dialog).getByText('Describe the customisation')).toBeInTheDocument()
    expect(within(dialog).getByText(/Enter the charge/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))

    await add('Gold foil logo on lid', /Per box/, '12.50', 'Front only')
    await add('Custom die', /Once for the order/, '1500')
    await add('Ribbon pull tab', /No extra charge/)

    const subtotals = screen.getAllByTestId('line-subtotal').map((e) => e.textContent)
    expect(subtotals).toEqual(['₹26,250.00', '₹4,375.00', '₹1,500.00'])
    expect(screen.getByText('Customisation · per box')).toBeInTheDocument()
    expect(screen.getByText('Customisation · once for the order')).toBeInTheDocument()
    expect(screen.getByText('RIBBON PULL TAB')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Quotation' }))
    await waitFor(() => expect(api.invoices).toHaveLength(1))
    const [main, perBox, once] = api.invoices[0].lines
    expect(main.customisations).toEqual([{ label: null, value: 'Ribbon pull tab', emphasis: false }])
    expect(perBox).toMatchObject({
      source: 'customisation',
      parent_id: 'line-1',
      charge_basis: 'per_unit',
      title: 'Gold foil logo on lid (customisation)',
      quantity: 350,
      unit_label: 'boxes',
      unit_price: '12.50',
      catalogue_unit_price: null,
      specs: [
        { label: 'For', value: 'Customised rigid box printing', emphasis: false },
        { label: 'Details', value: 'Front only', emphasis: false },
      ],
    })
    expect(once).toMatchObject({ source: 'customisation', charge_basis: 'per_order', quantity: 1, unit_label: 'order', unit_price: '1500.00' })
  })

  it('a customisation charged per box follows its article when the quantity changes', async () => {
    const perBox: CartLine = {
      ...draft(350, '10.00'),
      id: 'c1',
      source: 'customisation',
      parent_id: 'line-1',
      charge_basis: 'per_unit',
      calc_request: null,
      catalogue_unit_price: null,
      title: 'Embossing (customisation)',
      specs: [],
    }
    savedCart([catalogueLine(), perBox])
    mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    await act(() => vi.advanceTimersByTimeAsync(50))
    await user.click(screen.getAllByRole('button', { name: 'Edit' })[0])
    const field = screen.getByLabelText('Quantity')
    await user.clear(field)
    await user.type(field, '500')
    await act(() => vi.advanceTimersByTimeAsync(300))
    await waitFor(() => expect(screen.getAllByTestId('line-subtotal').map((e) => e.textContent)).toEqual(['₹37,500.00', '₹5,000.00']))
  })

  it('Quotation waits for a priced line and says so', async () => {
    savedCart([{ ...catalogueLine(), unit_price: '' }])
    mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    const quote = screen.getByRole('button', { name: 'Quotation' })
    expect(quote).toBeDisabled()
    expect(quote).toHaveAccessibleDescription('Quotation: give every line a price.')
  })

  it('GST invoice: grouped slab dropdown, GST fields, all three tax rows and the request', async () => {
    savedCart([catalogueLine()], { ...SHIP_TO, billing_type: '' })
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi({ printPaymentDetails: true })
    const user = setup()
    renderApp()
    await openCart(user)
    const unpaid = screen.getByRole('button', { name: 'Print (Unpaid as of now)' })
    expect(screen.queryByLabelText('GST slab')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Transport')).not.toBeInTheDocument()

    await user.click(screen.getByLabelText('GST invoice'))
    const select = await screen.findByLabelText('GST slab')
    expect(select).toHaveValue('')
    expect(within(select).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Select GST slab',
      '2.5% CGST + 2.5% SGST/UTGST (5%)',
      '6% CGST + 6% SGST/UTGST (12%)',
      '9% CGST + 9% SGST/UTGST (18%)',
      '5% IGST',
      '12% IGST',
      '18% IGST',
    ])
    expect([...select.querySelectorAll('optgroup')].map((g) => g.label)).toEqual([
      'Intra-state (CGST + SGST/UTGST, IGST 0%)',
      'Inter-state (IGST)',
    ])
    expect(unpaid).toBeDisabled()
    expect(screen.getByText('Print: select a GST slab.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Buyer Info (Billed to)' })).toBeInTheDocument()
    expect(screen.getByLabelText('Same as buyer')).toBeChecked()
    expect(screen.getByLabelText(/^Payment Terms/)).toHaveValue('Advance')
    expect(screen.getByLabelText(/^Transport/)).toHaveValue('Self')
    expect(screen.getByLabelText(/^Station/)).toHaveValue('Chandigarh')

    const summary = screen.getByLabelText('Invoice summary')
    await user.selectOptions(select, 'inter_18')
    expect(within(summary).getByText('CGST (0%)').nextSibling).toHaveTextContent('₹0.00')
    expect(within(summary).getByText('UGST (0%)').nextSibling).toHaveTextContent('₹0.00')
    expect(within(summary).getByText('IGST (18%)').nextSibling).toHaveTextContent('₹4,725.00')
    expect(screen.getByTestId('payable')).toHaveTextContent('₹30,975.00')
    await user.selectOptions(select, 'intra_18')
    expect(within(summary).getByText('CGST (9%)').nextSibling).toHaveTextContent('₹2,362.50')
    expect(within(summary).getByText('IGST (0%)').nextSibling).toHaveTextContent('₹0.00')
    expect(unpaid).toBeEnabled()

    // Non-blocking warnings: no HSN code yet, and a buyer from another state on an intra-state slab.
    const warnings = screen.getByRole('status', { name: 'GST invoice warnings' })
    expect(warnings).toHaveTextContent('1 line has no HSN code')
    await user.type(screen.getByLabelText(/^Buyer GSTIN/), '03abcde1234f1z5')
    expect(warnings).toHaveTextContent("The buyer's GSTIN is from state 03, but an intra-state slab is chosen")
    expect(unpaid).toBeEnabled()

    await user.clear(screen.getByLabelText(/^Transport/))
    await user.type(screen.getByLabelText('HSN code for Customised rigid box printing'), '4819')
    expect(warnings).not.toHaveTextContent('HSN')
    await user.click(unpaid)
    await waitFor(() => expect(api.invoices).toHaveLength(1))
    expect(api.invoices[0]).toMatchObject({
      document_type: 'invoice',
      bill_type: 'gst',
      gst_slab: 'intra_18',
      print_mode: 'unpaid',
      gst: {
        buyer: { name: 'Sogat Jutti Store', gstin: '03ABCDE1234F1Z5' },
        consignee_same: true,
        consignee: null,
        payment_terms: 'Advance',
        transport: '', // cleared: blank prints blank
        station: 'Chandigarh',
      },
    })
    expect(api.invoices[0].lines[0].hsn_code).toBe('4819')
    expect(await screen.findByText('GST invoice 1 downloaded')).toBeInTheDocument()

    await user.click(screen.getByLabelText('Non-GST invoice'))
    expect(screen.queryByLabelText('GST slab')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Same as buyer')).not.toBeInTheDocument()
    expect(screen.getByTestId('payable')).toHaveTextContent('₹26,250.00')
  })

  it('each bill type pre-fills its own next number', async () => {
    savedCart([catalogueLine()], { ...SHIP_TO, billing_type: '' })
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    expect(screen.queryByLabelText('Bill No')).not.toBeInTheDocument()
    await user.click(screen.getByLabelText('Non-GST invoice'))
    await waitFor(() => expect(screen.getByLabelText('Bill No')).toHaveValue('19'))
    await user.click(screen.getByLabelText('GST invoice'))
    expect(screen.getByLabelText('Bill No')).toHaveValue('1')
    await user.clear(screen.getByLabelText('Bill No'))
    await user.type(screen.getByLabelText('Bill No'), '7')
    await user.click(screen.getByLabelText('Non-GST invoice'))
    expect(screen.getByLabelText('Bill No')).toHaveValue('7') // typed by hand: kept
  })

  it('with payment details printed: pays in full by default; a split is chosen per invoice and starts at the configured 80%', async () => {
    savedCart([catalogueLine()], SHIP_TO)
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi({ printPaymentDetails: true })
    const user = setup()
    renderApp()
    await openCart(user)
    const summary = screen.getByLabelText('Invoice summary')
    expect(screen.getByLabelText(/^Split payment/)).not.toBeChecked()
    expect(within(summary).getByText('Full payment before printing').nextSibling).toHaveTextContent('₹26,250.00')
    expect(within(summary).queryByText(/before dispatch/)).not.toBeInTheDocument()
    const unpaid = screen.getByRole('button', { name: 'Print (Unpaid as of now)' })
    await user.click(unpaid)
    await waitFor(() => expect(api.invoices).toHaveLength(1))
    expect(api.invoices[0].advance_pct).toBeNull()

    await user.click(screen.getByLabelText(/^Split payment/))
    const pct = screen.getByLabelText('Before printing (%)')
    expect(pct).toHaveValue('80')
    expect(within(summary).getByText('80% before printing').nextSibling).toHaveTextContent('₹21,000.00')
    expect(within(summary).getByText('20% before dispatch').nextSibling).toHaveTextContent('₹5,250.00')
    await user.clear(pct)
    await user.type(pct, '150')
    expect(unpaid).toBeDisabled()
    expect(screen.getByText('Print: check the advance %.')).toBeInTheDocument()
    await user.clear(pct)
    await user.type(pct, '50')
    expect(within(summary).getByText('50% before dispatch')).toBeInTheDocument()
    await user.click(unpaid)
    await waitFor(() => expect(api.invoices).toHaveLength(2))
    expect(api.invoices[1].advance_pct).toBe('50')

    // A quotation never carries a split.
    await user.click(screen.getByRole('button', { name: 'Quotation' }))
    await waitFor(() => expect(api.invoices).toHaveLength(3))
    expect(api.invoices[2].advance_pct).toBeNull()
  })

  it('no payment details on printed invoices: no split payment, no GST Payment Terms, no payment lines in the summary', async () => {
    savedCart([catalogueLine()], SHIP_TO)
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    const summary = screen.getByLabelText('Invoice summary')
    expect(screen.queryByLabelText(/^Split payment/)).not.toBeInTheDocument()
    expect(within(summary).queryByText(/before printing|before dispatch/)).not.toBeInTheDocument()
    expect(within(summary).getByTestId('payable')).toHaveTextContent('₹26,250.00')
    await user.click(screen.getByLabelText('GST invoice'))
    await screen.findByLabelText('GST slab')
    expect(screen.queryByLabelText(/^Payment Terms/)).not.toBeInTheDocument()
    expect(screen.getByLabelText(/^Transport/)).toHaveValue('Self')
    await user.click(screen.getByLabelText('Non-GST invoice'))
    await user.click(screen.getByRole('button', { name: 'Print (Unpaid as of now)' }))
    await waitFor(() => expect(api.invoices).toHaveLength(1))
    expect(api.invoices[0].advance_pct).toBeNull()
  })

  it('U4: Print (Unpaid) asks for the passcode, posts no payments and downloads the named file', async () => {
    savedCart([catalogueLine()], SHIP_TO)
    const api = mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    await user.click(screen.getByRole('button', { name: 'Print (Unpaid as of now)' }))
    const dialog = await screen.findByRole('dialog', { name: 'Staff passcode' })
    await user.type(within(dialog).getByLabelText('Passcode'), '1234')
    await user.click(within(dialog).getByRole('button', { name: 'Continue' }))
    await waitFor(() => expect(downloads).toEqual(['Invoice_19_Sogat-Jutti-Store_Unpaid.pdf']))
    expect(api.logins).toBe(1)
    expect(api.invoices).toHaveLength(1)
    expect(api.invoices[0]).toMatchObject({
      document_type: 'invoice',
      bill_type: 'non_gst',
      gst_slab: null,
      gst: null,
      print_mode: 'unpaid',
      payments: [],
      bill_no: null,
    })
    expect(api.invoices[0].customer.business_name).toBe('Sogat Jutti Store')
    expect(api.invoices[0]).not.toHaveProperty('salesperson')
    expect(await screen.findByText('Invoice 19 downloaded')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clear cart' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Bill No')).toHaveValue('20'))
  })

  it('after printing, says which designer got the job (never on the PDF itself)', async () => {
    savedCart([catalogueLine()], SHIP_TO)
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    mockApi({
      invoice: () => {
        const r = pdfResponse(19, 'unpaid', 'Invoice_19_Sogat-Jutti-Store_Unpaid.pdf')
        r.headers.set('X-Job-Id', '7')
        r.headers.set('X-Designer', encodeURIComponent('Namit'))
        r.headers.set('X-Assigned-At', '2026-10-03T11:05:00+00:00')
        return r
      },
    })
    const user = setup()
    renderApp()
    await openCart(user)
    await user.click(screen.getByRole('button', { name: 'Print (Unpaid as of now)' }))
    expect(await screen.findByTestId('assigned')).toHaveTextContent('Assigned to Namit · 3 Oct 2026, 4:35 PM.')
    expect(screen.getByText('Invoice 19 downloaded · Assigned to Namit · 3 Oct 2026, 4:35 PM')).toBeInTheDocument()
  })

  it("U5: Print (Paid) pre-fills the payable amount and today's IST date", async () => {
    savedCart([catalogueLine()], SHIP_TO)
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    await user.click(screen.getByRole('button', { name: 'Print (Paid)' }))
    const dialog = await screen.findByRole('dialog', { name: 'Print (Paid)' })
    expect(within(dialog).getByLabelText('Amount received (₹)')).toHaveValue('26250')
    expect(within(dialog).getByLabelText('Date received')).toHaveValue(todayIST())
    expect(within(dialog).getByText('Received ₹26,250.00 of ₹26,250.00')).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Confirm and download' }))
    await waitFor(() => expect(api.invoices).toHaveLength(1))
    expect(api.invoices[0].print_mode).toBe('paid')
    expect(api.invoices[0].payments).toEqual([{ amount: '26250', date: todayIST(), mode: 'upi', note: null }])
    await waitFor(() => expect(downloads).toHaveLength(1))
  })

  it('U6: 409 PRICES_CHANGED updates the line and shows the banner without downloading', async () => {
    savedCart([catalogueLine()], SHIP_TO)
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    mockApi({
      invoice: () =>
        new Response(
          JSON.stringify({
            status: 'error',
            error: { code: 'PRICES_CHANGED', message: 'Prices changed', details: { lines: [{ id: 'line-1', quantity: 350, catalogue_unit_price: '80.00', warnings: [] }] } },
          }),
          { status: 409 },
        ),
    })
    const user = setup()
    renderApp()
    await openCart(user)
    await user.click(screen.getByRole('button', { name: 'Print (Unpaid as of now)' }))
    await waitFor(() => expect(screen.getByTestId('line-subtotal')).toHaveTextContent('₹28,000.00'))
    expect(screen.getAllByText('Prices changed since these were added. Check before printing.').length).toBeGreaterThan(0)
    expect(screen.getByRole('article', { name: /Line 1/ }).className).toContain('ring-warn')
    expect(downloads).toEqual([])
  })

  it('U7: a manual quote offers "Add as custom item" with the price empty', async () => {
    mockApi({ quote: () => MANUAL })
    const user = setup()
    renderApp()
    await screen.findByLabelText(/Quantity/)
    await act(() => vi.advanceTimersByTimeAsync(300))
    const button = await screen.findByRole('button', { name: 'Add as custom item' })
    await user.click(button)
    const dialog = await screen.findByRole('dialog', { name: 'Add custom item' })
    expect(within(dialog).getByLabelText('Title')).toHaveValue('Customised Rigid Boxes printing')
    expect(within(dialog).getAllByLabelText('Value')[0]).toHaveValue('3*3*2 in (LxWxH)')
    expect(within(dialog).getByLabelText('Unit price (₹)')).toHaveValue('')
    await user.type(within(dialog).getByLabelText('Quantity'), '50')
    await user.type(within(dialog).getByLabelText('Unit price (₹)'), '120')
    await user.click(within(dialog).getByRole('button', { name: 'Add to cart' }))
    expect(screen.getByTestId('cart-count')).toHaveTextContent('1')
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).lines[0]).toMatchObject({ source: 'custom', catalogue_unit_price: null, unit_price: '120', quantity: 50 })
  })

  it('with storage: Calculator, Cart, Invoices and Designer Assignment in the top bar, and Invoices opens at /invoices', async () => {
    mockApi({ storage: true })
    const user = setup()
    renderApp()
    await openCart(user)
    const nav = screen.getByRole('navigation', { name: 'Sections' })
    expect(within(nav).getAllByRole('button').map((b) => b.textContent?.replace(/\d+$/, ''))).toEqual(['Calculator', 'Cart', 'Invoices', 'Designer Assignment', 'Production', 'Attendance', 'Employees', 'Logs'])
    await user.click(within(nav).getByRole('button', { name: 'Invoices' }))
    expect(window.location.pathname).toBe('/invoices')
    expect(within(nav).getByRole('button', { name: 'Invoices' })).toHaveAttribute('aria-current', 'page')
  })

  it('Delete on the Invoices page asks first, then removes the invoice for everyone', async () => {
    const summary = (bill_no: number, business_name: string) => ({
      bill_no, business_name, invoice_date: '2026-10-01', billing_type: 'without_gst', total: '26250.00',
      payable: '26250.00', received: '0.00', status: 'unpaid', version: 1,
    })
    let stored = [summary(20, 'Other Shop'), summary(19, 'Sogat Jutti Store')]
    const deletes: string[] = []
    mockApi({ storage: true })
    const base = vi.mocked(fetch).getMockImplementation()!
    vi.mocked(fetch).mockImplementation(async (url, init) => {
      const u = String(url)
      if (u.includes('/api/invoices?')) return new Response(JSON.stringify({ invoices: stored, total: stored.length, limit: 25, offset: 0 }))
      if (init?.method === 'DELETE') {
        deletes.push(u)
        const billNo = Number(u.split('/').pop())
        stored = stored.filter((r) => r.bill_no !== billNo)
        return new Response(JSON.stringify({ deleted: billNo }))
      }
      return base(url, init)
    })
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const user = setup()
    renderApp()
    await user.click(await screen.findByRole('button', { name: 'Invoices' }))
    await user.click(await screen.findByRole('button', { name: 'Delete invoice 19' }))
    const dialog = screen.getByRole('dialog', { name: 'Delete invoice 19?' })
    await user.click(within(dialog).getByRole('button', { name: 'Cancel' }))
    expect(deletes).toEqual([])
    await user.click(screen.getByRole('button', { name: 'Delete invoice 19' }))
    await user.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete invoice' }))
    await waitFor(() => expect(screen.queryByText('Sogat Jutti Store')).not.toBeInTheDocument())
    expect(deletes).toEqual(['/api/invoices/19'])
    expect(screen.getByText('Other Shop')).toBeInTheDocument()
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('one password: with no staff passcode on the server, printing never asks for one', async () => {
    savedCart([catalogueLine()], SHIP_TO)
    const api = mockApi({ staffPasscode: false })
    const user = setup()
    renderApp()
    await openCart(user)
    await user.click(screen.getByRole('button', { name: 'Print (Unpaid as of now)' }))
    await waitFor(() => expect(downloads).toEqual(['Invoice_19_Sogat-Jutti-Store_Unpaid.pdf']))
    expect(screen.queryByRole('dialog', { name: 'Staff passcode' })).not.toBeInTheDocument()
    expect(api.logins).toBe(0)
  })

  it('without storage: Bill No is required, counts up after printing, and there is no Invoices tab', async () => {
    savedCart([catalogueLine()], SHIP_TO)
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi({ storage: false, invoice: (b) => pdfResponse(b.bill_no!, 'unpaid', `Invoice_${b.bill_no}_Sogat-Jutti-Store_Unpaid.pdf`) })
    const user = setup()
    renderApp()
    await openCart(user)
    await waitFor(() => expect(screen.getByText('Goes up by one after each print on this device.')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Invoices' })).not.toBeInTheDocument()
    const unpaid = screen.getByRole('button', { name: 'Print (Unpaid as of now)' })
    expect(unpaid).toBeDisabled()
    await user.type(screen.getByLabelText('Bill No'), '19')
    expect(unpaid).toBeEnabled()
    await user.click(unpaid)
    await waitFor(() => expect(downloads).toEqual(['Invoice_19_Sogat-Jutti-Store_Unpaid.pdf']))
    expect(api.invoices[0].bill_no).toBe(19)
    await waitFor(() => expect(screen.getByLabelText('Bill No')).toHaveValue('20'))
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).checkout.bill_no).toBe('20')
  })

  it('starts empty and warns when the saved cart is unreadable', async () => {
    localStorage.setItem(STORAGE_KEY, '{not json')
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    mockApi()
    renderApp()
    await waitFor(() => expect(screen.getByTestId('cart-count')).toHaveTextContent('0'))
    expect(warn).toHaveBeenCalled()
  })
})
