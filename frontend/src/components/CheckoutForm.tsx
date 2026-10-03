import type { BillType, GstFieldDefaults } from '../api/invoiceTypes'
import type { Checkout } from '../cart/CartProvider'
import { useCart } from '../cart/CartProvider'
import { type CheckoutErrors, advancePercent, gstWarnings, lineHsn, withDefault } from '../lib/documents'
import { money } from '../lib/format'
import { chosenSlab, fromPaise, invoiceMoney, suggestedSaving, type MoneySettings } from '../lib/invoiceMoney'

export const SLAB_PLACEHOLDER = 'Select GST slab'

export interface CheckoutSettings extends MoneySettings {
  gstDefaults: GstFieldDefaults
  hsnCodes: Record<string, string>
  stateCode: string
  /** false: invoices print no payment details, so the inputs that only fed them are hidden. */
  printPaymentDetails?: boolean
  /** true: Non-GST invoices print the payment summary (advance %), so the split is offered. */
  printPaymentSummary?: boolean
}

type TextKey = { [K in keyof Checkout]: Checkout[K] extends string | null ? K : never }[keyof Checkout]

interface FieldProps {
  id: TextKey
  label: string
  max?: number
  optional?: boolean
  error?: string
  showError: boolean
  inputMode?: 'numeric' | 'decimal' | 'tel' | 'text'
  type?: string
  autoComplete?: string
  /** Shown while the field is untouched (null): the config default. */
  fallback?: string
  upper?: boolean
}

