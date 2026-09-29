import type { Checkout } from '../cart/CartProvider'
import { useCart } from '../cart/CartProvider'
import { money } from '../lib/format'
import { fromPaise, invoiceMoney, suggestedSaving, toPaise, type MoneySettings } from '../lib/invoiceMoney'

const PHONE = /^[0-9 +-]{7,20}$/

/** FR-P1 field rules; returns an error per field (empty object = valid). */
export function checkoutErrors(c: Checkout, billNoRequired = false): Partial<Record<keyof Checkout, string>> {
  const e: Partial<Record<keyof Checkout, string>> = {}
  if (!c.business_name.trim()) e.business_name = 'Enter the business name'
  if (!c.address.trim()) e.address = 'Enter the address'
  if (!PHONE.test(c.phone.trim())) e.phone = '7–20 digits, spaces, + or -'
  if (billNoRequired && !c.bill_no) e.bill_no = 'Enter the Bill No'
  else if (c.bill_no && !/^[1-9]\d{0,6}$/.test(c.bill_no)) e.bill_no = 'Whole number from 1'
  if (!/^\d{4}-\d{2}-\d{2}$/.test(c.invoice_date)) e.invoice_date = 'Pick a date'
  if (c.saving_amount && toPaise(c.saving_amount) === null) e.saving_amount = 'Amount, up to 2 decimals'
  return e
}

interface FieldProps {
  id: keyof Checkout
  label: string
  max?: number
  optional?: boolean
  error?: string
  showError: boolean
  inputMode?: 'numeric' | 'decimal' | 'tel' | 'text'
  type?: string
  autoComplete?: string
}

function Field({ id, label, max, optional, error, showError, inputMode, type, autoComplete }: FieldProps) {
  const { checkout, dispatch } = useCart()
  const invalid = showError && !!error
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={`checkout-${id}`} className="text-sm font-semibold text-ink-soft">
        {label} {optional && <span className="font-normal">(optional)</span>}
      </label>
      <input
        id={`checkout-${id}`}
        className="field"
        type={type ?? 'text'}
        maxLength={max}
        inputMode={inputMode}
        autoComplete={autoComplete ?? 'off'}
        value={checkout[id]}
        onChange={(e) => dispatch({ type: 'checkout', patch: { [id]: e.target.value } })}
        aria-invalid={invalid ? 'true' : undefined}
        aria-describedby={invalid ? `checkout-${id}-error` : undefined}
      />
      {invalid && (
        <p id={`checkout-${id}-error`} className="text-sm text-stop">
          {error}
        </p>
      )}
    </div>
  )
}

export function CheckoutForm({ settings, showErrors, billNoRequired }: { settings: MoneySettings; showErrors: boolean; billNoRequired: boolean }) {
  const { checkout, lines, dispatch } = useCart()
  const errors = checkoutErrors(checkout, billNoRequired)
  const withGst = checkout.billing_type === 'with_gst'
  const m = invoiceMoney(lines, withGst, settings)
  const suggested = suggestedSaving(lines)
  const advancePct = settings.advancePct
  const f = (key: keyof Checkout) => ({ error: errors[key], showError: showErrors || !!checkout[key] })

  return (
    <section aria-labelledby="checkout-title" className="flex flex-col gap-4 rounded-md bg-stock p-4 shadow-sm ring-1 ring-rule">
      <h2 id="checkout-title" className="type-expanded text-lg font-bold">
        Ship To
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="business_name" label="Business name" max={60} autoComplete="organization" {...f('business_name')} />
        <Field id="contact_person" label="Contact person" max={60} optional autoComplete="name" {...f('contact_person')} />
        <div className="sm:col-span-2">
          <Field id="address" label="Address" max={140} autoComplete="street-address" {...f('address')} />
        </div>
        <Field id="phone" label="Phone" max={20} inputMode="tel" type="tel" autoComplete="tel" {...f('phone')} />
      </div>

      <h2 className="type-expanded mt-2 text-lg font-bold">Invoice</h2>
      <div className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-1">
          <Field id="bill_no" label="Bill No" inputMode="numeric" {...f('bill_no')} />
          {billNoRequired ? (
            <p className="text-xs text-ink-soft">Goes up by one after each print on this device.</p>
          ) : (
            !checkout.bill_no && <p className="text-xs text-ink-soft">Blank: the next number is assigned on print.</p>
          )}
        </div>
        <Field id="invoice_date" label="Invoice date" type="date" {...f('invoice_date')} />
      </div>
      <fieldset className="flex flex-wrap gap-x-5 gap-y-2">
        <legend className="mb-1.5 text-sm font-semibold text-ink-soft">Billing type</legend>
        {(
          [
            ['without_gst', 'Without GST billing'],
            ['with_gst', 'With GST billing'],
          ] as const
        ).map(([value, label]) => (
          <label key={value} className="flex items-center gap-2">
            <input
              type="radio"
              name="billing_type"
              className="accent-cyan"
              checked={checkout.billing_type === value}
              onChange={() => dispatch({ type: 'checkout', patch: { billing_type: value } })}
            />
            {label}
          </label>
        ))}
      </fieldset>
      <div className="flex flex-col gap-1">
        <Field id="saving_amount" label="Saving amount (₹)" optional inputMode="decimal" {...f('saving_amount')} />
        {suggested > 0n && (
          <button
            type="button"
            className="self-start text-sm text-cyan-deep underline"
            onClick={() => dispatch({ type: 'checkout', patch: { saving_amount: fromPaise(suggested).replace(/\.00$/, '') } })}
          >
            Use suggested ({money(fromPaise(suggested))})
          </button>
        )}
        <p className="text-xs text-ink-soft">Blank or 0 hides the saving block on the invoice.</p>
      </div>

      <dl className="flex flex-col gap-1.5 rounded-md bg-sheet p-3" aria-label="Invoice summary">
        <div className="flex justify-between">
          <dt>Total</dt>
          <dd>{money(fromPaise(m.total))}</dd>
        </div>
        {withGst && (
          <div className="flex justify-between">
            <dt>GST ({(Number(settings.gstRate) * 100).toFixed(0)}%)</dt>
            <dd>{money(fromPaise(m.gst))}</dd>
          </div>
        )}
        <div className="flex justify-between font-semibold">
          <dt>Payable</dt>
          <dd data-testid="payable">{money(fromPaise(m.payable))}</dd>
        </div>
        <div className="flex justify-between text-sm text-ink-soft">
          <dt>{advancePct}% before printing</dt>
          <dd>{money(fromPaise(m.advance))}</dd>
        </div>
        <div className="flex justify-between text-sm text-ink-soft">
          <dt>{100 - Number(advancePct)}% before dispatch</dt>
          <dd>{money(fromPaise(m.balance))}</dd>
        </div>
      </dl>
    </section>
  )
}
