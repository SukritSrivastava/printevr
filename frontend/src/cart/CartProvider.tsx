// Cart lines and the unsaved checkout form (BRD-cart-invoice FR-C5): React state, saved to
// localStorage after every change. What is kept, and for how long, is in ./storage.ts.
import { createContext, useContext, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import type { CartLine, ChangedLine, SpecLine } from '../api/invoiceTypes'
import { type Checkout, emptyCheckout, withoutCustomer } from './checkout'
import { type CartState, FORGET_CUSTOMER_EVENT, customerExpired, loadCart, saveCart } from './storage'

export { DEFAULTED, emptyCheckout, todayIST, type Checkout } from './checkout'
export { STORAGE_KEY, type CartState } from './storage'

/** How often an open page checks whether the customer details have expired. */
const EXPIRY_CHECK_MS = 60 * 1000

export function newId(): string {
  const c = globalThis.crypto as Crypto | undefined
  if (c?.randomUUID) return c.randomUUID()
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (ch) => {
    const r = (Math.random() * 16) | 0
    return (ch === 'x' ? r : (r & 0x3) | 0x8).toString(16)
  })
}

type Action =
  | { type: 'add'; lines: CartLine[] }
  | { type: 'addChild'; parentId: string; line: CartLine }
  | { type: 'update'; id: string; patch: Partial<CartLine> }
  | { type: 'remove'; id: string }
  | { type: 'move'; id: string; by: -1 | 1 }
  | { type: 'clear' }
  | { type: 'checkout'; patch: Partial<Checkout> }
  | { type: 'fresh'; changes: ChangedLine[] }
  | { type: 'forgetCustomer' }

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

/** Lines that print under their article (no number, no rule between them). */
export const isChild = (l: CartLine) => l.source === 'addon' || l.source === 'customisation'

/** A customisation charged per unit is always for its article's quantity. */
function syncPerUnit(lines: CartLine[]): CartLine[] {
  const byId = new Map(lines.map((l) => [l.id, l]))
  return lines.map((l) => {
    const parent = l.charge_basis === 'per_unit' && l.parent_id ? byId.get(l.parent_id) : undefined
    return parent && parent.quantity !== l.quantity ? { ...l, quantity: parent.quantity } : l
  })
}

function reducer(state: CartState, action: Action): CartState {
  switch (action.type) {
    case 'add':
      return { ...state, lines: [...state.lines, ...action.lines] }
    case 'addChild': {
      // After the article and the lines already under it.
      const at = state.lines.findIndex((l) => l.id === action.parentId)
      if (at < 0) return state
      let end = at + 1
      while (end < state.lines.length && state.lines[end].parent_id === action.parentId) end++
      return { ...state, lines: syncPerUnit([...state.lines.slice(0, end), action.line, ...state.lines.slice(end)]) }
    }
    case 'update':
      return { ...state, lines: syncPerUnit(state.lines.map((l) => (l.id === action.id ? { ...l, ...action.patch } : l))) }
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
      return { ...state, lines: syncPerUnit(state.lines.map((l) => (byId.has(l.id) ? withFreshPrice(l, byId.get(l.id)!) : l))) }
    }
    case 'forgetCustomer':
      return { ...state, checkout: withoutCustomer(state.checkout) }
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
  const [initial] = useState(() => loadCart())
  const [state, dispatch] = useReducer(reducer, initial.state)
  const [customItem, setCustomItem] = useState<CustomPrefill | null>(null)
  // When the checkout form last changed. Only a change to the form restarts the retention
  // period: opening the page, or re-pricing the lines when the cart opens, doesn't.
  const changedAt = useRef(initial.changedAt)
  const savedCheckout = useRef(state.checkout)

  useEffect(() => {
    if (state.checkout !== savedCheckout.current) {
      savedCheckout.current = state.checkout
      changedAt.current = Date.now()
    }
    saveCart(state, changedAt.current)
  }, [state])

  // Customer details expire in an open page too, and go at once on Sign out.
  const checkout = useRef(state.checkout)
  checkout.current = state.checkout
  useEffect(() => {
    const check = () => {
      if (customerExpired(checkout.current, changedAt.current)) dispatch({ type: 'forgetCustomer' })
    }
    const forget = () => dispatch({ type: 'forgetCustomer' })
    const timer = setInterval(check, EXPIRY_CHECK_MS)
    globalThis.addEventListener(FORGET_CUSTOMER_EVENT, forget)
    return () => {
      clearInterval(timer)
      globalThis.removeEventListener(FORGET_CUSTOMER_EVENT, forget)
    }
  }, [])

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