function Field({ id, label, max, optional, error, showError, inputMode, type, autoComplete, fallback, upper }: FieldProps) {
  const { checkout, dispatch } = useCart()
  const invalid = showError && !!error
  const value = withDefault(checkout[id] as string | null, fallback)
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={`checkout-${id}`} className="text-sm font-semibold text-ink-soft">
        {label} {optional && <span className="font-normal">(optional)</span>}
      </label>
      <input
        id={`checkout-${id}`}
        className={`field${upper ? ' uppercase' : ''}`}
        type={type ?? 'text'}
        maxLength={max}
        inputMode={inputMode}
        autoComplete={autoComplete ?? 'off'}
        value={value}
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

const BILL_TYPES: [BillType, string][] = [
  ['non_gst', 'Non-GST invoice'],
  ['gst', 'GST invoice'],
]

export function CheckoutForm({
  settings,
  errors,
  showErrors,
  billNoRequired,
  quoteNoRequired,
  onBillType,
}: {
  settings: CheckoutSettings
  errors: CheckoutErrors
  showErrors: boolean
  billNoRequired: boolean
  /** Without storage the quotation number is typed too (it counts up on this device). */
  quoteNoRequired: boolean
  onBillType: (next: BillType) => void
}) {
  const { checkout, lines, dispatch } = useCart()
  const gst = checkout.billing_type === 'gst'
  const slab = chosenSlab(checkout.billing_type, checkout.gst_slab, settings.slabGroups)
  const advancePct = advancePercent(checkout, settings.advancePct)
  const m = invoiceMoney(lines, slab?.components ?? [], { ...settings, advancePct: errors.advance_pct ? '100' : advancePct })
  const suggested = suggestedSaving(lines)
  const warnings = gstWarnings(checkout, slab, lines, settings.hsnCodes, settings.stateCode)
  const f = (key: keyof Checkout) => ({ error: errors[key], showError: showErrors || !!checkout[key] })
  const patch = (p: Partial<Checkout>) => dispatch({ type: 'checkout', patch: p })
  const paymentDetails = settings.printPaymentDetails !== false
  // The split prints in the reference's payment box or in the payment summary.
  const splitShown = paymentDetails || settings.printPaymentSummary === true

  return (
    <section aria-labelledby="checkout-title" className="flex flex-col gap-4 rounded-md bg-stock p-4 shadow-sm ring-1 ring-rule">
      <fieldset className="flex flex-wrap gap-x-5 gap-y-2">
        <legend className="mb-1.5 text-sm font-semibold text-ink-soft">Bill type</legend>
        {BILL_TYPES.map(([value, label]) => (
          <label key={value} className="flex items-center gap-2">
            <input
              type="radio"
              name="billing_type"
              className="accent-cyan"
              checked={checkout.billing_type === value}
              onChange={() => onBillType(value)}
            />
            {label}
          </label>
        ))}
        {!checkout.billing_type && <p className="w-full text-xs text-ink-soft">Choose one to print an invoice. A quotation doesn't need it.</p>}
      </fieldset>

      {gst && (
        <div className="flex flex-col gap-1 sm:max-w-sm">
          <label htmlFor="checkout-gst_slab" className="text-sm font-semibold text-ink-soft">
            GST slab
          </label>
          <select
            id="checkout-gst_slab"
            className="field"
            required
            value={slab ? slab.key : ''}
            onChange={(e) => patch({ gst_slab: e.target.value })}
            aria-describedby={slab ? undefined : 'checkout-gst_slab-hint'}
          >
            <option value="" disabled>
              {SLAB_PLACEHOLDER}
            </option>
            {settings.slabGroups.map((g) => (
              <optgroup key={g.key} label={g.label}>
                {g.slabs.map((s) => (
                  <option key={s.key} value={s.key}>
                    {s.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {!slab && (
            <p id="checkout-gst_slab-hint" className="text-xs text-ink-soft">
              {settings.slabGroups.length ? 'Required for a GST invoice.' : "GST slabs couldn't be loaded. Reload the page."}
            </p>
          )}
        </div>
      )}

      <h2 id="checkout-title" className="type-expanded mt-2 text-lg font-bold">
        {gst ? 'Buyer Info (Billed to)' : 'Ship To'}
      </h2>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field id="business_name" label={gst ? 'Buyer name' : 'Business name'} max={60} autoComplete="organization" {...f('business_name')} />
        {gst ? (
          <Field id="buyer_gstin" label="Buyer GSTIN" max={15} optional upper {...f('buyer_gstin')} />
        ) : (
          <Field id="contact_person" label="Contact person" max={60} optional autoComplete="name" {...f('contact_person')} />
        )}
        <div className="sm:col-span-2">
          <Field id="address" label="Address" max={140} optional={gst} autoComplete="street-address" {...f('address')} />
        </div>
        <Field id="phone" label="Phone" max={20} optional={gst} inputMode="tel" type="tel" autoComplete="tel" {...f('phone')} />
      </div>
      {!checkout.billing_type && <p className="-mt-2 text-xs text-ink-soft">Optional on a quotation.</p>}

      {gst && (
        <>
          <h2 className="type-expanded mt-2 text-lg font-bold">Consignee Info (Shipped to)</h2>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="accent-cyan"
              checked={checkout.consignee_same}
              onChange={(e) => patch({ consignee_same: e.target.checked })}
            />
            Same as buyer
          </label>
          {!checkout.consignee_same && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field id="consignee_name" label="Consignee name" max={60} {...f('consignee_name')} />
              <Field id="consignee_gstin" label="Consignee GSTIN" max={15} optional upper {...f('consignee_gstin')} />
              <div className="sm:col-span-2">
                <Field id="consignee_address" label="Consignee address" max={140} optional {...f('consignee_address')} />
              </div>
              <Field id="consignee_phone" label="Consignee phone" max={20} optional inputMode="tel" type="tel" {...f('consignee_phone')} />
            </div>
          )}

          <h2 className="type-expanded mt-2 text-lg font-bold">Delivery and transport</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="delivery_terms" label="Delivery Terms" max={60} optional {...f('delivery_terms')} />
            {paymentDetails && (
              <Field id="payment_terms" label="Payment Terms" max={40} optional fallback={settings.gstDefaults.payment_terms} {...f('payment_terms')} />
            )}
            <Field id="po_date" label="P.O Date" type="date" optional {...f('po_date')} />
            <Field id="gr_rr_no" label="GR/RR No" max={30} optional {...f('gr_rr_no')} />
            <Field id="transport" label="Transport" max={40} optional fallback={settings.gstDefaults.transport} {...f('transport')} />
            <Field id="vehicle_no" label="Vehicle no." max={20} optional {...f('vehicle_no')} />
            <Field id="eway_bill_no" label="E-Way Bill No." max={20} optional {...f('eway_bill_no')} />
            <Field id="station" label="Station" max={40} optional fallback={settings.gstDefaults.station} {...f('station')} />
          </div>
          <p className="-mt-2 text-xs text-ink-soft">Blank fields print blank.</p>

          <h2 className="type-expanded mt-2 text-lg font-bold">HSN codes</h2>
          <ul className="flex flex-col gap-2">
            {lines.map((line, i) => (
              <li key={line.id} className="flex flex-wrap items-center justify-between gap-2">
                <label htmlFor={`hsn-${line.id}`} className="min-w-0 flex-1 truncate text-sm">
                  {i + 1}. {line.title}
                </label>
                <input
                  id={`hsn-${line.id}`}
                  className="field w-32"
                  inputMode="numeric"
                  maxLength={12}
                  aria-label={`HSN code for ${line.title}`}
                  value={lineHsn(line, lines, settings.hsnCodes)}
                  onChange={(e) =>
                    dispatch({ type: 'update', id: line.id, patch: { hsn_code: e.target.value.replace(/[^0-9A-Za-z ]/g, '') } })
                  }
                />
              </li>
            ))}
          </ul>
        </>
      )}

      {warnings.length > 0 && (
        <ul role="status" aria-label="GST invoice warnings" className="flex flex-col gap-1 rounded-md bg-warn-wash px-3 py-2 text-sm text-warn">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}

      <h2 className="type-expanded mt-2 text-lg font-bold">Numbers and date</h2>
      <div className="grid grid-cols-2 gap-3">
        {checkout.billing_type && (
          <div className="flex flex-col gap-1">
            <Field id="bill_no" label="Bill No" inputMode="numeric" {...f('bill_no')} />
            {billNoRequired ? (
              <p className="text-xs text-ink-soft">Goes up by one after each print on this device.</p>
            ) : (
              !checkout.bill_no && <p className="text-xs text-ink-soft">Blank: the next number is assigned on print.</p>
            )}
          </div>
        )}
        {quoteNoRequired && <Field id="quote_no" label="Quote No" inputMode="numeric" {...f('quote_no')} />}
        <Field id="invoice_date" label="Date" type="date" {...f('invoice_date')} />
      </div>

      <div className="flex flex-col gap-1">
        <Field id="saving_amount" label="Saving amount (₹)" optional inputMode="decimal" {...f('saving_amount')} />
        {suggested > 0n && (
          <button
            type="button"
            className="self-start text-sm text-cyan-deep underline"
            onClick={() => patch({ saving_amount: fromPaise(suggested).replace(/\.00$/, '') })}
          >
            Use suggested ({money(fromPaise(suggested))})
          </button>
        )}
        <p className="text-xs text-ink-soft">Blank or 0 hides the saving block (quotations and Non-GST invoices).</p>
      </div>

      {splitShown && (
        <fieldset className="flex flex-col gap-2">
          <legend className="mb-1.5 text-sm font-semibold text-ink-soft">Payment</legend>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              className="accent-cyan"
              checked={checkout.split_payment}
              onChange={(e) => patch({ split_payment: e.target.checked })}
            />
            Split payment (part before printing, the rest before dispatch)
          </label>
          {checkout.split_payment ? (
            <div className="sm:max-w-xs">
              <Field id="advance_pct" label="Before printing (%)" inputMode="decimal" max={6} fallback={settings.advancePct} {...f('advance_pct')} />
            </div>
          ) : (
            <p className="text-xs text-ink-soft">Off: the invoice asks for the full amount before printing.</p>
          )}
        </fieldset>
      )}

      <dl className="flex flex-col gap-1.5 rounded-md bg-sheet p-3" aria-label="Invoice summary">
        <div className="flex justify-between">
          <dt>{gst ? 'Sub-total' : 'Total'}</dt>
          <dd>{money(fromPaise(m.total))}</dd>
        </div>
        {m.taxes.map((t) => (
          <div key={t.name} className="flex justify-between">
            <dt>
              {t.name} ({t.rate}%)
            </dt>
            <dd>{money(fromPaise(t.amount))}</dd>
          </div>
        ))}
        <div className="flex justify-between font-semibold">
          <dt>{gst ? 'Total (after tax)' : 'Payable'}</dt>
          <dd data-testid="payable">{money(fromPaise(m.payable))}</dd>
        </div>
        {!splitShown ? null : checkout.split_payment && !errors.advance_pct ? (
          <>
            <div className="flex justify-between text-sm text-ink-soft">
              <dt>{advancePct}% before printing</dt>
              <dd>{money(fromPaise(m.advance))}</dd>
            </div>
            <div className="flex justify-between text-sm text-ink-soft">
              <dt>{Number((100 - Number(advancePct)).toFixed(2))}% before dispatch</dt>
              <dd>{money(fromPaise(m.balance))}</dd>
            </div>
          </>
        ) : (
          <div className="flex justify-between text-sm text-ink-soft">
            <dt>Full payment before printing</dt>
            <dd>{money(fromPaise(m.payable))}</dd>
          </div>
        )}
      </dl>
    </section>
  )
}
