// Designer Assignment tab: jobs board, live refresh, optimistic saves, IST times. API mocked.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Designer, Job } from './api/designers'
import { DesignersPage } from './components/designers/DesignersPage'
import { StaffProvider } from './components/StaffLoginDialog'
import { ToastProvider } from './components/Toast'
import { age, istDateTime, REFRESH_MS, timeAgo } from './lib/designers'

const DESIGNERS: Designer[] = [
  { id: 1, name: 'Namit', active: true, rotation_order: 1 },
  { id: 2, name: 'Ajendra', active: true, rotation_order: 2 },
]

const job = (id: number, designer: Designer, changes: Partial<Job> = {}): Job => ({
  id,
  series: 'non_gst',
  bill_no: 18 + id,
  customer_name: `Customer ${id}`,
  invoice_total: '26250.00',
  items_summary: 'Customised rigid box printing ×350',
  designer_id: designer.id,
  designer_name: designer.name,
  assigned_at: '2026-10-03T11:05:00+00:00',
  status: 1,
  status_label: 'Work assigned',
  pending: true,
  vendor_name: null,
  updated_at: '2026-10-03T11:05:00+00:00',
  ...changes,
})

interface Mock {
  jobs: Job[]
  urls: string[]
  patches: { id: number; body: Record<string, unknown> }[]
  failPatch: boolean
}

function mockApi(): Mock {
  const m: Mock = { jobs: [job(2, DESIGNERS[1]), job(1, DESIGNERS[0])], urls: [], patches: [], failPatch: false }
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      m.urls.push(url)
      const path = url.replace(/\?.*$/, '')
      if (path.endsWith('/api/designers')) return Response.json({ designers: DESIGNERS })
      if (path.endsWith('/api/rotation/next')) return Response.json({ designer: DESIGNERS[0] })
      if (path.endsWith('/api/vendors')) return Response.json({ vendors: ['Sharma Printers'] })
      if (path.endsWith('/api/jobs')) return Response.json({ jobs: m.jobs, total: m.jobs.length })
      const patch = path.match(/\/api\/jobs\/(\d+)$/)
      if (patch && init?.method === 'PATCH') {
        const body = JSON.parse(String(init.body))
        m.patches.push({ id: Number(patch[1]), body })
        if (m.failPatch) return Response.json({ status: 'error', error: { code: 'DB_DOWN', message: 'Database unavailable', details: {} } }, { status: 503 })
        m.jobs = m.jobs.map((j) => (j.id === Number(patch[1]) ? { ...j, ...body } : j))
        return Response.json(m.jobs.find((j) => j.id === Number(patch[1])))
      }
      throw new Error(`unexpected ${url}`)
    }),
  )
  return m
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>
        <StaffProvider required={false}>
          <DesignersPage />
        </StaffProvider>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const jobCalls = (m: Mock) => m.urls.filter((u) => u.includes('/api/jobs?')).length

function setVisibility(state: 'visible' | 'hidden') {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  document.dispatchEvent(new Event('visibilitychange', { bubbles: true })) // bubbles, as browsers send it
}

describe('IST times', () => {
  it('formats in Asia/Kolkata whatever the device zone is', () => {
    expect(istDateTime('2026-10-03T11:05:00Z')).toBe('3 Oct 2026, 4:35 PM')
    expect(istDateTime('2026-10-03T20:00:00Z')).toBe('4 Oct 2026, 1:30 AM') // next day in India
  })
  it('says how long ago', () => {
    const now = Date.parse('2026-10-03T13:05:00Z')
    expect(timeAgo('2026-10-03T13:04:50Z', now)).toBe('just now')
    expect(timeAgo('2026-10-03T13:00:00Z', now)).toBe('5 minutes ago')
    expect(timeAgo('2026-10-03T11:05:00Z', now)).toBe('2 hours ago')
    expect(timeAgo('2026-10-01T13:05:00Z', now)).toBe('2 days ago')
    expect(age('2026-10-02T13:05:00Z', now)).toBe('1 day')
  })
})

