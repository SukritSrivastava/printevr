import type { ApiErrorBody, CalculateRequest, Catalog, QuoteResponse } from './types'

const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

/** The server answered with an error object (validation, unknown item, policy block...). */
export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details: Record<string, unknown> = {},
  ) {
    super(message)
  }
}

/** The server could not be reached at all. */
export class NetworkError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, init)
  } catch (err) {
    if ((err as Error).name === 'AbortError') throw err
    throw new NetworkError("Can't reach the pricing server")
  }
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new NetworkError("Can't reach the pricing server")
  }
  if (!response.ok) {
    const e = (body as ApiErrorBody).error
    if (e) throw new ApiError(e.code, e.message, response.status, e.details)
    throw new NetworkError("Can't reach the pricing server")
  }
  return body as T
}

export interface Session {
  authenticated: boolean
  password_required: boolean
}

export function fetchSession(signal?: AbortSignal): Promise<Session> {
  return request<Session>('/api/session', { signal })
}

export function login(password: string): Promise<{ status: 'ok' }> {
  return request('/api/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password }),
  })
}

export function logout(): Promise<{ status: 'ok' }> {
  return request('/api/logout', { method: 'POST' })
}

export function fetchCatalog(signal?: AbortSignal): Promise<Catalog> {
  return request<Catalog>('/api/catalog', { signal })
}

export function calculate(body: CalculateRequest, signal?: AbortSignal): Promise<QuoteResponse> {
  return request<QuoteResponse>('/api/calculate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}
