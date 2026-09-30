// BRD-tier-slider-back-nav section 11, slider tests S1-S14.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { readFileSync } from 'node:fs'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import type { CalculateRequest, QuoteResponse, TierSchedule } from './api/types'
import { TierSlider, type ServerTier } from './components/TierSlider'
import { positionOf, segments, tierAt } from './lib/tierSlider'
import { C1, CUSTOM_SCHEDULE, OUTDOOR_SCHEDULE, RIGID_SCHEDULE, STICKER_SCHEDULE, T1, T5, catalog, withSchedule } from './test/fixtures'

const WIDTH = 1000
let rectWidth = WIDTH

beforeEach(() => {
  rectWidth = WIDTH
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(
    () => ({ left: 0, top: 0, right: rectWidth, bottom: 44, width: rectWidth, height: 44, x: 0, y: 0, toJSON: () => ({}) }) as DOMRect,
  )
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

/** The slider with a real quantity state, as the calculator uses it. */
function Harness({ schedule, start, server, onQty }: { schedule: TierSchedule; start: number; server?: ServerTier; onQty?: (n: number) => void }) {
  const [qty, setQty] = useState(start)
  return (
    <>
      <output data-testid="qty">{qty}</output>
      <TierSlider
        schedule={schedule}
        quantity={qty}
        unit="box"
        onChange={(n) => {
          setQty(n)
          onQty?.(n)
        }}
        server={server}
      />
    </>
  )
}

const slider = () => screen.getByRole('slider')
const chip = () => screen.getByTestId('tier-chip')
const dot = (q: number) => screen.getByTestId(`tier-dot-${q}`)
const x = (q: number, s: TierSchedule = RIGID_SCHEDULE) => positionOf(q, segments(s)) * WIDTH
const leftOf = (el: HTMLElement) => parseFloat(el.style.left)

describe('tier slider', () => {
  it('S1: a marker for every breakpoint, labelled with quantity and unit price', () => {
    render(<Harness schedule={RIGID_SCHEDULE} start={100} />)
    for (const [q, price] of [['100', '₹105'], ['250', '₹75'], ['500', '₹55'], ['1,000', '₹45'], ['2,000', '₹40']]) {
      const marker = screen.getByRole('button', { name: new RegExp(`^${q} or more: ${price} each`) })
      expect(marker).toHaveTextContent(`${q}${price}`)
    }
  })

  it('S2: at 350 the chip shows the tier and the next break, and 500 is the highlighted marker', () => {
    render(<Harness schedule={RIGID_SCHEDULE} start={350} />)
    expect(chip()).toHaveTextContent('350 boxes · ₹75 each')
    expect(chip()).toHaveTextContent('Add 150 more → ₹55 each')
    expect(dot(500)).toHaveAttribute('data-state', 'next')
    expect(dot(250)).toHaveAttribute('data-state', 'passed')
    expect(dot(1000)).toHaveAttribute('data-state', 'later')
    expect(screen.getByRole('button', { name: /^500 or more: ₹55 each, next price break/ })).toBeInTheDocument()
  })

  it('S3, S4: the overpay zone starts at 367, where the next marker pulses', () => {
    const { rerender } = render(<TierSlider schedule={RIGID_SCHEDULE} quantity={366} unit="box" onChange={() => {}} />)
    expect(dot(500)).not.toHaveAttribute('data-pulse')
    expect(chip().className).toContain('border-cyan')
    for (const q of [367, 450]) {
      rerender(<TierSlider schedule={RIGID_SCHEDULE} quantity={q} unit="box" onChange={() => {}} />)
      expect(dot(500)).toHaveAttribute('data-pulse', 'true')
      expect(chip().className).toContain('border-warn')
    }
    // The shaded zone runs from 367 to the end of the 250 tier.
    const zone = screen.getAllByTestId('tier-overpay')[1]
    expect(leftOf(zone)).toBeCloseTo((x(367) / WIDTH) * 100, 2)
    expect(leftOf(zone) + parseFloat(zone.style.width)).toBeCloseTo((x(500) / WIDTH) * 100, 2)
  })

  it('S6: releasing a drag at 493 snaps to 500; a drag released far from a break does not', () => {
    render(<Harness schedule={RIGID_SCHEDULE} start={300} />)
    fireEvent.pointerDown(slider(), { pointerId: 1, button: 0, clientX: x(300) })
    fireEvent.pointerMove(slider(), { pointerId: 1, clientX: x(493) })
    fireEvent.pointerUp(slider(), { pointerId: 1, clientX: x(493) })
    expect(screen.getByTestId('qty')).toHaveTextContent('500')

    fireEvent.pointerDown(slider(), { pointerId: 2, button: 0, clientX: x(500) })
    fireEvent.pointerUp(slider(), { pointerId: 2, clientX: x(700) })
    expect(screen.getByTestId('qty')).toHaveTextContent('700')
  })

  it('FR-A3: tapping a breakpoint sets exactly that quantity', async () => {
    render(<Harness schedule={RIGID_SCHEDULE} start={300} />)
    await userEvent.click(screen.getByRole('button', { name: /^2,000 or more/ }))
    expect(screen.getByTestId('qty')).toHaveTextContent('2000')
    fireEvent.pointerDown(slider(), { pointerId: 3, button: 0, clientX: x(1000) + 8 })
    fireEvent.pointerUp(slider(), { pointerId: 3, clientX: x(1000) + 8 })
    expect(screen.getByTestId('qty')).toHaveTextContent('1000')
  })

  it('S7: 60 sits in the below-minimum segment and is billed as 100', () => {
    render(<TierSlider schedule={RIGID_SCHEDULE} quantity={60} unit="box" onChange={() => {}} />)
    expect(leftOf(screen.getByTestId('tier-thumb'))).toBeLessThan((x(100) / WIDTH) * 100)
    expect(chip()).toHaveTextContent('60 boxes · Billed as 100')
    expect(chip()).toHaveTextContent('₹105 each')
    expect(slider()).toHaveAttribute('aria-valuetext', '60 boxes, billed as 100, ₹105 each, 150 short of the ₹75 tier')
  })

  it('S8: 5,000 pins the thumb at the end, beyond scale, with no "Add n more"', () => {
    render(<TierSlider schedule={RIGID_SCHEDULE} quantity={5000} unit="box" onChange={() => {}} />)
    expect(leftOf(screen.getByTestId('tier-thumb'))).toBe(100)
    expect(chip()).toHaveTextContent('5,000 · beyond scale')
    expect(chip()).not.toHaveTextContent('Add')
    expect(slider()).toHaveAttribute('aria-valuenow', '4000')
    expect(tierAt(5000, RIGID_SCHEDULE).tier.unit_price).toBe('40.00')
  })

  it('S9: sticker sheets end at max_qty; 1,200 is a manual quote', () => {
    render(<TierSlider schedule={STICKER_SCHEDULE} quantity={1200} unit="sheet" onChange={() => {}} />)
    expect(slider()).toHaveAttribute('aria-valuemax', '1000')
    expect(screen.getByText('1,000 max')).toBeInTheDocument()
    expect(chip()).toHaveTextContent('Needs a manual quote')
    expect(chip()).not.toHaveTextContent('Add')
  })

  it('S10: keyboard: Page Up / Down between breaks, Home / End, arrows by one unit', async () => {
    const user = userEvent.setup()
    render(<Harness schedule={RIGID_SCHEDULE} start={350} />)
    expect(slider()).toHaveAttribute('aria-valuetext', '350 boxes, ₹75 each, 150 short of the ₹55 tier')
    slider().focus()
    await user.keyboard('{PageUp}')
    expect(screen.getByTestId('qty')).toHaveTextContent('500')
    await user.keyboard('{PageDown}')
    expect(screen.getByTestId('qty')).toHaveTextContent('250')
    await user.keyboard('{ArrowRight}{ArrowRight}{ArrowLeft}')
    expect(screen.getByTestId('qty')).toHaveTextContent('251')
    await user.keyboard('{Home}')
    expect(screen.getByTestId('qty')).toHaveTextContent('100')
    await user.keyboard('{End}')
    expect(screen.getByTestId('qty')).toHaveTextContent('4000')
    expect(slider()).toHaveAttribute('aria-valuetext', '4,000 boxes, ₹40 each')
    // Keys never snap: one step past a breakpoint stays there.
    await user.keyboard('{PageDown}{ArrowRight}')
    expect(screen.getByTestId('qty')).toHaveTextContent('2001')
  })

  it('S12: outdoor branding is read-only: markers and position, no zone, no chip', () => {
    render(<TierSlider schedule={OUTDOOR_SCHEDULE} quantity={240} unit="sq ft" />)
    expect(screen.queryByRole('slider')).not.toBeInTheDocument()
    expect(screen.getByRole('img', { name: /240 sq ft, ₹35 each/ })).toBeInTheDocument()
    expect(screen.queryByTestId('tier-chip')).not.toBeInTheDocument()
    expect(screen.queryByTestId('tier-overpay')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^101 or more: ₹35/ })).toBeDisabled()
  })

  it('S13: custom sizes show the interpolated tier prices', () => {
    render(<TierSlider schedule={CUSTOM_SCHEDULE} quantity={300} unit="box" onChange={() => {}} />)
    expect(screen.getByRole('button', { name: /^250 or more: ₹88.50 each/ })).toBeInTheDocument()
    expect(chip()).toHaveTextContent('Add 200 more → ₹68.50 each')
  })

  it('S14: at 375 px, labels show prices only and never overlap; the thumb target is 44 px', () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('max-width'), addEventListener() {}, removeEventListener() {} }))
    rectWidth = 343 // a 375 px phone minus the page padding
    render(<TierSlider schedule={STICKER_SCHEDULE} quantity={120} unit="sheet" onChange={() => {}} />)
    const labels = screen.getAllByRole('button', { name: /or more/ })
    expect(labels[0]).toHaveTextContent(/^₹130$/)
    const lefts = labels.map((l) => (leftOf(l) / 100) * rectWidth)
    for (let i = 1; i < lefts.length; i++) expect(lefts[i] - lefts[i - 1]).toBeGreaterThanOrEqual(36)
    expect(screen.getByTestId('tier-thumb').className).toContain('size-11') // 2.75rem = 44 px
    const css = readFileSync('src/index.css', 'utf8')
    expect(css).toMatch(/prefers-reduced-motion: reduce\)[^}]*\{[^}]*animation: none !important/s)
  })

  it('FR-A9 f: a single-tier item shows the slider without markers or chip', () => {
    const single: TierSchedule = { ...RIGID_SCHEDULE, min_qty: 1, slider_max: 2, tiers: [{ qty_from: 1, qty_to: null, unit_price: '900.00', overpay_from: null }] }
    render(<TierSlider schedule={single} quantity={1} unit="roll" onChange={() => {}} />)
    expect(slider()).toBeInTheDocument()
    expect(screen.queryByTestId('tier-chip')).not.toBeInTheDocument()
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('FR-A11: when the server disagrees, the server wins and a dev warning is logged', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    render(<TierSlider schedule={RIGID_SCHEDULE} quantity={450} unit="box" onChange={() => {}} server={{ requested: 450, tierFrom: 500, unitsToNext: 550 }} />)
    expect(warn).toHaveBeenCalled()
    expect(chip()).toHaveTextContent('Add 550 more → ₹45 each')
  })
})

