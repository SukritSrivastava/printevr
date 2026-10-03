// The cart in localStorage (BRD-cart-invoice FR-C5) and how long customer details stay there.
//
// Retention policy:
// - Cart lines (articles, specs, quantities, prices) and the cart's own settings (document
//   type, bill / quote numbers, date, GST slab, saving, payment split) stay until Clear cart,
//   as before. They describe the order, not the customer, and prices are re-checked anyway.
// - Customer details (CUSTOMER_FIELDS in checkout.ts: names, addresses, phones, GSTINs,
//   transport details) are cleared CUSTOMER_TTL_MS after the checkout form was last changed,
//   when staff press Sign out, and when a saved cart from an older version is read (its age is
//   unknown). The open page clears them on the same schedule, not only the next load.
// - Nothing that signs anyone in is kept here: the site session is an httpOnly cookie and the
//   staff token lives in sessionStorage (api/invoices.ts) and is dropped on Sign out.
// - Storage that is blocked, full, unreadable, from an unknown version or holding wrong types
//   never breaks the page: the cart starts empty (or without the bad parts) and a warning is
//   logged.
import type { CartLine, SpecLine } from '../api/invoiceTypes'
import { type Checkout, emptyCheckout, hasCustomerDetails, withoutCustomer } from './checkout'

export const STORAGE_KEY = 'printevr.cart.v2'
export const STORAGE_VERSION = 2
/** Saved before customer details expired; read once, then removed. */
export const LEGACY_KEYS = ['printevr.cart.v1'] as const
export const CUSTOMER_TTL_MS = 12 * 60 * 60 * 1000
/** A saved time further ahead than this (a clock changed) isn't trusted. */
const CLOCK_SKEW_MS = 5 * 60 * 1000
/** Tells a mounted CartProvider to drop the customer details it holds in memory. */
export const FORGET_CUSTOMER_EVENT = 'printevr:forget-customer'

export interface CartState {
  lines: CartLine[]
  checkout: Checkout
}

interface Saved {
  version: typeof STORAGE_VERSION
  /** When the checkout form last changed (ms since the epoch). */
  saved_at: number
  lines: CartLine[]
  checkout: Checkout
}

export interface Loaded {
  state: CartState
  /** When it last changed; customer details expire CUSTOMER_TTL_MS after this. */
  changedAt: number
}

const validSpec = (s: unknown): s is SpecLine => !!s && typeof (s as SpecLine).value === 'string'

function validLines(lines: unknown): CartLine[] {
  if (!Array.isArray(lines)) throw new Error('lines missing')
  return lines.filter(
    (l): l is CartLine =>
      !!l && typeof l.id === 'string' && typeof l.title === 'string' && Array.isArray(l.specs) && l.specs.every(validSpec),
  )
}

/**
 * The saved form, field by field: a field of the wrong type keeps its blank start. A checkout
 * saved by an older version also had a default bill type (without_gst), and with_gst meant the
 * old GST rates, so neither counts as a choice; salesperson and gst_option are gone.
 */
export function readCheckout(saved: unknown): Checkout {
  const blank = emptyCheckout()
  const raw = saved && typeof saved === 'object' ? (saved as Record<string, unknown>) : {}
  const out = { ...blank } as Record<string, unknown>
  for (const key of Object.keys(blank) as (keyof Checkout)[]) {
    const value = raw[key]
    const start = blank[key]
    const ok = typeof value === typeof start || (start === null && (value === null || typeof value === 'string'))
    if (ok && value !== undefined) out[key] = value
  }
  if (out.billing_type !== 'non_gst' && out.billing_type !== 'gst') out.billing_type = ''
  return out as unknown as Checkout
}

function storage(): Storage | null {
  try {
    return globalThis.localStorage ?? null
  } catch {
    return null // blocked (e.g. some private modes throw on access)
  }
}

function expired(changedAt: number, now: number): boolean {
  return !Number.isFinite(changedAt) || now - changedAt > CUSTOMER_TTL_MS || changedAt - now > CLOCK_SKEW_MS
}

const empty = (now: number): Loaded => ({ state: { lines: [], checkout: emptyCheckout() }, changedAt: now })

function readLegacy(store: Storage, now: number): Loaded | null {
  for (const key of LEGACY_KEYS) {
    let raw: string | null
    try {
      raw = store.getItem(key)
      if (raw !== null) store.removeItem(key)
    } catch {
      return null
    }
    if (raw === null) continue
    try {
      const parsed = JSON.parse(raw) as { lines?: unknown; checkout?: unknown }
      // Its age is unknown, so its customer details count as expired.
      return { state: { lines: validLines(parsed.lines), checkout: withoutCustomer(readCheckout(parsed.checkout)) }, changedAt: now }
    } catch (err) {
      console.warn('Saved cart could not be read; starting with an empty cart.', err)
      return null
    }
  }
  return null
}

/** The saved cart, with customer details removed if they are past the retention period. */
export function loadCart(now: number = Date.now()): Loaded {
  const store = storage()
  if (!store) return empty(now)
  let raw: string | null
  try {
    raw = store.getItem(STORAGE_KEY)
  } catch {
    return empty(now)
  }
  if (raw === null) return readLegacy(store, now) ?? empty(now)
  try {
    const parsed = JSON.parse(raw) as Partial<Saved>
    if (!parsed || typeof parsed !== 'object' || parsed.version !== STORAGE_VERSION) {
      throw new Error(`unknown cart version ${String((parsed as Partial<Saved> | null)?.version)}`)
    }
    const lines = validLines(parsed.lines)
    let checkout = readCheckout(parsed.checkout)
    const changedAt = typeof parsed.saved_at === 'number' ? parsed.saved_at : Number.NaN
    if (expired(changedAt, now) && hasCustomerDetails(checkout)) {
      checkout = withoutCustomer(checkout)
      const state = { lines, checkout }
      saveCart(state, now) // don't leave them in storage until the next change
      return { state, changedAt: now }
    }
    return { state: { lines, checkout }, changedAt: Number.isFinite(changedAt) ? Math.min(changedAt, now) : now }
  } catch (err) {
    console.warn('Saved cart could not be read; starting with an empty cart.', err)
    try {
      store.removeItem(STORAGE_KEY)
    } catch {
      /* blocked */
    }
    return empty(now)
  }
}

export function saveCart(state: CartState, changedAt: number): void {
  const saved: Saved = { version: STORAGE_VERSION, saved_at: changedAt, lines: state.lines, checkout: state.checkout }
  try {
    storage()?.setItem(STORAGE_KEY, JSON.stringify(saved))
  } catch {
    /* storage full or blocked: the cart still works for this visit */
  }
}

/** Sign out: remove customer details from storage (and from an open cart); lines stay. */
export function forgetCustomerDetails(now: number = Date.now()): void {
  const store = storage()
  if (store) {
    for (const key of LEGACY_KEYS) {
      try {
        store.removeItem(key)
      } catch {
        /* blocked */
      }
    }
    try {
      if (store.getItem(STORAGE_KEY) !== null) {
        const { state } = loadCart(now)
        saveCart({ ...state, checkout: withoutCustomer(state.checkout) }, now)
      }
    } catch {
      /* blocked */
    }
  }
  globalThis.dispatchEvent?.(new Event(FORGET_CUSTOMER_EVENT))
}

export function customerExpired(checkout: Checkout, changedAt: number, now: number = Date.now()): boolean {
  return hasCustomerDetails(checkout) && expired(changedAt, now)
}
