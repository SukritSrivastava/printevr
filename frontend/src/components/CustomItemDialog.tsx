import { useState } from 'react'
import type { CartLine, Middle, SpecLine } from '../api/invoiceTypes'
import { newId, useCart } from '../cart/CartProvider'
import { toPaise } from '../lib/invoiceMoney'
import { Dialog } from './Dialog'
import { MiddleEditor } from './MiddleEditor'
import { SpecListEditor } from './SpecListEditor'
import { useToast } from './Toast'

/** A job the calculator can't price, typed by hand (FR-C4). */
export function CustomItemDialog() {
  const { customItem, closeCustomItem, dispatch } = useCart()
  const toast = useToast()
  const [title, setTitle] = useState(customItem?.title ?? '')
  const [specs, setSpecs] = useState<SpecLine[]>(customItem?.specs ?? [])
  const [customisations, setCustomisations] = useState<SpecLine[]>([])
  const [quantity, setQuantity] = useState('')
  const [unitLabel, setUnitLabel] = useState(customItem?.unit_label ?? 'pcs')
  const [price, setPrice] = useState('')
  const [middle, setMiddle] = useState<Middle>({ kind: 'none' })
  const [tried, setTried] = useState(false)

  if (!customItem) return null

  const qty = Number(quantity)
  const errors = {
    title: title.trim() ? null : 'Enter a title',
    quantity: Number.isInteger(qty) && qty >= 1 && qty <= 10_000_000 ? null : 'Whole number from 1',
    unit: unitLabel.trim() ? null : 'Enter a unit, e.g. boxes',
    price: (() => {
      const p = toPaise(price)
      return p !== null && p >= 1n && p <= 1_000_000_000n ? null : 'Price above 0, up to 2 decimals'
    })(),
    specs: [...specs, ...customisations].some((s) => !s.value.trim()) ? 'Every row needs a value' : null,
  }
  const valid = Object.values(errors).every((e) => e === null)

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setTried(true)
    if (!valid) return
    const line: CartLine = {
      id: newId(),
      source: 'custom',
      parent_id: null,
      calc_request: null,
      title: title.trim(),
      specs: specs.map((s) => ({ ...s, label: s.label?.trim() || null, value: s.value.trim() })),
      customisations: customisations.map((s) => ({ ...s, label: s.label?.trim() || null, value: s.value.trim() })),
      quantity: qty,
      unit_label: unitLabel.trim(),
      middle,
      catalogue_unit_price: null,
      unit_price: price.trim(),
      warnings: [],
    }
    dispatch({ type: 'add', lines: [line] })
    closeCustomItem()
    toast('Custom item added to cart')
  }

  const err = (key: keyof typeof errors) =>
    tried && errors[key] ? (
      <p className="text-sm text-stop" role="alert">
        {errors[key]}
      </p>
    ) : null

  return (
    <Dialog title="Add custom item" onClose={closeCustomItem} wide>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <div className="flex flex-col gap-1">
          <label htmlFor="custom-title" className="text-sm font-semibold text-ink-soft">
            Title
          </label>
          <input id="custom-title" className="field" maxLength={80} value={title} onChange={(e) => setTitle(e.target.value)} />
          {err('title')}
        </div>
        <SpecListEditor legend="Specs" items={specs} max={12} onChange={setSpecs} />
        <SpecListEditor legend="Customisations" items={customisations} max={8} onChange={setCustomisations} />
        {err('specs')}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          <div className="flex flex-col gap-1">
            <label htmlFor="custom-qty" className="text-sm font-semibold text-ink-soft">
              Quantity
            </label>
            <input id="custom-qty" className="field" inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value.replace(/[^\d]/g, ''))} />
            {err('quantity')}
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="custom-unit" className="text-sm font-semibold text-ink-soft">
              Unit label
            </label>
            <input id="custom-unit" className="field" maxLength={20} value={unitLabel} onChange={(e) => setUnitLabel(e.target.value)} />
            {err('unit')}
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor="custom-price" className="text-sm font-semibold text-ink-soft">
              Unit price (₹)
            </label>
            <input id="custom-price" className="field" inputMode="decimal" value={price} onChange={(e) => setPrice(e.target.value.replace(/[^\d.]/g, ''))} />
            {err('price')}
          </div>
        </div>
        <MiddleEditor value={middle} onChange={setMiddle} />
        <button type="submit" className="rounded-md bg-ink px-4 py-2.5 font-semibold text-stock">
          Add to cart
        </button>
      </form>
    </Dialog>
  )
}
