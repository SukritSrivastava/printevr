// Attendance and Employees tabs (API mocked), the attendance helpers, and percent add-ons.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AttendanceRecord, DayRegister, Employee, MonthSummary } from './api/team'
import { AddonList } from './components/AddonList'
import { StaffProvider } from './components/StaffLoginDialog'
import { AttendancePage } from './components/team/AttendancePage'
import { EmployeesPage } from './components/team/EmployeesPage'
import { TeamAdminProvider } from './components/team/TeamAdmin'
import { ToastProvider } from './components/Toast'
import { dayStatus, duration, istClock, istHHMM, monthCsv, shiftDay, shiftMonth } from './lib/attendance'
import { CalculatorLinkProvider } from './nav'

const ROLES = [
  { value: 'designer', label: 'Designer' },
  { value: 'production', label: 'Production' },
  { value: 'staff', label: 'Staff' },
]

const person = (id: number, name: string, changes: Partial<Employee> = {}): Employee => ({
  id,
  name,
  role: 'designer',
  phone: null,
  email: null,
  joined_on: null,
  active: true,
  ...changes,
})

const record = (changes: Partial<AttendanceRecord> = {}): AttendanceRecord => ({
  work_date: '2026-10-08',
  check_in: '2026-10-08T03:35:00+00:00', // 9:05 AM IST
  check_out: null,
  minutes: null,
  note: null,
  edited_by_admin: false,
  ...changes,
})

describe('attendance helpers', () => {
  it('formats IST times and durations', () => {
    expect(istClock('2026-10-08T03:35:00+00:00')).toBe('9:05 AM')
    expect(istHHMM('2026-10-08T12:45:00+00:00')).toBe('18:15')
    expect(duration(555)).toBe('9h 15m')
    expect(duration(45)).toBe('45m')
  })

  it('works out the day status', () => {
    expect(dayStatus(null, true)).toBe('not_in')
    expect(dayStatus(null, false)).toBe('absent')
    expect(dayStatus(record(), true)).toBe('in')
    expect(dayStatus(record(), false)).toBe('missing_out')
    expect(dayStatus(record({ check_out: '2026-10-08T12:00:00+00:00', minutes: 505 }), true)).toBe('out')
  })

  it('moves between days and months', () => {
    expect(shiftDay('2026-10-31', 1)).toBe('2026-11-01')
    expect(shiftDay('2026-03-01', -1)).toBe('2026-02-28')
    expect(shiftMonth('2026-01', -1)).toBe('2025-12')
    expect(shiftMonth('2026-12', 1)).toBe('2027-01')
  })

  it('writes the month as CSV, one column per day', () => {
    const summary: MonthSummary = {
      month: '2026-02',
      first: '2026-02-01',
      last: '2026-02-03',
      today: '2026-02-10',
      rows: [
        {
          employee: person(1, 'Sharma, Asha'),
          days_present: 2,
          minutes: 540,
          open_days: 1,
          days: {
            '2026-02-01': record({ work_date: '2026-02-01', check_in: '2026-02-01T03:30:00+00:00', check_out: '2026-02-01T12:30:00+00:00', minutes: 540 }),
            '2026-02-03': record({ work_date: '2026-02-03', check_in: '2026-02-03T04:00:00+00:00' }),
          },
        },
      ],
    }
    expect(monthCsv(summary, () => 'Designer').split('\r\n')).toEqual([
      'Employee,Role,Days present,Hours worked,Missing check-outs,2026-02-01,2026-02-02,2026-02-03',
      '"Sharma, Asha",Designer,2,9.00,1,09:00-18:00,,09:30-?',
      '',
    ])
  })
})

