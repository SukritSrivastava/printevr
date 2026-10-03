// BRD-tier-slider-back-nav section 11, navigation tests N1-N9 (N10 is the production-build check).
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { CartLine, InvoiceCreate, InvoiceLineDraft } from './api/invoiceTypes'
import type { CalculateRequest, QuoteResponse } from './api/types'
import { STORAGE_KEY } from './cart/CartProvider'
import { fromSearch, slug, toSearch } from './lib/calcUrl'
import { CUSTOM_SIZE } from './lib/selection'
import { C1, T1, catalog } from './test/fixtures'

const RIGID = 'rigid_boxes/3x3x2-in/top-bottom'
const rigid = catalog.categories[0].products[0]

const draft = (quantity: number): InvoiceLineDraft => ({
  source: 'catalogue',
  title: 'Customised rigid box printing',
  specs: [{ label: 'Size', value: '3*3*2 in (LxWxH)', emphasis: true }],
  customisations: [],
  quantity,
  unit_label: 'boxes',
  middle: { kind: 'none' },
  catalogue_unit_price: '75.00',
  unit_price: '75.00',
  warnings: [],
})

function quoteFor(b: CalculateRequest): QuoteResponse {
  if (b.custom_dimensions) return C1
  if (T1.status !== 'success') throw new Error('fixture')
  const quantity = { ...T1.data.quantity, requested: b.quantity, billed: b.quantity }
  return { ...T1, data: { ...T1.data, quantity, invoice_lines: [draft(b.quantity)] } }
}

interface Api {
  calls: CalculateRequest[]
  invoices: InvoiceCreate[]
  billNoCalls: number
}

function mockApi(): Api {
  const api: Api = { calls: [], invoices: [], billNoCalls: 0 }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/session')) return new Response(JSON.stringify({ authenticated: true, password_required: false }))
      if (url.endsWith('/api/catalog')) return new Response(JSON.stringify(catalog))
      if (url.endsWith('/api/invoice-settings')) return new Response(JSON.stringify({ enabled: true, storage: true, gst_rate: '0.18', advance_pct: '80' }))
      if (url.endsWith('/api/calculate')) {
        const body = JSON.parse(String(init?.body)) as CalculateRequest
        api.calls.push(body)
        return new Response(JSON.stringify(quoteFor(body)))
      }
      if (url.endsWith('/api/invoices/next-bill-no')) {
        api.billNoCalls++
        return new Response(JSON.stringify({ next_bill_no: 19 + api.invoices.length, gst_rate: '0.18', advance_pct: '80' }))
      }
      if (url.endsWith('/api/invoices') && init?.method === 'POST') {
        api.invoices.push(JSON.parse(String(init.body)) as InvoiceCreate)
        return new Response(new Blob(['%PDF-1.4 test']), {
          status: 201,
          headers: { 'Content-Disposition': 'attachment; filename="Invoice_19_X_Paid.pdf"', 'X-Bill-No': '19', 'X-Invoice-Status': 'paid' },
        })
      }
      if (url.includes('/api/invoices?')) return new Response(JSON.stringify({ invoices: [], total: 0, limit: 25, offset: 0 }))
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

const setup = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
const wait = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms))
const back = () => act(async () => {
  window.history.back()
  await vi.advanceTimersByTimeAsync(50)
})
const forward = () => act(async () => {
  window.history.forward()
  await vi.advanceTimersByTimeAsync(50)
})
const tab = (name: RegExp) => screen.findByRole('button', { name })
const cartLine = (quantity = 450): CartLine => ({
  ...draft(quantity),
  id: 'line-1',
  parent_id: null,
  calc_request: { product_id: 'rigid_boxes', item_id: RIGID, options: {}, custom_dimensions: null, quantity, addons: [], billing_type: 'gst' },
})

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

