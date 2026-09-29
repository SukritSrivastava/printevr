import { useState } from 'react'
import type { PaymentInput, PaymentMode } from '../api/invoiceTypes'
import { todayIST } from '../cart/CartProvider'
import { money } from '../lib/format'
import { fromPaise, toPaise } from '../lib/invoiceMoney'
import { Dialog } from './Dialog'

const MODES: [PaymentMode, string][] = [
  ['upi', 'UPI'],
  ['cash', 'Cash'],
  ['bank_transfer', 'Bank transfer'],
  ['cheque', 'Cheque'],
]

interface Row {
  amount: string
  date: string
  mode: PaymentMode
}

interface Props {
  title: string
  /** What is still owed: the payable amount, or the remaining amount when recording a payment. */
  limit: bigint
  maxRows: number
  confirmLabel: string
  busy: boolean
  error?: string | null
  onConfirm: (payments: PaymentInput[]) => void
  onClose: () => void
}

/** Amount received (defaults to everything owed), date (today, IST) and mode (FR-P4). */
export function PaymentDialog({ title, limit, maxRows, confirmLabel, busy, error, onConfirm, onClose }: Props) {
  const [rows, setRows] = useState<Row[]>([{ amount: fromPaise(limit).replace(/\.00$/, ''), date: todayIST(), mode: 'upi' }])
  const set = (i: number, patch: Partial<Row>) => setRows(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  const amounts = rows.map((r) => toPaise(r.amount))
  const received = amounts.reduce<bigint>((s, a) => s + (a ?? 0n), 0n)
  const badRow = amounts.some((a) => a === null || a <= 0n) || rows.some((r) => !r.date)
  const problem =
    received === 0n
      ? 'Enter the amount received'
      : received > limit
        ? `That's more than the ${money(fromPaise(limit))} owed`
        : badRow
          ? 'Every payment needs an amount above 0 and a date'
          : null

  return (
    <Dialog title={title} onClose={onClose}>
      <form
        className="flex flex-col gap-4"
        onSubmit={(e) => {
          e.preventDefault()
          if (problem || busy) return
          onConfirm(rows.map((r) => ({ amount: r.amount, date: r.date, mode: r.mode, note: null })))
        }}
      >
        {rows.map((r, i) => (
          <fieldset key={i} className="grid grid-cols-2 gap-2 rounded-md border border-rule p-3">
            <legend className="px-1 text-sm font-semibold text-ink-soft">Payment {i + 1}</legend>
            <div className="col-span-2 flex flex-col gap-1">
              <label htmlFor={`pay-amount-${i}`} className="text-sm text-ink-soft">
                Amount received (₹)
              </label>
              <input
                id={`pay-amount-${i}`}
                className="field type-expanded font-semibold"
                inputMode="decimal"
                value={r.amount}
                onChange={(e) => set(i, { amount: e.target.value.replace(/[^\d.]/g, '') })}
              />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`pay-date-${i}`} className="text-sm text-ink-soft">
                Date received
              </label>
              <input id={`pay-date-${i}`} type="date" className="field" value={r.date} onChange={(e) => set(i, { date: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`pay-mode-${i}`} className="text-sm text-ink-soft">
                Mode <span className="text-xs">(not printed)</span>
              </label>
              <select id={`pay-mode-${i}`} className="field" value={r.mode} onChange={(e) => set(i, { mode: e.target.value as PaymentMode })}>
                {MODES.map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </div>
            {rows.length > 1 && (
              <button type="button" className="col-span-2 justify-self-start text-sm text-stop" onClick={() => setRows(rows.filter((_, j) => j !== i))}>
                Remove payment {i + 1}
              </button>
            )}
          </fieldset>
        ))}
        {rows.length < maxRows && (
          <button
            type="button"
            className="self-start rounded-md border border-dashed border-ink-soft px-3 py-1.5 text-sm"
            onClick={() => setRows([...rows, { amount: '', date: todayIST(), mode: 'upi' }])}
          >
            + Add another payment
          </button>
        )}
        <p className="font-semibold" aria-live="polite">
          Received {money(fromPaise(received))} of {money(fromPaise(limit))}
        </p>
        {problem && <p className="text-sm text-stop">{problem}</p>}
        {error && (
          <p role="alert" className="text-sm text-stop">
            {error}
          </p>
        )}
        <button type="submit" disabled={!!problem || busy} className="rounded-md bg-ink px-4 py-3 font-semibold text-stock disabled:opacity-50">
          {busy ? 'Preparing invoice…' : confirmLabel}
        </button>
      </form>
    </Dialog>
  )
}
