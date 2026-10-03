import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { CalculateRequest, Catalog, CatalogProduct } from './api/types'
import { quantityError } from './lib/selection'
import { T1, catalog } from './test/fixtures'

// The three mailer bags need at least 300 (config/products.yaml min_qty: 300, below_min_policy: block).
const bagBreakpoints = [300, 500, 1000, 2500].map((q) => ({ qty_from: q, label: `${q} pcs` }))
const bag = (id: string, name: string): CatalogProduct => ({
  ...catalog.categories[0].products[0],
  id,
  name,
  sale_unit: 'bag',
  custom_dims: 'flat',
  anchor_match: [],
  option_labels: {},
  min_qty: 300,
  below_min_policy: 'block',
  breakpoints: bagBreakpoints,
  items: [{ id: `${id}/8x10-in`, size: '8 × 10 in', option_1: null, option_2: null, breakpoints: bagBreakpoints, production_time: '7 days', has_sample: false }],
})
const BAGS = [
  bag('courier_bags', 'Customised & Coloured Courier Bags'),
  bag('frosted_bags', 'Customised & Coloured Frosted Bags'),
  bag('kraft_mailer_bags', 'Customised & Coloured Kraft Mailer Bags'),
]

function mockApi(products: CatalogProduct[]) {
  const calls: CalculateRequest[] = []
  const bagCatalog: Catalog = { ...catalog, categories: [{ name: 'Mailer Bags', products }] }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/session')) return new Response(JSON.stringify({ authenticated: true, password_required: true }))
      if (url.endsWith('/api/catalog')) return new Response(JSON.stringify(bagCatalog))
      calls.push(JSON.parse(String(init?.body)) as CalculateRequest)
      return new Response(JSON.stringify(T1))
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

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('300 minimum on the mailer bags', () => {
  it('quantityError refuses less than a hard minimum, like the server', () => {
    for (const p of BAGS) {
      expect(quantityError('299', p.custom_dims, p.sale_unit, p)).toBe('Minimum order is 300 bags')
      expect(quantityError('200', p.custom_dims, p.sale_unit, p)).toBe('Minimum order is 300 bags')
      expect(quantityError('300', p.custom_dims, p.sale_unit, p)).toBeNull()
    }
    // Products billed at their minimum (rigid boxes) still accept less: the server bills the minimum.
    const rigid = catalog.categories[0].products[0]
    expect(quantityError('50', rigid.custom_dims, rigid.sale_unit, rigid)).toBeNull()
  })

  it.each(BAGS)('$name starts at 300, shows the error below it and never asks the server for less', async (product) => {
    const calls = mockApi([product])
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp()
    const qty = (await screen.findByLabelText(/Quantity/)) as HTMLInputElement
    expect(qty.value).toBe('300')

    // The − button stops at the minimum.
    fireEvent.click(screen.getByRole('button', { name: '50 fewer' }))
    expect(qty.value).toBe('300')

    await user.clear(qty)
    await user.type(qty, '250')
    await act(() => vi.advanceTimersByTimeAsync(400))
    expect(screen.getByText('Minimum order is 300 bags', { selector: '#quantity-help' })).toBeInTheDocument()
    expect(qty).toHaveAttribute('aria-invalid', 'true')
    expect(calls.every((c) => c.quantity >= 300)).toBe(true)

    await user.clear(qty)
    await user.type(qty, '300')
    await act(() => vi.advanceTimersByTimeAsync(400))
    expect(qty).not.toHaveAttribute('aria-invalid')
    expect(calls.at(-1)?.quantity).toBe(300)
  })
})
