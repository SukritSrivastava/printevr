// Cart storage: versions, retention of customer details, and storage that misbehaves.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CartLine } from '../api/invoiceTypes'
import { CUSTOMER_FIELDS, emptyCheckout, type Checkout } from './checkout'
import {
  CUSTOMER_TTL_MS,
  FORGET_CUSTOMER_EVENT,
  LEGACY_KEYS,
  STORAGE_KEY,
  customerExpired,
  forgetCustomerDetails,
  loadCart,
  saveCart,
} from './storage'

const NOW = Date.UTC(2026, 9, 3, 6, 0, 0)
const HOUR = 60 * 60 * 1000

const line: CartLine = {
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

const customer: Partial<Checkout> = {
  business_name: 'Sogat Jutti Store',
  contact_person: 'Raman',
  address: 'Sector 67, Mohali',
  phone: '+91 95010 60618',
  buyer_gstin: '03ABCDE1234F1Z5',
  consignee_same: false,
  consignee_name: 'Warehouse',
  consignee_address: 'Phase 8, Mohali',
  consignee_phone: '+91 90000 00000',
  consignee_gstin: '03ABCDE1234F2Z4',
  vehicle_no: 'PB65 1234',
  eway_bill_no: '1234',
  gr_rr_no: '77',
  po_date: '2026-10-01',
  delivery_terms: 'Door delivery',
  payment_terms: 'Advance',
  transport: 'By road',
  station: 'Mohali',
}
const cartSettings: Partial<Checkout> = { bill_no: '21', quote_no: '4', billing_type: 'gst', gst_slab: 'igst_18', saving_amount: '500', split_payment: true, advance_pct: '50' }
const filled = (): Checkout => ({ ...emptyCheckout(), ...customer, ...cartSettings })

const stored = () => JSON.parse(localStorage.getItem(STORAGE_KEY)!)
const seed = (value: unknown, key = STORAGE_KEY) => localStorage.setItem(key, typeof value === 'string' ? value : JSON.stringify(value))

function expectNoCustomer(checkout: Checkout) {
  const blank = emptyCheckout()
  for (const key of CUSTOMER_FIELDS) expect(checkout[key], key).toEqual(blank[key])
}

beforeEach(() => localStorage.clear())
afterEach(() => vi.restoreAllMocks())

describe('saving', () => {
  it('stores a versioned record with the time of the last change, and no credentials', () => {
    saveCart({ lines: [line], checkout: filled() }, NOW)
    expect(stored()).toMatchObject({ version: 2, saved_at: NOW, lines: [line] })
    expect(Object.keys(localStorage)).toEqual([STORAGE_KEY])
    expect(localStorage.getItem(STORAGE_KEY)).not.toMatch(/token|passcode|password/i)
  })

  it('keeps working when storage is full or blocked', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError')
    })
    expect(() => saveCart({ lines: [line], checkout: filled() }, NOW)).not.toThrow()
  })
})

describe('retention', () => {
  it('keeps customer details inside the retention period', () => {
    saveCart({ lines: [line], checkout: filled() }, NOW)
    const { state, changedAt } = loadCart(NOW + CUSTOMER_TTL_MS - 1000)
    expect(state.checkout).toEqual(filled())
    expect(changedAt).toBe(NOW) // opening the page doesn't restart the period
  })

  it('clears customer details after it, keeping the lines and the cart settings', () => {
    saveCart({ lines: [line], checkout: filled() }, NOW)
    const later = NOW + CUSTOMER_TTL_MS + 1000
    const { state } = loadCart(later)
    expectNoCustomer(state.checkout)
    expect(state.checkout).toMatchObject(cartSettings)
    expect(state.lines).toEqual([line])
    // Removed from storage at once, not at the next change.
    expectNoCustomer(stored().checkout)
    expect(stored().lines).toEqual([line])
  })

  it('does not trust a missing, broken or future saved time', () => {
    for (const saved_at of [undefined, 'yesterday', NOW + 2 * HOUR]) {
      seed({ version: 2, saved_at, lines: [line], checkout: filled() })
      expectNoCustomer(loadCart(NOW).state.checkout)
    }
  })

  it('customerExpired is false for a blank form, however old', () => {
    expect(customerExpired(emptyCheckout(), 0, NOW)).toBe(false)
    expect(customerExpired(filled(), NOW - CUSTOMER_TTL_MS - 1, NOW)).toBe(true)
    expect(customerExpired(filled(), NOW - HOUR, NOW)).toBe(false)
  })
})

