// Customer details in the browser: cleared on Sign out and after the retention period, in an
// open page too; cart lines stay. API mocked.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { CartLine } from './api/invoiceTypes'
import { STORAGE_KEY } from './cart/CartProvider'
import { CUSTOMER_TTL_MS } from './cart/storage'
import { catalog } from './test/fixtures'

const TOKEN_KEY = 'printevr.staff.token'
const SHIP_TO = { business_name: 'Sogat Jutti Store', address: 'Sector 67, Mohali', phone: '+91 95010 60618', billing_type: 'non_gst' }

const line = {
  id: 'line-1',
  source: 'custom',
  parent_id: null,
  calc_request: null,
  title: 'Customised rigid box printing',
  specs: [{ label: 'Size', value: '3*3*2 in', emphasis: true }],
  customisations: [],
  quantity: 100,
  unit_label: 'boxes',
  middle: { kind: 'none' },
  catalogue_unit_price: null,
  unit_price: '75.00',
  warnings: [],
} as unknown as CartLine

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status })

function mockApi() {
  const calls: string[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      calls.push(url)
      if (url.endsWith('/api/session')) return json({ authenticated: !calls.some((u) => u.endsWith('/api/logout')), password_required: true })
      if (url.endsWith('/api/logout')) return json({ status: 'ok' })
      if (url.endsWith('/api/catalog')) return json(catalog)
      if (url.endsWith('/api/invoice-settings')) {
        return json({ enabled: true, storage: false, staff_passcode: true, gst_slab_groups: [], seller_state_code: '', gst_field_defaults: {}, hsn_codes: {}, advance_pct: '80', print_payment_details: false })
      }
      throw new Error(`unexpected ${url}`)
    }),
  )
  return calls
}

const seed = (savedAt: number) =>
  localStorage.setItem(STORAGE_KEY, JSON.stringify({ version: 2, saved_at: savedAt, lines: [line], checkout: SHIP_TO }))
const saved = () => JSON.parse(localStorage.getItem(STORAGE_KEY)!)

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

const setup = () => userEvent.setup({ advanceTimers: vi.advanceTimersByTime })

async function openCart(user: ReturnType<typeof setup>) {
  await user.click(await screen.findByRole('button', { name: /^Cart/ }))
  await screen.findByRole('heading', { name: 'Cart' })
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  localStorage.clear()
  sessionStorage.clear()
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('customer details in browser storage', () => {
  it('Sign out clears them and the staff token; the cart lines stay', async () => {
    seed(Date.now())
    sessionStorage.setItem(TOKEN_KEY, '9999999999.sig')
    const calls = mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    expect(screen.getByLabelText('Business name')).toHaveValue('Sogat Jutti Store')

    await user.click(screen.getByRole('button', { name: 'Sign out' }))
    await waitFor(() => expect(calls.some((u) => u.endsWith('/api/logout'))).toBe(true))
    await screen.findByLabelText('Password')
    expect(saved().checkout).toMatchObject({ business_name: '', address: '', phone: '' })
    expect(saved().checkout.billing_type).toBe('non_gst')
    expect(saved().lines).toEqual([line])
    expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull()
    expect(JSON.stringify({ ...localStorage })).not.toContain('Sogat')
  })

  it('an open page clears them once the retention period has passed', async () => {
    seed(Date.now())
    mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    expect(screen.getByLabelText('Phone')).toHaveValue('+91 95010 60618')

    await act(async () => {
      vi.advanceTimersByTime(CUSTOMER_TTL_MS + 2 * 60 * 1000)
    })
    await waitFor(() => expect(screen.getByLabelText('Business name')).toHaveValue(''))
    expect(screen.getByLabelText('Phone')).toHaveValue('')
    expect(saved().checkout.business_name).toBe('')
    expect(saved().lines).toEqual([line])
  })

  it('changing only the lines does not restart the period; editing the form does', async () => {
    const HOUR = 60 * 60 * 1000
    const second = { ...line, id: 'line-2', title: 'Second item' } as CartLine
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: 2, saved_at: Date.now() - CUSTOMER_TTL_MS + HOUR, lines: [line, second], checkout: SHIP_TO }),
    )
    mockApi()
    const user = setup()
    const view = renderApp()
    await openCart(user)
    await user.click(screen.getByRole('button', { name: 'Move line 1 down' }))
    await act(async () => {
      vi.advanceTimersByTime(2 * HOUR)
    })
    await waitFor(() => expect(screen.getByLabelText('Business name')).toHaveValue(''))
    expect(saved().lines.map((l: CartLine) => l.id)).toEqual(['line-2', 'line-1'])
    view.unmount()

    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: 2, saved_at: Date.now() - CUSTOMER_TTL_MS + HOUR, lines: [line], checkout: SHIP_TO }),
    )
    renderApp()
    await openCart(user)
    await user.type(screen.getByLabelText('Address'), ' 2')
    await act(async () => {
      vi.advanceTimersByTime(2 * HOUR)
    })
    expect(screen.getByLabelText('Business name')).toHaveValue('Sogat Jutti Store')
    expect(saved().checkout.address).toBe('Sector 67, Mohali 2')
  })

  it('a page opened after the retention period starts without them', async () => {
    seed(Date.now() - CUSTOMER_TTL_MS - 60 * 1000)
    mockApi()
    const user = setup()
    renderApp()
    await openCart(user)
    expect(screen.getByLabelText('Business name')).toHaveValue('')
    expect(screen.getByText('Customised rigid box printing', { exact: false })).toBeInTheDocument()
    expect(saved().checkout.address).toBe('')
  })
})
