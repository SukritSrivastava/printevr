// "+ Add customisation" on a cart line: anything out of the box the customer wants on this
// article. With no extra charge it is listed under CUSTOMISATIONS:- on the article; with a
// charge it becomes its own row under the article (per unit, following the article's
// quantity, or once for the order), so it counts in the totals and GST of every document.
import { useState } from 'react'
import type { CartLine, ChargeBasis } from '../api/invoiceTypes'
import { newId, useCart } from '../cart/CartProvider'
import { money } from '../lib/format'
import { fromPaise, lineSubtotal, toPaise } from '../lib/invoiceMoney'
import { Dialog } from './Dialog'
import { useToast } from './Toast'

/** The row title adds " (customisation)", and titles are at most 80 characters. */
export const CUSTOMISATION_MAX = 64
const SUFFIX = ' (customisation)'
const FREE_MAX = 8

type Charge = 'none' | ChargeBasis

export function AddCustomisationDialog({ line, onClose }: { line: CartLine; onClose: () => void }) {
  const { dispatch } = useCart()
  const toast = useToast()
  const [text, setText] = useState('')
  const [details, setDetails] = useState('')
  const [charge, setCharge] = useState<Charge>('per_unit')
  const [price, setPrice] = useState('')
  const [tried, setTried] = useState(false)

  const paise = toPaise(price)
  const freeFull = line.customisations.length >= FREE_MAX
  const errors = {
    text: text.trim() ? null : 'Describe the customisation',
    price: charge === 'none' || (paise !== null && paise >= 1n && paise <= 1_000_000_000n) ? null : 'Enter the charge (₹, up to 2 decimals)',
    full: charge === 'none' && freeFull ? `This line already lists ${FREE_MAX} customisations; add this one with a charge or edit the list` : null,
  }
  const valid = Object.values(errors).every((e) => e === null)
  const quantity = charge === 'per_unit' ? line.quantity : 1
  const total = charge !== 'none' && paise !== null ? fromPaise(lineSubtotal(quantity, fromPaise(paise))) : null

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    setTried(true)
    if (!valid) return
    const what = text.trim()
    const more = details.trim()
    if (charge === 'none') {
      dispatch({
        type: 'update',
        id: line.id,
        patch: { customisations: [...line.customisations, { label: more ? what : null, value: more || what, emphasis: false }] },
      })
      toast(`Customisation added to ${line.title}`)
    } else {
      const row: CartLine = {
        id: newId(),
        source: 'customisation',
        parent_id: line.id,
        charge_basis: charge,
        calc_request: null,
        title: `${what}${SUFFIX}`,
        specs: [{ label: 'For', value: line.title, emphasis: false }, ...(more ? [{ label: 'Details', value: more, emphasis: false }] : [])],
        customisations: [],
        quantity,
        unit_label: charge === 'per_unit' ? line.unit_label : 'order',
        middle: { kind: 'none' },
        catalogue_unit_price: null,
        unit_price: fromPaise(paise!),
        warnings: [],
      }
      dispatch({ type: 'addChild', parentId: line.id, line: row })
      toast(`${what} added: ${money(total!)}`)
    }
    onClose()
  }

  const err = (key: keyof typeof errors, id?: string) =>
    tried && errors[key] ? (
      <p id={id} role="alert" className="text-sm text-stop">
        {errors[key]}
      </p>
    ) : null

  const option = (value: Charge, label: string, hint: string) => (
    <label className={`flex cursor-pointer items-start gap-3 rounded-md px-3 py-2 ring-1 ${charge === value ? 'bg-cyan-wash ring-cyan' : 'ring-rule'}`}>
      <input type="radio" name="customisation-charge" className="mt-1 accent-cyan" checked={charge === value} onChange={() => setCharge(value)} />
      <span className="flex flex-col">
        <span className="font-semibold">{label}</span>
        <span className="text-sm text-ink-soft">{hint}</span>
      </span>
    </label>
  )

  return (
    <Dialog title={`Customise: ${line.title}`} onClose={onClose}>
      <form onSubmit={submit} className="flex flex-col gap-4" noValidate>
        <div className="flex flex-col gap-1">
          <label htmlFor="customisation-text" className="text-sm font-semibold text-ink-soft">
            Customisation
          </label>
          <input
            id="customisation-text"
            className="field"
            maxLength={CUSTOMISATION_MAX}
            placeholder="e.g. Gold foil logo on the lid"
            value={text}
            onChange={(e) => setText(e.target.value)}
            aria-invalid={tried && errors.text ? 'true' : undefined}
          />
          {err('text')}
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor="customisation-details" className="text-sm font-semibold text-ink-soft">
            Details (optional)
          </label>
          <input
            id="customisation-details"
            className="field"
            maxLength={120}
            placeholder="e.g. 2 × 1 in, front only, Pantone 871C"
            value={details}
            onChange={(e) => setDetails(e.target.value)}
          />
        </div>
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1 text-sm font-semibold text-ink-soft">Charge</legend>
          {option('per_unit', `Per ${singular(line.unit_label)}`, `Charged on all ${line.quantity} ${line.unit_label}; follows the article's quantity`)}
          {option('per_order', 'Once for the order', 'A one-time charge, e.g. a die, block or setup')}
          {option('none', 'No extra charge', 'Listed under CUSTOMISATIONS on the article')}
        </fieldset>
        {charge !== 'none' && (
          <div className="flex flex-col gap-1">
            <label htmlFor="customisation-price" className="text-sm font-semibold text-ink-soft">
              {charge === 'per_unit' ? `Charge per ${singular(line.unit_label)} (₹)` : 'Charge for the order (₹)'}
            </label>
            <input
              id="customisation-price"
              className="field"
              inputMode="decimal"
              value={price}
              onChange={(e) => setPrice(e.target.value.replace(/[^\d.]/g, ''))}
              aria-invalid={tried && errors.price ? 'true' : undefined}
            />
            {err('price')}
            {total && (
              <p className="text-sm text-ink-soft" data-testid="customisation-total">
                Adds {money(total)} to the order{charge === 'per_unit' ? ` (${line.quantity} × ${money(fromPaise(paise!))})` : ''}, before GST.
              </p>
            )}
          </div>
        )}
        {err('full')}
        <div className="flex justify-end gap-2">
          <button type="button" className="rounded-md px-4 py-2 font-semibold ring-1 ring-rule" onClick={onClose} data-close>
            Cancel
          </button>
          <button type="submit" className="rounded-md bg-ink px-4 py-2 font-semibold text-stock">
            Add customisation
          </button>
        </div>
      </form>
    </Dialog>
  )
}

/** "boxes" -> "box", "pcs" -> "pc", "rolls" -> "roll"; leaves anything else alone. */
export function singular(unit: string): string {
  const u = unit.trim()
  if (/(x|ch|sh|ss)es$/i.test(u)) return u.slice(0, -2)
  if (/s$/i.test(u) && !/ss$/i.test(u)) return u.slice(0, -1)
  return u
}