describe('sign out', () => {
  it('removes customer details from storage, keeps the lines, and tells an open cart', () => {
    saveCart({ lines: [line], checkout: filled() }, NOW)
    seed({ lines: [], checkout: customer }, LEGACY_KEYS[0])
    const heard = vi.fn()
    window.addEventListener(FORGET_CUSTOMER_EVENT, heard)
    forgetCustomerDetails(NOW + 1000)
    window.removeEventListener(FORGET_CUSTOMER_EVENT, heard)
    expectNoCustomer(stored().checkout)
    expect(stored().checkout).toMatchObject(cartSettings)
    expect(stored().lines).toEqual([line])
    expect(localStorage.getItem(LEGACY_KEYS[0])).toBeNull()
    expect(heard).toHaveBeenCalledOnce()
  })

  it('does nothing harmful with an empty or blocked storage', () => {
    expect(() => forgetCustomerDetails(NOW)).not.toThrow()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    expect(() => forgetCustomerDetails(NOW)).not.toThrow()
  })
})

describe('older, corrupt and unavailable storage', () => {
  it('reads a v1 cart once: lines kept, customer details dropped (their age is unknown)', () => {
    seed({ lines: [line], checkout: { ...customer, ...cartSettings, salesperson: 'Old', gst_option: 'x' } }, LEGACY_KEYS[0])
    const { state } = loadCart(NOW)
    expect(state.lines).toEqual([line])
    expectNoCustomer(state.checkout)
    expect(state.checkout).toMatchObject(cartSettings)
    expect(state.checkout).not.toHaveProperty('salesperson')
    expect(localStorage.getItem(LEGACY_KEYS[0])).toBeNull()
  })

  it('a v1 with_gst / without_gst bill type is not a choice', () => {
    seed({ lines: [], checkout: { billing_type: 'with_gst' } }, LEGACY_KEYS[0])
    expect(loadCart(NOW).state.checkout.billing_type).toBe('')
  })

  it.each([
    ['not JSON', '{not json'],
    ['not an object', '"text"'],
    ['null', 'null'],
    ['an unknown version', JSON.stringify({ version: 3, saved_at: NOW, lines: [line], checkout: customer })],
    ['no version', JSON.stringify({ lines: [line], checkout: customer })],
    ['lines that are not a list', JSON.stringify({ version: 2, saved_at: NOW, lines: 'x', checkout: {} })],
  ])('starts empty and warns on %s', (_, raw) => {
    seed(raw)
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const { state } = loadCart(NOW)
    expect(state.lines).toEqual([])
    expect(state.checkout).toEqual(emptyCheckout())
    expect(warn).toHaveBeenCalled()
    expect(localStorage.getItem(STORAGE_KEY)).toBeNull()
  })

  it('drops bad lines and wrongly typed fields, keeping the rest', () => {
    seed({
      version: 2,
      saved_at: NOW,
      lines: [line, null, { id: 7 }, { ...line, id: 'line-2', specs: [{ value: 3 }] }],
      checkout: { business_name: 42, address: 'Mohali', consignee_same: 'yes', payment_terms: null, bill_no: '21' },
    })
    const { state } = loadCart(NOW)
    expect(state.lines.map((l) => l.id)).toEqual(['line-1'])
    expect(state.checkout).toMatchObject({ business_name: '', address: 'Mohali', consignee_same: true, payment_terms: null, bill_no: '21' })
  })

  it('starts empty when storage cannot be read at all', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('blocked', 'SecurityError')
    })
    expect(loadCart(NOW).state).toEqual({ lines: [], checkout: emptyCheckout() })
  })
})
