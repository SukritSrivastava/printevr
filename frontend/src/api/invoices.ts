// Invoice API (BRD-cart-invoice 8.4). Every /api/invoices call carries the staff token.
import { ApiError, NetworkError } from './client'
import type {
  InvoiceCreate,
  InvoiceList,
  InvoiceSettings,
  InvoicePdf,
  InvoiceStatus,
  NextBillNo,
  PaymentInput,
} from './invoiceTypes'
import type { ApiErrorBody } from './types'
import { filenameFromDisposition } from '../lib/download'

const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')
const TOKEN_KEY = 'printevr.staff.token'
const OFFLINE = "Can't reach the server. Nothing was saved."

export function staffToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setStaffToken(token: string | null): void {
  try {
    if (token) sessionStorage.setItem(TOKEN_KEY, token)
    else sessionStorage.removeItem(TOKEN_KEY)
  } catch {
    /* private mode: the token lives only for this page */
  }
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers)
  const token = staffToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body) headers.set('Content-Type', 'application/json')
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers })
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new NetworkError(OFFLINE)
  }
  if (!response.ok) {
    let body: ApiErrorBody | null = null
    try {
      body = (await response.json()) as ApiErrorBody
    } catch {
      /* not JSON */
    }
    if (body?.error) throw new ApiError(body.error.code, body.error.message, response.status, body.error.details)
    throw new NetworkError(OFFLINE)
  }
  return response
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init)
  try {
    return (await response.json()) as T
  } catch {
    throw new NetworkError(OFFLINE)
  }
}

async function pdf(path: string, init?: RequestInit): Promise<InvoicePdf> {
  const response = await send(path, init)
  const billNo = Number(response.headers.get('X-Bill-No'))
  const status = (response.headers.get('X-Invoice-Status') ?? 'unpaid') as InvoiceStatus
  const filename = filenameFromDisposition(response.headers.get('Content-Disposition'), `Invoice_${billNo}.pdf`)
  return { blob: await response.blob(), filename, billNo, status }
}

export async function staffLogin(passcode: string): Promise<string> {
  const { token } = await json<{ token: string; expires_at: string }>('/api/staff/login', {
    method: 'POST',
    body: JSON.stringify({ passcode }),
  })
  setStaffToken(token)
  return token
}

export const fetchInvoiceSettings = (signal?: AbortSignal) => json<InvoiceSettings>('/api/invoice-settings', { signal })

export const fetchNextBillNo = () => json<NextBillNo>('/api/invoices/next-bill-no')

export const createInvoice = (body: InvoiceCreate) =>
  pdf('/api/invoices', { method: 'POST', body: JSON.stringify(body) })

export function listInvoices(params: { q?: string; limit?: number; offset?: number }): Promise<InvoiceList> {
  const search = new URLSearchParams()
  if (params.q) search.set('q', params.q)
  search.set('limit', String(params.limit ?? 25))
  search.set('offset', String(params.offset ?? 0))
  return json<InvoiceList>(`/api/invoices?${search}`)
}

export const downloadInvoice = (billNo: number) => pdf(`/api/invoices/${billNo}/pdf`)

export const addPayment = (billNo: number, payment: PaymentInput) =>
  pdf(`/api/invoices/${billNo}/payments`, { method: 'POST', body: JSON.stringify(payment) })
