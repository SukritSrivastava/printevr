// BRD-cart-invoice 11.5 (U1-U7): cart and printing, API mocked.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { CartLine, InvoiceCreate, InvoiceLineDraft } from './api/invoiceTypes'
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

const pdfResponse = (billNo: number, status: string, name: string) =>
  new Response(new Blob(['%PDF-1.4 test'], { type: 'application/pdf' }), {
    status: 201,
    headers: {
      'Content-Type': 'application/pdf',
      'Content-Disposition': `attachment; filename="${name}"`,
      'X-Bill-No': String(billNo),
      'X-Invoice-Status': status,
    },
  })

const settingsResponse = (storage: boolean) =>
  new Response(JSON.stringify({ enabled: true, storage, gst_rate: '0.18', advance_pct: '80' }))

function mockApi(opts: { quote?: (b: CalculateRequest) => QuoteResponse; invoice?: InvoiceAnswer; storage?: boolean } = {}): Api {
  const api: Api = { calls: [], invoices: [], logins: 0 }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/session')) return new Response(JSON.stringify({ authenticated: true, password_required: false }))
      if (url.endsWith('/api/catalog')) return new Response(JSON.stringify(catalog))
      if (url.endsWith('/api/invoice-settings')) return settingsResponse(opts.storage ?? true)
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
        return new Response(JSON.stringify({ next_bill_no: 19 + api.invoices.length, gst_rate: '0.18', advance_pct: '80' }))
      }
      if (url.endsWith('/api/invoices') && init?.method === 'POST') {
        const body = JSON.parse(String(init.body)) as InvoiceCreate
        api.invoices.push(body)
        return (opts.invoice ?? (() => pdfResponse(19, body.print_mode === 'paid' ? 'paid' : 'unpaid', 'Invoice_19_Sogat-Jutti-Store_Unpaid.pdf')))(body)
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
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ lines, checkout }))
}

const catalogueLine = (quantity = 350): CartLine => ({
  ...draft(quantity),
  id: 'line-1',
  parent_id: null,
  calc_request: { product_id: 'rigid_boxes', item_id: RIGID, options: {}, custom_dimensions: null, quantity, addons: [], billing_type: 'gst' },
})

const SHIP_TO = { business_name: 'Sogat Jutti Store', contact_person: '', address: 'Sector 67, Mohali', phone: '+91 95010 60618' }

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
    const m = invoiceMoney(lines, false)
    expect([m.total, m.payable, m.advance, m.balance].map(fromPaise)).toEqual(['148000.00', '148000.00', '118400.00', '29600.00'])
    const g = invoiceMoney(lines, true)
    expect([g.gst, g.payable, g.advance, g.balance].map(fromPaise)).toEqual(['26640.00', '174640.00', '139712.00', '34928.00'])
    expect(fromPaise(lineSubtotal(1, '88.50'))).toBe('88.50')
    expect(fromPaise(invoiceMoney([{ quantity: 1, unit_price: '88.50' }], false).advance)).toBe('70.80')
    expect(fromPaise(suggestedSaving(lines))).toBe('7000.00')
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

  it('U3: print buttons wait for Ship To and a priced line', async () => {
    savedCart([{ ...catalogueLine(), unit_price: '' }])
    mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    const unpaid = screen.getByRole('button', { name: 'Print (Unpaid as of now)' })
    const paid = screen.getByRole('button', { name: 'Print (Paid)' })
    expect(unpaid).toBeDisabled()
    await user.type(screen.getByLabelText('Business name'), SHIP_TO.business_name)
    await user.type(screen.getByLabelText(/^Address/), SHIP_TO.address)
    expect(unpaid).toBeDisabled()
    await user.type(screen.getByLabelText('Phone'), SHIP_TO.phone)
    expect(unpaid).toBeDisabled() // the line still has no price
    await user.click(screen.getByRole('button', { name: 'Edit' }))
    await user.click(screen.getByRole('button', { name: 'Edit price' }))
    await user.type(screen.getByLabelText('Unit price (₹)'), '70')
    expect(unpaid).toBeEnabled()
    expect(paid).toBeEnabled()
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
    expect(api.invoices[0]).toMatchObject({ print_mode: 'unpaid', payments: [], bill_no: null, billing_type: 'without_gst' })
    expect(api.invoices[0].customer.business_name).toBe('Sogat Jutti Store')
    expect(await screen.findByText('Invoice 19 downloaded')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clear cart' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('Bill No')).toHaveValue('20'))
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

  it('Invoices page: lists invoices and records a payment for the remaining amount', async () => {
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const payments: unknown[] = []
    const row = { bill_no: 19, invoice_date: '2026-09-29', business_name: 'Sogat Jutti Store', billing_type: 'without_gst', total: '148000.00', payable: '148000.00', received: '30000.00', status: 'part_paid', version: 2 }
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith('/api/session')) return new Response(JSON.stringify({ authenticated: true, password_required: false }))
        if (url.endsWith('/api/catalog')) return new Response(JSON.stringify(catalog))
        if (url.endsWith('/api/invoice-settings')) return settingsResponse(true)
        if (url.endsWith('/api/calculate')) return new Response(JSON.stringify(quoteFor(100)))
        if (url.includes('/api/invoices?')) return new Response(JSON.stringify({ invoices: [row], total: 1, limit: 25, offset: 0 }))
        if (url.endsWith('/api/invoices/19/payments')) {
          payments.push(JSON.parse(String(init?.body)))
          return pdfResponse(19, 'paid', 'Invoice_19_Sogat-Jutti-Store_Paid.pdf')
        }
        throw new Error(`unexpected ${url}`)
      }),
    )
    const user = setup()
    renderApp()
    await user.click(await screen.findByRole('button', { name: 'Invoices' }))
    expect(await screen.findByText('Sogat Jutti Store')).toBeInTheDocument()
    expect(screen.getByText('Part-paid')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Record payment for invoice 19' }))
    const dialog = await screen.findByRole('dialog', { name: /Record payment/ })
    expect(within(dialog).getByLabelText('Amount received (₹)')).toHaveValue('118000')
    expect(within(dialog).queryByRole('button', { name: /Add another payment/ })).not.toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Record and download' }))
    await waitFor(() => expect(downloads).toEqual(['Invoice_19_Sogat-Jutti-Store_Paid.pdf']))
    expect(payments).toEqual([{ amount: '118000', date: todayIST(), mode: 'upi', note: null }])
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
