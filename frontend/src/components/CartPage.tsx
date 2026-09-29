import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, NetworkError, calculate } from '../api/client'
import { createInvoice, fetchNextBillNo, staffToken } from '../api/invoices'
import type { CartLine, ChangedLine, InvoiceCreate, InvoiceSettings, PaymentInput } from '../api/invoiceTypes'
import { useCart } from '../cart/CartProvider'
import { saveBlob } from '../lib/download'
import { DEFAULT_MONEY_SETTINGS, invoiceMoney, toPaise, type MoneySettings } from '../lib/invoiceMoney'
import { CartLineCard } from './CartLineCard'
import { CheckoutForm, checkoutErrors } from './CheckoutForm'
import { PaymentDialog } from './PaymentDialog'
import { StaffCancelled, useStaff } from './StaffLoginDialog'
import { useToast } from './Toast'

const STALE = 'Prices changed since these were added. Check before printing.'
const PARALLEL = 4

/** Run tasks with at most `limit` in flight. */
async function pool<T, R>(items: T[], limit: number, task: (item: T) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length)
  let next = 0
  const worker = async () => {
    while (next < items.length) {
      const i = next++
      results[i] = await task(items[i])
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return results
}

/** Re-quote catalogue lines; returns the ones whose billed quantity or catalogue price moved (FR-C6). */
async function freshPrices(lines: CartLine[]): Promise<ChangedLine[]> {
  const catalogue = lines.filter((l) => l.source === 'catalogue' && l.calc_request)
  const results = await pool(catalogue, PARALLEL, async (line) => {
    try {
      const r = await calculate(line.calc_request!)
      if (r.status !== 'success' || !r.data.invoice_lines?.length) return null
      const d = r.data.invoice_lines[0]
      const price = d.catalogue_unit_price ?? d.unit_price
      if (d.quantity === line.quantity && Number(price) === Number(line.catalogue_unit_price)) return null
      return { id: line.id, quantity: d.quantity, catalogue_unit_price: price, warnings: d.warnings }
    } catch {
      return null // offline: the server checks again on print
    }
  })
  return results.filter((r): r is ChangedLine => r !== null)
}

export const lineReady = (l: CartLine) =>
  (toPaise(l.unit_price) ?? 0n) > 0n &&
  !!l.title.trim() &&
  Number(l.quantity) >= 1 &&
  [...l.specs, ...l.customisations].every((s) => s.value.trim()) &&
  (l.middle.kind !== 'note' || !!l.middle.text.trim()) &&
  (l.middle.kind !== 'reference_price' || (toPaise(l.middle.amount) ?? 0n) > 0n)

type Problem = { message: string; retry?: () => void }

export function CartPage({ onCalculator, invoiceSettings }: { onCalculator: () => void; invoiceSettings?: InvoiceSettings }) {
  const { lines, checkout, dispatch, openCustomItem } = useCart()
  const withStaff = useStaff()
  const toast = useToast()
  const [stale, setStale] = useState(false)
  const [changed, setChanged] = useState<Set<string>>(new Set())
  const [settings, setSettings] = useState<MoneySettings>(DEFAULT_MONEY_SETTINGS)
  // Without storage the server can't count bill numbers: the Bill No is typed (and remembered here).
  const storage = invoiceSettings?.storage ?? true
  useEffect(() => {
    if (invoiceSettings?.gst_rate && invoiceSettings.advance_pct) {
      setSettings({ gstRate: invoiceSettings.gst_rate, advancePct: invoiceSettings.advance_pct })
    }
  }, [invoiceSettings])
  const [busy, setBusy] = useState(false)
  const [paying, setPaying] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [printed, setPrinted] = useState<number | null>(null)
  const busyRef = useRef(false)

  const applyChanges = useCallback(
    (changes: ChangedLine[]) => {
      if (!changes.length) return
      dispatch({ type: 'fresh', changes })
      setChanged(new Set(changes.map((c) => c.id)))
      setStale(true)
    },
    [dispatch],
  )

  const refreshBillNo = useCallback(async () => {
    const next = await fetchNextBillNo()
    setSettings({ gstRate: next.gst_rate, advancePct: next.advance_pct })
    return next.next_bill_no
  }, [])

  // On open: re-quote every catalogue line once, and pre-fill the bill number if staff are signed in.
  const opened = useRef(false)
  useEffect(() => {
    if (opened.current) return
    opened.current = true
    freshPrices(lines).then(applyChanges)
    if (storage && staffToken()) {
      refreshBillNo()
        .then((n) => {
          if (!checkout.bill_no) dispatch({ type: 'checkout', patch: { bill_no: String(n) } })
        })
        .catch(() => {})
    }
  }, [lines, checkout.bill_no, applyChanges, refreshBillNo, dispatch, storage])

  const m = invoiceMoney(lines, checkout.billing_type === 'with_gst', settings)
  const formOk = Object.keys(checkoutErrors(checkout, !storage)).length === 0
  const ready = lines.length > 0 && lines.every(lineReady) && formOk

  const print = async (mode: 'unpaid' | 'paid', payments: PaymentInput[] = []) => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setProblem(null)
    const body: InvoiceCreate = {
      bill_no: checkout.bill_no ? Number(checkout.bill_no) : null,
      invoice_date: checkout.invoice_date,
      billing_type: checkout.billing_type,
      customer: {
        business_name: checkout.business_name.trim(),
        contact_person: checkout.contact_person.trim(),
        address: checkout.address.trim(),
        phone: checkout.phone.trim(),
      },
      lines,
      payments,
      saving_amount: checkout.saving_amount && toPaise(checkout.saving_amount) ? checkout.saving_amount : null,
      print_mode: mode,
    }
    try {
      const pdf = await withStaff(() => createInvoice(body))
      saveBlob(pdf.blob, pdf.filename)
      setPaying(false)
      setPrinted(pdf.billNo)
      setStale(false)
      setChanged(new Set())
      toast(`Invoice ${pdf.billNo} downloaded`)
      if (storage) {
        refreshBillNo()
          .then((n) => dispatch({ type: 'checkout', patch: { bill_no: String(n) } }))
          .catch(() => dispatch({ type: 'checkout', patch: { bill_no: String(pdf.billNo + 1) } }))
      } else {
        dispatch({ type: 'checkout', patch: { bill_no: String(pdf.billNo + 1) } })
      }
    } catch (err) {
      if (err instanceof StaffCancelled) {
        // nothing: they closed the passcode dialog
      } else if (err instanceof NetworkError) {
        setProblem({ message: "Can't reach the server. Nothing was saved.", retry: () => print(mode, payments) })
      } else if (err instanceof ApiError && err.code === 'BILL_NO_TAKEN') {
        const next = Number(err.details.next_bill_no)
        dispatch({ type: 'checkout', patch: { bill_no: String(next) } })
        setProblem({ message: `Bill No ${body.bill_no} is already used. Changed to ${next}; press Print again.` })
      } else if (err instanceof ApiError && err.code === 'PRICES_CHANGED') {
        applyChanges((err.details.lines as ChangedLine[]) ?? [])
        setProblem({ message: STALE })
      } else if (err instanceof ApiError && err.code === 'INVOICING_DISABLED') {
        setProblem({ message: "Invoicing isn't set up on this server." })
      } else {
        setProblem({ message: err instanceof ApiError ? err.message : String((err as Error).message) })
      }
      // Keep the payment dialog open only for a network error, which it shows inline.
      if (!(err instanceof StaffCancelled) && !(err instanceof NetworkError)) setPaying(false)
    } finally {
      busyRef.current = false
      setBusy(false)
    }
  }

  if (lines.length === 0 && printed === null) {
    return (
      <main className="mx-auto flex max-w-3xl flex-col items-start gap-4 px-4 py-10 sm:px-6">
        <h1 className="type-expanded text-2xl font-bold">Cart</h1>
        <p className="text-ink-soft">The cart is empty. Price an article in the calculator and press Add to cart.</p>
        <div className="flex flex-wrap gap-3">
          <button type="button" className="rounded-md bg-ink px-4 py-2.5 font-semibold text-stock" onClick={onCalculator}>
            Go to calculator
          </button>
          <button type="button" className="rounded-md border-[1.5px] border-ink px-4 py-2.5 font-semibold" onClick={() => openCustomItem()}>
            Add custom item
          </button>
        </div>
      </main>
    )
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-5 px-4 pt-6 sm:px-6">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="type-expanded text-2xl font-bold">Cart</h1>
        <button type="button" className="rounded-md border-[1.5px] border-ink px-3 py-1.5 text-sm font-semibold" onClick={() => openCustomItem()}>
          + Add custom item
        </button>
      </div>

      {stale && (
        <div role="alert" className="rounded-md bg-warn-wash px-4 py-3 text-warn">
          <strong className="font-semibold">{STALE}</strong>
        </div>
      )}

      {printed !== null && (
        <div role="status" className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-save-wash px-4 py-3 text-save">
          <p>
            <strong className="font-semibold">Invoice {printed} downloaded.</strong> The cart is kept so you can reprint.
          </p>
          <button
            type="button"
            className="rounded-md bg-save px-3 py-1.5 text-sm font-semibold text-stock"
            onClick={() => {
              dispatch({ type: 'clear' })
              setPrinted(null)
            }}
          >
            Clear cart
          </button>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {lines.map((line, i) => (
          <CartLineCard key={line.id} line={line} index={i} count={lines.length} changed={changed.has(line.id)} />
        ))}
      </div>

      {invoiceSettings && !invoiceSettings.enabled && (
        <p role="status" className="rounded-md bg-warn-wash px-4 py-3 text-warn">
          Invoicing isn't set up on this server.
        </p>
      )}

      <CheckoutForm settings={settings} showErrors={false} billNoRequired={!storage} />

      <div className="sticky bottom-0 z-10 -mx-4 flex flex-col gap-2 border-t border-rule bg-sheet/95 px-4 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] backdrop-blur sm:-mx-6 sm:px-6">
        {problem && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 text-sm text-stop">
            <span>{problem.message}</span>
            {problem.retry && (
              <button type="button" className="rounded-md bg-ink px-3 py-1 font-semibold text-stock" onClick={problem.retry}>
                Retry
              </button>
            )}
          </div>
        )}
        <div className="grid gap-2 sm:grid-cols-2">
          <PrintButton label="Print (Unpaid as of now)" busy={busy} disabled={!ready} onClick={() => print('unpaid')} />
          <PrintButton label="Print (Paid)" busy={busy} disabled={!ready} onClick={() => setPaying(true)} />
        </div>
        <p className="text-center text-xs text-ink-soft">
          {ready
            ? 'Downloads the invoice PDF.'
            : `Downloads the invoice PDF. Fill in Ship To${storage ? '' : ' and Bill No'} and give every line a price first.`}
        </p>
      </div>

      {paying && (
        <PaymentDialog
          title="Print (Paid)"
          limit={m.payable}
          maxRows={4}
          confirmLabel="Confirm and download"
          busy={busy}
          error={problem?.message}
          onConfirm={(payments) => print('paid', payments)}
          onClose={() => setPaying(false)}
        />
      )}
    </main>
  )
}

function PrintButton({ label, busy, disabled, onClick }: { label: string; busy: boolean; disabled: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      className="flex w-full items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-semibold text-stock disabled:opacity-45"
      disabled={disabled || busy}
      aria-busy={busy}
      onClick={onClick}
    >
      {busy && <span className="size-4 animate-spin rounded-full border-2 border-stock border-t-transparent" aria-hidden="true" />}
      {label}
    </button>
  )
}