describe('calculator URL', () => {
  it('round-trips a standard item, a custom size and add-ons', () => {
    const std = fromSearch(`?product=rigid_boxes&item=${RIGID}&qty=450&billing=gst`, catalog)
    expect(std.notice).toBeNull()
    expect(std.config.selection).toEqual({ size: '3 × 3 × 2 in', option_1: 'Top-Bottom', option_2: null })
    expect(toSearch(std.config, rigid)).toBe(`?product=rigid_boxes&item=${RIGID}&qty=450&billing=gst`)

    const custom = fromSearch('?product=rigid_boxes&opt1=top-bottom&custom=3.5x3.5x2in&qty=300', catalog)
    expect(custom.notice).toBeNull()
    expect(custom.config.selection).toEqual({ size: CUSTOM_SIZE, option_1: 'Top-Bottom', option_2: null })
    expect(custom.config.dims).toMatchObject({ length: '3.5', width: '3.5', height: '2' })
    expect(toSearch(custom.config, rigid)).toBe('?product=rigid_boxes&opt1=top-bottom&custom=3.5x3.5x2in&qty=300&billing=gst')
    expect(slug('Magnetic / Slider')).toBe('magnetic-slider')
  })

  it('falls back to defaults, with a notice, for values that no longer exist (N8)', () => {
    const r = fromSearch('?product=rigid_boxes&item=rigid_boxes/99x99x99-in/top-bottom&qty=abc&addons=gold', catalog)
    expect(r.config.productId).toBe('rigid_boxes')
    expect(r.config.selection.size).toBe('3 × 3 × 2 in')
    expect(r.config.qty).toBe('100')
    expect(r.notice).toMatch(/item "rigid_boxes\/99x99x99-in\/top-bottom"/)
    expect(r.notice).toMatch(/quantity "abc"/)
    expect(fromSearch('?product=gone&custom=1x2', catalog).notice).toMatch(/product "gone"/)
  })
})

