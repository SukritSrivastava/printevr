// Cart lines and the unsaved checkout form (BRD-cart-invoice FR-C5): React state, saved to
// localStorage after every change. This is the team's own site, so browser storage is fine.
import { createContext, useContext, useEffect, useMemo, useReducer, useState } from 'react'
import type { BillType, CartLine, ChangedLine, SpecLine } from '../api/invoiceTypes'

export const STORAGE_KEY = 'printevr.cart.v1'

export interface Checkout {
  /** Ship To; on a GST invoice, the buyer (Billed to). */
  business_name: string
  contact_person: string
  address: string
  phone: string
  /** The invoice number for the chosen bill type ('' = assign the next one on print). */
  bill_no: string
  /** Without storage only: the next quotation number on this device. */
  quote_no: string
  invoice_date: string // YYYY-MM-DD
  billing_type: BillType | '' // '' = not chosen yet (no default)
  gst_slab: string // a GstSlab key; '' = not picked yet
  // GST invoice only
  buyer_gstin: string
  consignee_same: boolean
  consignee_name: string
  consignee_address: string
  consignee_phone: string
  consignee_gstin: string
  delivery_terms: string
  /** null = not touched: shows (and sends) the default from config/invoice.yaml */
  payment_terms: string | null
  po_date: string // YYYY-MM-DD or ''
  gr_rr_no: string
  transport: string | null
  vehicle_no: string
  eway_bill_no: string
  station: string | null
  saving_amount: string
  /** Off = pay in full before printing (the default); on = advance_pct now, the rest before dispatch. */
  split_payment: boolean
  /** null = not touched: shows (and sends) the config's advance percent */
  advance_pct: string | null
  /** Custom invoice: every line's rate is editable (down to 0). Never printed. */
  custom_invoice: boolean
}

/** The GST invoice fields whose blank start shows a default (gst_field_defaults). */
export const DEFAULTED = ['payment_terms', 'transport', 'station'] as const

export interface CartState {
  lines: CartLine[]
  checkout: Checkout
}

/** Today's date in India (YYYY-MM-DD), whatever the device's time zone. */
export function todayIST(now: Date = new Date()): string {
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit' }).format(now)
}