// ---- In the calculator, against the mocked API.

function mockApi(handler: (b: CalculateRequest) => QuoteResponse) {
  const calls: CalculateRequest[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      if (url.endsWith('/api/session')) return new Response(JSON.stringify({ authenticated: true, password_required: false }))
      if (url.endsWith('/api/catalog')) return new Response(JSON.stringify(catalog))
      if (url.endsWith('/api/invoice-settings')) return new Response(JSON.stringify({ enabled: true, storage: true, gst_rate: '0.18', advance_pct: '80' }))
      const body = JSON.parse(String(init?.body)) as CalculateRequest
      calls.push(body)
      return new Response(JSON.stringify(handler(body)))
    }),
  )
  return calls
}

function quoteAt(b: CalculateRequest): QuoteResponse {
  if (b.custom_dimensions) return withSchedule(C1, CUSTOM_SCHEDULE)
  const base = b.quantity >= 367 && b.quantity < 500 ? T5 : T1
  if (base.status !== 'success') throw new Error('fixture')
  const r = withSchedule(base) as Extract<QuoteResponse, { status: 'success' }>
  const t = tierAt(b.quantity, RIGID_SCHEDULE)
  return {
    ...r,
    data: {
      ...r.data,
      quantity: { ...r.data.quantity, requested: b.quantity, billed: t.billed },
      pricing: {
        ...r.data.pricing,
        tier_applied: { qty_from: t.tier.qty_from, label: `${t.tier.qty_from} qty`, range: '' },
        next_tier: t.next ? { qty_from: t.next.tier.qty_from, units_to_next: t.next.unitsToNext, unit_price: t.next.tier.unit_price } : null,
      },
    },
  }
}

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