describe('navigation', () => {
  it('N1, N2: Back from the cart restores the calculator at 450; Forward reopens the cart', async () => {
    savedCartWith(cartLine())
    mockApi()
    const user = setup()
    renderApp()
    const qty = await screen.findByLabelText(/Quantity/)
    await user.clear(qty)
    await user.type(qty, '450')
    await wait(400)
    expect(window.location.search).toContain('qty=450')
    await user.click(await tab(/^Cart/))
    expect(window.location.pathname).toBe('/cart')
    expect(await screen.findByRole('heading', { name: 'Cart' })).toBeInTheDocument()
    expect(document.title).toBe('Cart · Printevr')

    await back()
    expect(window.location.pathname).toBe('/')
    expect(window.location.search).toContain(`item=${RIGID}`)
    expect(screen.getByLabelText(/Quantity/)).toHaveValue('450')
    expect(document.title).toBe('Calculator · Printevr')

    await forward()
    expect(window.location.pathname).toBe('/cart')
    expect(await screen.findAllByRole('article', { name: /Line 1/ })).toHaveLength(1)
  })

  it('keeps an edit made just before leaving, even inside the 300 ms URL delay', async () => {
    mockApi()
    const user = setup()
    renderApp()
    const qty = await screen.findByLabelText(/Quantity/)
    await wait(400)
    await user.clear(qty)
    await user.type(qty, '640')
    await user.click(await tab(/^Cart/)) // well inside 300 ms
    await back()
    expect(screen.getByLabelText(/Quantity/)).toHaveValue('640')
    expect(window.location.search).toContain('qty=640')
  })

  it('N3: refreshing /cart and /checkout keeps the screen and the cart', async () => {
    savedCartWith(cartLine())
    mockApi()
    window.history.replaceState(null, '', '/cart')
    const first = renderApp()
    expect(await screen.findByRole('heading', { name: 'Cart' })).toBeInTheDocument()
    expect(screen.getAllByRole('article')).toHaveLength(1)
    first.unmount()

    window.history.replaceState(null, '', '/checkout')
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Cart' })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/cart')
    expect(screen.getByRole('heading', { name: 'Ship To' })).toBeInTheDocument()
  })

  it('N4: a pasted calculator link opens that configuration and quotes it', async () => {
    const api = mockApi()
    window.history.replaceState(null, '', '/?product=rigid_boxes&opt1=top-bottom&custom=3.5x3.5x2in&qty=300')
    renderApp()
    expect(await screen.findByLabelText('Length')).toHaveValue('3.5')
    expect(screen.getByLabelText('Height')).toHaveValue('2')
    expect(screen.getByLabelText(/Quantity/)).toHaveValue('300')
    await wait(400)
    await waitFor(() => expect(within(screen.getByRole('region', { name: 'Quote' })).getByTestId('grand-total')).toHaveTextContent('₹31,329.00'))
    expect(api.calls.at(-1)).toMatchObject({ item_id: null, options: { option_1: 'Top-Bottom' }, custom_dimensions: { length: 3.5, width: 3.5, height: 2, unit: 'in' }, quantity: 300 })
  })

  it('N5: twenty quantity changes, then one Back, leaves the calculator', async () => {
    mockApi()
    const user = setup()
    window.history.replaceState(null, '', '/cart')
    renderApp()
    await user.click(await tab(/^Calculator/))
    const qty = await screen.findByLabelText(/Quantity/)
    for (let i = 0; i < 20; i++) {
      await user.click(screen.getByRole('button', { name: '50 more' }))
      await wait(i % 2 ? 350 : 20)
    }
    expect(screen.getByLabelText(/Quantity/)).toHaveValue('1100')
    expect(window.location.search).toContain('qty=1100')
    await back()
    expect(window.location.pathname).toBe('/cart')
    expect(qty).toBeInTheDocument() // still mounted, hidden
  })

  it('N6: Back and Forward after Print (Paid) never print again or change the cart', async () => {
    savedCartWith(cartLine(), { business_name: 'Sogat Jutti Store', address: 'Mohali', phone: '+91 95010 60618', billing_type: 'non_gst' })
    sessionStorage.setItem('printevr.staff.token', '9999999999.sig')
    const api = mockApi()
    const user = setup()
    renderApp()
    await user.click(await tab(/^Cart/))
    await user.click(await screen.findByRole('button', { name: 'Print (Paid)' }))
    await user.click(await screen.findByRole('button', { name: 'Confirm and download' }))
    await waitFor(() => expect(downloads).toHaveLength(1))
    const saved = localStorage.getItem(STORAGE_KEY)
    const billNoCalls = api.billNoCalls

    await back()
    await forward()
    await back()
    await forward()
    await wait(400)
    expect(window.location.pathname).toBe('/cart')
    expect(api.invoices).toHaveLength(1)
    expect(downloads).toHaveLength(1)
    expect(JSON.parse(localStorage.getItem(STORAGE_KEY)!).lines).toEqual(JSON.parse(saved!).lines)
    // Re-opening the cart only reads the next number; nothing is allocated.
    expect(api.billNoCalls).toBeGreaterThanOrEqual(billNoCalls)
  })

  it('N7: an unknown path shows Page not found with a link to the calculator', async () => {
    mockApi()
    const user = setup()
    window.history.replaceState(null, '', '/does-not-exist')
    renderApp()
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(document.title).toBe('Page not found · Printevr')
    await user.click(screen.getByRole('link', { name: 'Go to the calculator' }))
    expect(window.location.pathname).toBe('/')
    expect(screen.getByLabelText(/Quantity/)).toBeVisible()
  })

  it('N8: an item that does not exist opens the default calculator with a notice', async () => {
    mockApi()
    window.history.replaceState(null, '', '/?product=rigid_boxes&item=rigid_boxes/99x99x99-in/top-bottom&qty=450')
    renderApp()
    expect(await screen.findByText(/doesn't recognise \(item "rigid_boxes\/99x99x99-in\/top-bottom"\)/)).toBeInTheDocument()
    expect(screen.getByLabelText('Size')).toHaveValue('3 × 3 × 2 in')
    expect(screen.getByLabelText(/Quantity/)).toHaveValue('450')
    await wait(400)
    expect(window.location.search).toContain(`item=${RIGID}`)
  })

  it('N9: "Go to calculator" goes back when the calculator is the previous entry, else opens it', async () => {
    mockApi()
    const user = setup()
    const first = renderApp()
    await screen.findByLabelText(/Quantity/)
    await wait(400)
    await user.click(await tab(/^Cart/))
    const idx = () => (window.history.state as { idx: number }).idx
    expect(idx()).toBe(1)
    await user.click(await screen.findByRole('button', { name: 'Go to calculator' }))
    await wait(50)
    expect(window.location.pathname).toBe('/')
    expect(idx()).toBe(0) // went back, did not stack a new entry

    // Opened straight on /cart: there is nothing to go back to inside the app.
    first.unmount()
    window.history.replaceState(null, '', '/cart')
    renderApp()
    await user.click(await screen.findByRole('button', { name: 'Go to calculator' }))
    expect(window.location.pathname).toBe('/')
    expect(idx()).toBe(1) // a new entry after /cart
  })
})

function savedCartWith(line: CartLine, checkout: Record<string, string> = {}) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 2, saved_at: Date.now(), lines: [line], checkout }))
}
