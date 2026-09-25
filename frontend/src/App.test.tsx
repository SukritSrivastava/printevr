import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { CalculateRequest, QuoteResponse } from './api/types'
import { money, qtyWithUnit } from './lib/format'
import { quoteText } from './lib/quoteText'
import { dimensionError, normalize } from './lib/selection'
import { C1, T1, T5, catalog } from './test/fixtures'

type Handler = (body: CalculateRequest) => QuoteResponse

function mockApi(handler: Handler) {
  const calls: CalculateRequest[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/catalog')) return new Response(JSON.stringify(catalog))
      const body = JSON.parse(String(init?.body)) as CalculateRequest
      calls.push(body)
      return new Response(JSON.stringify(handler(body)))
    }),
  )
  return calls
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

const quote = () => screen.getByRole('region', { name: 'Quote' })

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('money format', () => {
  it('uses Indian grouping', () => {
    expect(money('169920.00')).toBe('₹1,69,920.00')
    expect(qtyWithUnit(1200, 'box')).toBe('1,200 boxes')
  })
})

describe('selection', () => {
  it('drops options that do not exist for the size', () => {
    const product = catalog.categories[0].products[0]
    const sel = normalize(product, { size: '5 × 3 × 2 in', option_1: 'Magnetic / Slider', option_2: null })
    expect(sel.option_1).toBe('Top-Bottom')
  })
  it('validates custom dimensions like the server', () => {
    expect(dimensionError('0', 'in')).toBe('Must be above 0')
    expect(dimensionError('61', 'in')).toBe('At most 60 in')
    expect(dimensionError('152', 'cm')).toBeNull()
    expect(dimensionError('1.234', 'in')).toBe('Up to 2 decimals')
  })
})

describe('quote desk', () => {
  it('T1 on screen: 350 boxes', async () => {
    const calls = mockApi(() => T1)
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp()
    const qty = await screen.findByLabelText(/Quantity/)
    await user.clear(qty)
    await user.type(qty, '350')
    await act(() => vi.advanceTimersByTimeAsync(300))
    await waitFor(() => expect(within(quote()).getByTestId('grand-total')).toHaveTextContent('₹30,975.00'))
    expect(within(quote()).getByText('₹75.00')).toBeInTheDocument()
    expect(within(quote()).getByText(/Add 150 more to drop to/)).toHaveTextContent('₹55')
    // Debounced: typing "350" sends one request for 350, not one per keystroke.
    expect(calls.filter((c) => c.quantity !== 100).map((c) => c.quantity)).toEqual([350])
  })

  it('T5 on screen: better option changes quantity only when clicked', async () => {
    const calls = mockApi((b) => (b.quantity === 450 ? T5 : T1))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp()
    const qty = await screen.findByLabelText(/Quantity/)
    await user.clear(qty)
    await user.type(qty, '450')
    await act(() => vi.advanceTimersByTimeAsync(300))
    const banner = await within(quote()).findByText(/cost ₹6,250 less/)
    expect(banner).toHaveTextContent('500 boxes cost ₹6,250 less')
    expect(qty).toHaveValue('450')
    await user.click(within(quote()).getByRole('button', { name: 'Use 500' }))
    expect(qty).toHaveValue('500')
    await act(() => vi.advanceTimersByTimeAsync(300))
    await waitFor(() => expect(calls.at(-1)?.quantity).toBe(500))
  })

  it('C1 on screen: custom size names its anchors', async () => {
    const calls = mockApi((b) => (b.custom_dimensions ? C1 : T1))
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp()
    await user.selectOptions(await screen.findByLabelText('Size'), 'Custom size…')
    await user.type(screen.getByLabelText('Length'), '3.5')
    await user.type(screen.getByLabelText('Width'), '3.5')
    await user.type(screen.getByLabelText('Height'), '2')
    const qty = screen.getByLabelText(/Quantity/)
    await user.clear(qty)
    await user.type(qty, '300')
    await act(() => vi.advanceTimersByTimeAsync(300))
    await waitFor(() => expect(within(quote()).getByTestId('grand-total')).toHaveTextContent('₹31,329.00'))
    expect(within(quote()).getByText(/Priced between 3 × 3 × 2 and 5 × 3 × 2/)).toBeInTheDocument()
    expect(within(quote()).getByText(/final price confirmed after design review/)).toBeInTheDocument()
    expect(calls.at(-1)).toMatchObject({
      product_id: 'rigid_boxes',
      item_id: null,
      options: { option_1: 'Top-Bottom' },
      custom_dimensions: { length: 3.5, width: 3.5, height: 2, unit: 'in' },
      quantity: 300,
    })
  })

  it('shows a manual quote instead of a receipt', async () => {
    mockApi(() => ({
      status: 'manual_quote',
      reason: 'CUSTOM_OUT_OF_RANGE',
      message: 'Custom size is larger than the largest standard size',
      data: { product: { id: 'rigid_boxes', name: 'Rigid Boxes', description: 'custom' } },
    }))
    renderApp()
    await act(() => vi.advanceTimersByTimeAsync(300))
    expect(await within(quote()).findByText('Needs a manual quote')).toBeInTheDocument()
  })

  it("keeps the form filled when the server can't be reached", async () => {
    let up = true
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) => {
        if (url.endsWith('/api/catalog')) return new Response(JSON.stringify(catalog))
        if (!up) throw new TypeError('Failed to fetch')
        return new Response(JSON.stringify(T1))
      }),
    )
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp()
    const qty = await screen.findByLabelText(/Quantity/)
    up = false
    await user.clear(qty)
    await user.type(qty, '350')
    await act(() => vi.advanceTimersByTimeAsync(300))
    expect(await within(quote()).findByText("Can't reach the pricing server")).toBeInTheDocument()
    expect(qty).toHaveValue('350')
    up = true
    await user.click(within(quote()).getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(within(quote()).getByTestId('grand-total')).toHaveTextContent('₹30,975.00'))
  })
})

describe('copy quote', () => {
  it('builds plain text with the key lines', () => {
    const text = quoteText(T1.status === 'success' ? T1.data : (null as never))
    expect(text).toContain('Quantity: 350 boxes')
    expect(text).toContain('Unit price: ₹75.00 per box')
    expect(text).toContain('GST 18%: ₹4,725.00')
    expect(text).toContain('*Total: ₹30,975.00*')
    expect(text).toContain('Production time: 10-12 days')
  })
})