describe('tier slider in the calculator', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    localStorage.clear()
  })
  const quote = () => screen.getByRole('region', { name: 'Quote' })

  it('S2, S4, S5: typed quantity moves the thumb; the banner shows in the zone; Use 500 lands on the marker', async () => {
    mockApi(quoteAt)
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp()
    const qty = await screen.findByLabelText(/^Quantity/)
    await user.clear(qty)
    await user.type(qty, '350')
    await act(() => vi.advanceTimersByTimeAsync(300))
    await waitFor(() => expect(within(quote()).getByTestId('grand-total')).toHaveTextContent('₹30,975.00'))
    expect(within(quote()).getByText('₹26,250.00')).toBeInTheDocument()
    expect(chip()).toHaveTextContent('Add 150 more → ₹55 each')

    await user.clear(qty)
    await user.type(qty, '450')
    expect(chip()).toHaveTextContent('450 boxes · ₹75 each') // before any response
    await act(() => vi.advanceTimersByTimeAsync(300))
    expect(await within(quote()).findByText(/cost ₹6,250 less/)).toHaveTextContent('500 boxes cost ₹6,250 less')
    expect(dot(500)).toHaveAttribute('data-pulse', 'true')

    await user.click(within(quote()).getByRole('button', { name: 'Use 500' }))
    expect(qty).toHaveValue('500')
    expect(leftOf(screen.getByTestId('tier-thumb'))).toBeCloseTo(leftOf(dot(500)), 5)
  })

  it('S11: dragging 100 to 2,000 for 3 s updates the chip every frame and quotes once, after the pause', async () => {
    const calls = mockApi(quoteAt)
    renderApp()
    await screen.findByRole('slider')
    await act(() => vi.advanceTimersByTimeAsync(300))
    const before = calls.length
    const seen = new Set<string>()
    fireEvent.pointerDown(slider(), { pointerId: 9, button: 0, clientX: x(100) })
    for (let t = 0; t <= 3000; t += 16) {
      const clientX = x(100) + ((x(2000) - x(100)) * t) / 3000
      fireEvent.pointerMove(slider(), { pointerId: 9, clientX })
      await act(() => vi.advanceTimersByTimeAsync(16))
      seen.add(chip().textContent ?? '')
    }
    expect(seen.size).toBeGreaterThan(100) // the chip changed on nearly every frame
    expect(calls.length).toBe(before) // nothing sent while moving
    fireEvent.pointerUp(slider(), { pointerId: 9, clientX: x(2000) })
    expect(screen.getByLabelText(/^Quantity/)).toHaveValue('2000')
    await act(() => vi.advanceTimersByTimeAsync(400))
    expect(calls.length).toBe(before + 1)
    expect(calls.at(-1)?.quantity).toBe(2000)
  })

  it('S7: typing 60 bills as 100 and the chip says so', async () => {
    mockApi(quoteAt)
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    renderApp()
    const qty = await screen.findByLabelText(/^Quantity/)
    await act(() => vi.advanceTimersByTimeAsync(300))
    await user.clear(qty)
    await user.type(qty, '60')
    expect(chip()).toHaveTextContent('60 boxes · Billed as 100')
  })

  it('S13: a custom size shows the custom tier prices', async () => {
    mockApi(quoteAt)
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
    window.history.replaceState(null, '', '/?product=rigid_boxes&opt1=top-bottom&custom=3.5x3.5x2in&qty=300')
    renderApp()
    await screen.findByLabelText('Length')
    await act(() => vi.advanceTimersByTimeAsync(300))
    expect(await screen.findByTestId('tier-chip')).toHaveTextContent('Add 200 more → ₹68.50 each')
    // A new size hides the old prices until its own quote arrives.
    await user.type(screen.getByLabelText('Length'), '1')
    expect(screen.queryByTestId('tier-slider')).not.toBeInTheDocument()
  })
})