describe('AddonList', () => {
  it('shows a percent add-on as a share of the unit price', () => {
    render(
      <AddonList
        addons={[
          { id: 'inlet', name: 'Inlet (+20% of box price)', price: null, basis: 'per_unit', from_sheet: false, percent: '20' },
          { id: 'gold_foiling', name: 'Gold foiling', price: '4000', basis: 'per_order', from_sheet: false, percent: null },
        ]}
        selected={[]}
        unit="box"
        onToggle={() => {}}
      />,
    )
    expect(screen.getByText('+20% of the box price')).toBeInTheDocument()
    expect(screen.getByText(/per order/)).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------- pages

interface Call {
  method: string
  path: string
  body: Record<string, unknown> | null
  admin: string | null
}

interface Mock {
  calls: Call[]
  employees: Employee[]
  day: DayRegister
}

function mockApi(): Mock {
  const m: Mock = {
    calls: [],
    employees: [person(1, 'Asha'), person(2, 'Bilal', { role: 'production' })],
    day: {
      date: '2026-10-08',
      today: '2026-10-08',
      rows: [],
      counts: { employees: 2, present: 0, checked_in_now: 0 },
    },
  }
  m.day.rows = m.employees.map((employee) => ({ employee, record: null }))
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? 'GET'
      const path = url.replace(/\?.*$/, '')
      const body = init?.body ? JSON.parse(String(init.body)) : null
      const admin = new Headers(init?.headers).get('X-Team-Admin')
      m.calls.push({ method, path, body, admin })
      if (path.endsWith('/api/team/settings')) {
        return Response.json({ roles: ROLES, admin_configured: true, is_admin: admin === 'admin-token', timezone: 'Asia/Kolkata' })
      }
      if (path.endsWith('/api/team/admin/login')) {
        if (body.passcode !== 'letmein')
          return Response.json({ status: 'error', error: { code: 'BAD_PASSCODE', message: "That admin passcode isn't right", details: {} } }, { status: 401 })
        return Response.json({ token: 'admin-token', expires_at: '2026-10-08T20:00:00+00:00' })
      }
      if (path.endsWith('/api/team/attendance') && method === 'GET') return Response.json(m.day)
      if (path.endsWith('/api/team/attendance/check-in')) {
        const row = m.day.rows.find((r) => r.employee.id === body.employee_id)!
        row.record = record()
        m.day.counts = { ...m.day.counts, present: 1, checked_in_now: 1 }
        return Response.json(row)
      }
      if (path.endsWith('/api/team/employees') && method === 'GET') return Response.json({ employees: m.employees })
      if (path.endsWith('/api/team/employees') && method === 'POST') {
        if (admin !== 'admin-token')
          return Response.json({ status: 'error', error: { code: 'ADMIN_REQUIRED', message: 'Enter the admin passcode', details: {} } }, { status: 403 })
        const added = person(3, body.name, { role: body.role, phone: body.phone })
        m.employees = [...m.employees, added]
        return Response.json(added, { status: 201 })
      }
      const del = path.match(/\/api\/team\/employees\/(\d+)$/)
      if (del && method === 'DELETE') {
        const id = Number(del[1])
        m.employees = m.employees.filter((e) => e.id !== id)
        return Response.json({ ...person(id, 'x'), active: false })
      }
      throw new Error(`unexpected ${method} ${url}`)
    }),
  )
  return m
}

function renderPage(page: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <CalculatorLinkProvider>
        <QueryClientProvider client={client}>
          <ToastProvider>
            <StaffProvider required={false}>
              <TeamAdminProvider>{page}</TeamAdminProvider>
            </StaffProvider>
          </ToastProvider>
        </QueryClientProvider>
      </CalculatorLinkProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => sessionStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('Attendance page', () => {
  it('lists everyone for today and checks a person in', async () => {
    const m = mockApi()
    renderPage(<AttendancePage />)
    const asha = (await screen.findByText('Asha')).closest('li')!
    expect(within(asha).getByText('Not checked in')).toBeInTheDocument()
    expect(screen.getByTestId('attendance-counts')).toHaveTextContent('0 of 2 present · 0 checked in now')
    // No admin token: no correcting times.
    expect(screen.queryByRole('button', { name: /Edit Asha's attendance/ })).not.toBeInTheDocument()

    await userEvent.click(within(asha).getByRole('button', { name: 'Check in Asha' }))
    expect(m.calls.find((c) => c.path.endsWith('/check-in'))?.body).toEqual({ employee_id: 1 })
    await waitFor(() => expect(within(screen.getByText('Asha').closest('li')!).getByText('Checked in')).toBeInTheDocument())
    expect(within(screen.getByText('Asha').closest('li')!).getByText('9:05 AM')).toBeInTheDocument()
    expect(within(screen.getByText('Asha').closest('li')!).getByRole('button', { name: 'Check out Asha' })).toBeInTheDocument()
  })
})

describe('Employees page', () => {
  it('asks for the admin passcode, then adds an employee with the admin token', async () => {
    const m = mockApi()
    renderPage(<EmployeesPage />)
    await screen.findByText('Bilal')
    await userEvent.click(screen.getByRole('button', { name: '+ Add employee' }))

    const login = await screen.findByRole('dialog', { name: 'Admin passcode' })
    await userEvent.type(within(login).getByLabelText('Passcode'), 'wrong')
    await userEvent.click(screen.getByRole('button', { name: 'Unlock' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("That admin passcode isn't right")
    await userEvent.type(within(login).getByLabelText('Passcode'), 'letmein')
    await userEvent.click(screen.getByRole('button', { name: 'Unlock' }))
    expect(sessionStorage.getItem('printevr.team.admin')).toBe('admin-token')
    expect(localStorage.getItem('printevr.team.admin')).toBeNull()

    const dialog = await screen.findByRole('dialog', { name: 'Add employee' })
    await userEvent.type(within(dialog).getByLabelText('Name'), 'Chitra')
    await userEvent.selectOptions(within(dialog).getByLabelText('Role'), 'production')
    await userEvent.type(within(dialog).getByLabelText('Phone (optional)'), '98765 43210')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add employee' }))

    const post = m.calls.find((c) => c.method === 'POST' && c.path.endsWith('/api/team/employees'))!
    expect(post.body).toEqual({ name: 'Chitra', role: 'production', phone: '98765 43210', email: null, joined_on: null })
    expect(post.admin).toBe('admin-token')
    expect(await screen.findByText('Chitra')).toBeInTheDocument()
    expect(screen.getByText(/Admin unlocked/)).toBeInTheDocument()
  })

  it('removes an employee after confirming', async () => {
    const m = mockApi()
    sessionStorage.setItem('printevr.team.admin', 'admin-token')
    renderPage(<EmployeesPage />)
    await userEvent.click(await screen.findByRole('button', { name: 'Remove Bilal' }))
    const dialog = await screen.findByRole('dialog', { name: 'Remove Bilal?' })
    expect(dialog).toHaveTextContent('Their past attendance is kept')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Remove' }))
    expect(m.calls.some((c) => c.method === 'DELETE' && c.path.endsWith('/api/team/employees/2') && c.admin === 'admin-token')).toBe(true)
    await waitFor(() => expect(screen.queryByText('Bilal')).not.toBeInTheDocument())
  })
})
