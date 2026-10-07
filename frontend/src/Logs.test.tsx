// Logs tab (admin only): locked without admin, then lists changes with who/what/when and details.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LogEntry } from './api/team'
import { StaffProvider } from './components/StaffLoginDialog'
import { LogsPage, device } from './components/team/LogsPage'
import { TeamAdminProvider } from './components/team/TeamAdmin'
import { ToastProvider } from './components/Toast'
import { CalculatorLinkProvider } from './nav'

const ENTRY: LogEntry = {
  id: 7,
  at: '2026-10-08T05:00:00+00:00', // 10:30 AM IST
  actor_role: 'staff',
  actor_name: null,
  category: 'invoices',
  summary: 'Created Invoice #19 for Sogat Jutti Store: 3 lines, ₹32,125 before tax (unpaid)',
  method: 'POST',
  path: '/api/invoices',
  status: 201,
  details: { customer: 'Sogat Jutti Store', lines: [{ title: 'Rigid box', quantity: 350 }] },
  ip: '49.36.1.2',
  user_agent: 'Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/128.0 Mobile Safari/537.36',
}

function mockApi() {
  const urls: { url: string; admin: string | null }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const admin = new Headers(init?.headers).get('X-Team-Admin')
      urls.push({ url, admin })
      if (url.includes('/api/team/settings'))
        return Response.json({ roles: [], admin_configured: true, is_admin: admin === 'tok', timezone: 'Asia/Kolkata' })
      if (url.includes('/api/team/admin/login')) return Response.json({ token: 'tok', expires_at: '2026-10-08T20:00:00Z' })
      if (url.includes('/api/team/logs'))
        return Response.json({ entries: [ENTRY], total: 1, limit: 50, offset: 0, categories: [{ value: 'invoices', label: 'Invoices & payments' }] })
      throw new Error(`unexpected ${url}`)
    }),
  )
  return urls
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <CalculatorLinkProvider>
        <QueryClientProvider client={client}>
          <ToastProvider>
            <StaffProvider required={false}>
              <TeamAdminProvider>
                <LogsPage />
              </TeamAdminProvider>
            </StaffProvider>
          </ToastProvider>
        </QueryClientProvider>
      </CalculatorLinkProvider>
    </MemoryRouter>,
  )
}

beforeEach(() => sessionStorage.clear())
afterEach(() => vi.unstubAllGlobals())

describe('Logs page', () => {
  it('is locked until the admin passcode is entered, then lists changes', async () => {
    const urls = mockApi()
    renderPage()
    await userEvent.click(await screen.findByRole('button', { name: 'Unlock admin' }))
    expect(urls.some((u) => u.url.includes('/api/team/logs'))).toBe(false)
    const dialog = await screen.findByRole('dialog', { name: 'Admin passcode' })
    await userEvent.type(within(dialog).getByLabelText('Passcode'), 'secret')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Unlock' }))

    expect(await screen.findByText(ENTRY.summary)).toBeInTheDocument()
    expect(urls.filter((u) => u.url.includes('/api/team/logs')).every((u) => u.admin === 'tok')).toBe(true)
    expect(screen.getByText('8 Oct 2026, 10:30 AM')).toBeInTheDocument()
    expect(screen.getByText('Staff')).toBeInTheDocument()
    expect(screen.getByText('Chrome on Android · 49.36.1.2')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /Created Invoice #19/ }))
    expect(screen.getByText('Sogat Jutti Store')).toBeInTheDocument()
    expect(screen.getByText('POST /api/invoices · 201')).toBeInTheDocument()
  })

  it('sends the filters', async () => {
    const urls = mockApi()
    sessionStorage.setItem('printevr.team.admin', 'tok')
    renderPage()
    await screen.findByText(ENTRY.summary)
    await userEvent.selectOptions(screen.getByLabelText('Area'), 'invoices')
    await userEvent.type(screen.getByLabelText('Search'), 'sogat')
    await userEvent.click(screen.getByRole('button', { name: 'Show' }))
    await waitFor(() => expect(urls.at(-1)?.url).toContain('category=invoices'))
    expect(urls.at(-1)?.url).toContain('q=sogat')
  })

  it('names common devices', () => {
    expect(device(ENTRY.user_agent)).toBe('Chrome on Android')
    expect(device('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit Version/17.0 Mobile Safari/604.1')).toBe('Safari on iPhone/iPad')
    expect(device(null)).toBe('Unknown device')
  })
})