export function newId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c?.randomUUID) return c.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    return (ch === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

export const emptyCheckout = (): Checkout => ({
  business_name: '',
  contact_person: '',
  address: '',
  phone: '',
  bill_no: '',
  quote_no: '1',
  invoice_date: todayIST(),
  billing_type: '',
  gst_slab: '',
  buyer_gstin: '',
  consignee_same: true,
  consignee_name: '',
  consignee_address: '',
  consignee_phone: '',
  consignee_gstin: '',
  delivery_terms: '',
  payment_terms: null,
  po_date: '',
  gr_rr_no: '',
  transport: null,
  vehicle_no: '',
  eway_bill_no: '',
  station: null,
  saving_amount: '',
  split_payment: false,
  advance_pct: null,
  custom_invoice: false,
})

type Action =
  | { type: 'add'; lines: CartLine[] }
  | { type: 'update'; id: string; patch: Partial<CartLine> }
  | { type: 'remove'; id: string }
  | { type: 'move'; id: string; by: -1 | 1 }
  | { type: 'clear' }
  | { type: 'checkout'; patch: Partial<Checkout> }
  | { type: 'fresh'; changes: ChangedLine[] }

/** Back to the calculator's rate (custom invoice "Reset to calculated price"). */
export const calculatedPrice = (l: CartLine): Partial<CartLine> => (l.catalogue_unit_price === null ? {} : { unit_price: l.catalogue_unit_price })

/** A price counts as edited when it differs from the catalogue price. */
export const isEdited = (l: CartLine) => l.catalogue_unit_price !== null && Number(l.unit_price) !== Number(l.catalogue_unit_price)

/** Apply a fresh quote to a line: new billed quantity and catalogue price; an edited price is kept. */
export function withFreshPrice(line: CartLine, fresh: { quantity: number; catalogue_unit_price: string; warnings: CartLine['warnings'] }): CartLine {
  return {
    ...line,
    quantity: fresh.quantity,
    catalogue_unit_price: fresh.catalogue_unit_price,
    unit_price: isEdited(line) ? line.unit_price : fresh.catalogue_unit_price,
    warnings: line.source === 'addon' ? line.warnings : fresh.warnings,
  }
}

function reducer(state: CartState, action: Action): CartState {
  switch (action.type) {
    case 'add':
      return { ...state, lines: [...state.lines, ...action.lines] }
    case 'update':
      return { ...state, lines: state.lines.map((l) => (l.id === action.id ? { ...l, ...action.patch } : l)) }
    case 'remove':
      return { ...state, lines: state.lines.filter((l) => l.id !== action.id && l.parent_id !== action.id) }
    case 'move': {
      const i = state.lines.findIndex((l) => l.id === action.id)
      const j = i + action.by
      if (i < 0 || j < 0 || j >= state.lines.length) return state
      const lines = [...state.lines]
      ;[lines[i], lines[j]] = [lines[j], lines[i]]
      return { ...state, lines }
    }
    case 'clear':
      return {
        lines: [],
        checkout: {
          ...emptyCheckout(),
          bill_no: state.checkout.bill_no,
          quote_no: state.checkout.quote_no,
          billing_type: state.checkout.billing_type,
        },
      }
    case 'checkout':
      return { ...state, checkout: { ...state.checkout, ...action.patch } }
    case 'fresh': {
      const byId = new Map(action.changes.map((c) => [c.id, c]))
      return { ...state, lines: state.lines.map((l) => (byId.has(l.id) ? withFreshPrice(l, byId.get(l.id)!) : l)) }
    }
  }
}

const validSpec = (s: unknown): s is SpecLine => !!s && typeof (s as SpecLine).value === 'string'

/**
 * A checkout saved by an older version: the bill type had a default (without_gst) and with_gst
 * meant the old GST rates, so neither counts as a choice; the salesperson is no longer asked for.
 */
function migrateCheckout(saved: unknown): Checkout {
  const raw = { ...((saved as Record<string, unknown>) ?? {}) }
  delete raw.salesperson
  delete raw.gst_option
  if (raw.billing_type !== 'non_gst' && raw.billing_type !== 'gst') raw.billing_type = ''
  return { ...emptyCheckout(), ...(raw as Partial<Checkout>) }
}

function load(): CartState {
  const empty = { lines: [], checkout: emptyCheckout() }
  let raw: string | null = null
  try {
    raw = localStorage.getItem(STORAGE_KEY)
  } catch {
    return empty
  }
  if (!raw) return empty
  try {
    const parsed = JSON.parse(raw) as Partial<CartState>
    if (!Array.isArray(parsed.lines)) throw new Error('lines missing')
    const lines = parsed.lines.filter(
      (l): l is CartLine =>
        !!l && typeof l.id === 'string' && typeof l.title === 'string' && Array.isArray(l.specs) && l.specs.every(validSpec),
    )
    return { lines, checkout: migrateCheckout(parsed.checkout) }
  } catch (err) {
    console.warn('Saved cart could not be read; starting with an empty cart.', err)
    return empty
  }
}

export interface CustomPrefill {
  title: string
  specs: SpecLine[]
  unit_label: string
}

interface CartContextValue extends CartState {
  dispatch: React.Dispatch<Action>
  customItem: CustomPrefill | null
  openCustomItem: (prefill?: Partial<CustomPrefill>) => void
  closeCustomItem: () => void
}

const CartContext = createContext<CartContextValue | null>(null)

export function CartProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, load)
  const [customItem, setCustomItem] = useState<CustomPrefill | null>(null)

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
    } catch {
      /* storage full or blocked: the cart still works for this visit */
    }
  }, [state])

  const value = useMemo<CartContextValue>(
    () => ({
      ...state,
      dispatch,
      customItem,
      openCustomItem: (prefill) => setCustomItem({ title: '', specs: [], unit_label: 'pcs', ...prefill }),
      closeCustomItem: () => setCustomItem(null),
    }),
    [state, customItem],
  )
  return <CartContext.Provider value={value}>{children}</CartContext.Provider>
}

export function useCart(): CartContextValue {
  const ctx = useContext(CartContext)
  if (!ctx) throw new Error('useCart outside CartProvider')
  return ctx
}