describe('Designer Assignment tab', () => {
  beforeEach(() => setVisibility('visible'))
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('shows who is next and the pending jobs, newest first, with IST times', async () => {
    const m = mockApi()
    renderPage()
    await waitFor(() => expect(screen.getByTestId('next-designer')).toHaveTextContent('Next job goes to: Namit'))
    const table = (await screen.findAllByRole('table'))[0]
    const rows = within(table).getAllByRole('row').slice(1)
    expect(rows.map((r) => within(r).getAllByRole('cell')[1].textContent)).toEqual([
      'Customer 2Customised rigid box printing ×350',
      'Customer 1Customised rigid box printing ×350',
    ])
    expect(within(rows[0]).getAllByText('3 Oct 2026, 4:35 PM').length).toBeGreaterThan(0)
    // Pending only is on by default.
    expect(m.urls.find((u) => u.includes('/api/jobs?'))).toContain('pending=true')
  })

  it('filters by designer', async () => {
    const m = mockApi()
    const user = userEvent.setup()
    renderPage()
    await screen.findAllByRole('table')
    await user.selectOptions(screen.getByLabelText('Designer'), 'Ajendra')
    await waitFor(() => expect(m.urls.at(-1)).toMatch(/\/api\/jobs\?designer=2&pending=true$/))
  })

  it('a status change shows at once and is saved', async () => {
    const m = mockApi()
    const user = userEvent.setup()
    renderPage()
    const [select] = await screen.findAllByLabelText('Progress of invoice #20')
    await user.selectOptions(select, '2')
    expect(screen.getAllByLabelText('Progress of invoice #20')[0]).toHaveValue('2')
    await waitFor(() => expect(m.patches).toEqual([{ id: 2, body: { status: 2 } }]))
  })

  it('a failed status save goes back and says so', async () => {
    const m = mockApi()
    m.failPatch = true
    const user = userEvent.setup()
    renderPage()
    const [select] = await screen.findAllByLabelText('Progress of invoice #20')
    await user.selectOptions(select, '3')
    expect(await screen.findByText('Not saved: Database unavailable')).toBeInTheDocument()
    await waitFor(() => expect(screen.getAllByLabelText('Progress of invoice #20')[0]).toHaveValue('1'))
  })

  it('vendor name saves on Enter, trimmed, and suggests used names', async () => {
    const m = mockApi()
    const user = userEvent.setup()
    const { container } = renderPage()
    const [input] = await screen.findAllByLabelText('Vendor for invoice #19')
    await user.click(input)
    await user.type(input, '  Akal   Packaging {Enter}')
    await waitFor(() => expect(m.patches).toEqual([{ id: 1, body: { vendor_name: 'Akal Packaging' } }]))
    await waitFor(() => expect(container.querySelector('datalist option')).toHaveAttribute('value', 'Sharma Printers'))
  })

  it('refetches every 10 seconds while visible, not while hidden, and at once on return', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    const m = mockApi()
    renderPage()
    await screen.findAllByRole('table')
    const first = jobCalls(m)
    await act(() => vi.advanceTimersByTimeAsync(REFRESH_MS + 100))
    expect(jobCalls(m)).toBe(first + 1)

    // Another device changed a status: it shows up on the next refresh.
    m.jobs = m.jobs.map((j) => (j.id === 2 ? { ...j, status: 2, status_label: 'Sent to customer for approval' } : j))
    await act(() => vi.advanceTimersByTimeAsync(REFRESH_MS + 100))
    await waitFor(() => expect(screen.getAllByLabelText('Progress of invoice #20')[0]).toHaveValue('2'))

    act(() => setVisibility('hidden'))
    const hiddenAt = jobCalls(m)
    await act(() => vi.advanceTimersByTimeAsync(REFRESH_MS * 3))
    expect(jobCalls(m)).toBe(hiddenAt)

    act(() => setVisibility('visible'))
    await waitFor(() => expect(jobCalls(m)).toBe(hiddenAt + 1))
  })
})
