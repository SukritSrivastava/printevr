import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, NetworkError, calculate } from '../api/client'
import { createInvoice, fetchNextBillNo, staffToken } from '../api/invoices'
import type { BillType, CartLine, ChangedLine, InvoiceSettings, PaymentInput, Series } from '../api/invoiceTypes'
import { useCart } from '../cart/CartProvider'
import { checkoutErrors, documentRequest, printMissing, quotationMissing } from '../lib/documents'
import { saveBlob } from '../lib/download'
import { DEFAULT_MONEY_SETTINGS, chosenSlab, invoiceMoney } from '../lib/invoiceMoney'
import { CartLineCard } from './CartLineCard'
import { CheckoutForm, type CheckoutSettings } from './CheckoutForm'
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

type Problem = { message: string; retry?: () => void }
type Kind = 'quotation' | 'unpaid' | 'paid'

const DOCUMENT_NAMES: Record<Series, string> = { quotation: 'Quotation', non_gst: 'Invoice', gst: 'GST invoice' }

function settingsFrom(s: InvoiceSettings | undefined): CheckoutSettings {
  return {
    ...DEFAULT_MONEY_SETTINGS,
    ...(s?.gst_slab_groups ? { slabGroups: s.gst_slab_groups } : {}),
    ...(s?.advance_pct ? { advancePct: s.advance_pct } : {}),
    gstDefaults: s?.gst_field_defaults ?? {},
    hsnCodes: s?.hsn_codes ?? {},
    stateCode: s?.seller_state_code ?? '',
  }
}

export function CartPage({ onCalculator, invoiceSettings }: { onCalculator: () => void; invoiceSettings?: InvoiceSettings }) {
  const { lines, checkout, dispatch, openCustomItem } = useCart()
  const withStaff = useStaff()
  const toast = useToast()
  const [stale, setStale] = useState(false)
  const [changed, setChanged] = useState<Set<string>>(new Set())
  const [settings, setSettings] = useState<CheckoutSettings>(() => settingsFrom(invoiceSettings))
  // Without storage the server can't count numbers: the Bill No (and Quote No) are typed and
  // remembered here.
  const storage = invoiceSettings?.storage ?? true
  useEffect(() => {
    if (invoiceSettings) setSettings(settingsFrom(invoiceSettings))
  }, [invoiceSettings])
  // Each series' next number, once staff are signed in (storage only).
  const [next, setNext] = useState<Record<Series, number> | null>(null)
  const [busy, setBusy] = useState(false)
  const [paying, setPaying] = useState(false)
  const [problem, setProblem] = useState<Problem | null>(null)
  const [printed, setPrinted] = useState<{ series: Series; no: number } | null>(null)
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

  const refreshNumbers = useCallback(async () => {
    const n = await fetchNextBillNo()
    setNext(n.next)
    setSettings((s) => ({ ...s, slabGroups: n.gst_slab_groups, advancePct: n.advance_pct }))
    return n.next
  }, [])

  // On open: re-quote every catalogue line once, and pre-fill the bill number if staff are signed in.
  const opened = useRef(false)
  useEffect(() => {
    if (opened.current) return
    opened.current = true
    freshPrices(lines).then(applyChanges)
    if (storage && (staffToken() || invoiceSettings?.staff_passcode === false)) {
      refreshNumbers()
        .then((n) => {
          if (!checkout.bill_no && checkout.billing_type) dispatch({ type: 'checkout', patch: { bill_no: String(n[checkout.billing_type]) } })
        })
        .catch(() => {})
    }
  }, [lines, checkout.bill_no, checkout.billing_type, applyChanges, refreshNumbers, dispatch, storage, invoiceSettings?.staff_passcode])

  /** Switching bill type moves a pre-filled Bill No to the new series; a typed one stays. */
  const chooseBillType = (type: BillType) => {
    const previous = checkout.billing_type
    const suggested = !checkout.bill_no || (!!previous && !!next && checkout.bill_no === String(next[previous]))
    const bill_no = storage && suggested ? (next ? String(next[type]) : '') : checkout.bill_no
    dispatch({ type: 'checkout', patch: { billing_type: type, bill_no } })
  }

  const slab = chosenSlab(checkout.billing_type, checkout.gst_slab, settings.slabGroups)
  const m = invoiceMoney(lines, slab?.components ?? [], settings)
  const formErrors = checkoutErrors(checkout, { billNoRequired: !storage, quoteNoRequired: !storage })
  const quoteMissing = quotationMissing(lines, formErrors)
  const missing = printMissing(checkout, lines, formErrors, slab)
  const ready = missing.length === 0
  const quoteReady = quoteMissing.length === 0

  const print = async (kind: Kind, payments: PaymentInput[] = []) => {
    if (busyRef.current) return
    busyRef.current = true
    setBusy(true)
    setProblem(null)
    const body = documentRequest(
      kind,
      checkout,
      lines,
      { storage, slab, defaults: settings.gstDefaults, hsnCodes: settings.hsnCodes, advancePct: settings.advancePct },
      payments,
    )
    const quotation = kind === 'quotation'
    try {
      const pdf = await withStaff(() => createInvoice(body))
      saveBlob(pdf.blob, pdf.filename)
      setPaying(false)
      setPrinted({ series: pdf.series, no: pdf.billNo })
      setStale(false)
      setChanged(new Set())
      toast(`${DOCUMENT_NAMES[pdf.series]} ${pdf.billNo} downloaded`)
      if (!storage) {
        dispatch({ type: 'checkout', patch: quotation ? { quote_no: String(pdf.billNo + 1) } : { bill_no: String(pdf.billNo + 1) } })
      } else {
        const type = checkout.billing_type
        refreshNumbers()
          .then((n) => {
            if (!quotation && type) dispatch({ type: 'checkout', patch: { bill_no: String(n[type]) } })
          })
          .catch(() => {
            if (!quotation) dispatch({ type: 'checkout', patch: { bill_no: String(pdf.billNo + 1) } })
          })
      }
    } catch (err) {
      if (err instanceof StaffCancelled) {
        // nothing: they closed the passcode dialog
      } else if (err instanceof NetworkError) {
        setProblem({ message: "Can't reach the server. Nothing was saved.", retry: () => print(kind, payments) })
      } else if (err instanceof ApiError && err.code === 'BILL_NO_TAKEN') {
        const free = Number(err.details.next_bill_no)
        const field = quotation ? 'quote_no' : 'bill_no'
        dispatch({ type: 'checkout', patch: { [field]: String(free) } })
        setProblem({ message: `${quotation ? 'Quote' : 'Bill'} No ${body.bill_no} is already used. Changed to ${free}; press the button again.` })
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
            <strong className="font-semibold">
              {DOCUMENT_NAMES[printed.series]} {printed.no} downloaded.
            </strong>{' '}
            The cart is kept so you can print again.
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

      <CheckoutForm
        settings={settings}
        errors={formErrors}
        showErrors={false}
        billNoRequired={!storage}
        quoteNoRequired={!storage}
        onBillType={chooseBillType}
      />

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
        <div className="grid gap-2 sm:grid-cols-3">
          <PrintButton label="Quotation" busy={busy} disabled={!quoteReady} hint="quotation-hint" onClick={() => print('quotation')} />
          <PrintButton label="Print (Unpaid as of now)" busy={busy} disabled={!ready} hint="print-hint" onClick={() => print('unpaid')} />
          <PrintButton label="Print (Paid)" busy={busy} disabled={!ready} hint="print-hint" onClick={() => setPaying(true)} />
        </div>
        {!quoteReady && (
          <p id="quotation-hint" className="text-center text-xs text-ink-soft">
            Quotation: {quoteMissing.join(', ')}.
          </p>
        )}
        <p id="print-hint" className="text-center text-xs text-ink-soft">
          {ready
            ? `Print downloads the ${checkout.billing_type === 'gst' ? 'GST invoice' : 'Non-GST invoice'} PDF.`
            : `Print: ${missing.join(', ')}.`}
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

function PrintButton({
  label,
  busy,
  disabled,
  hint,
  onClick,
}: {
  label: string
  busy: boolean
  disabled: boolean
  /** id of the line saying what's missing */
  hint: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      className="flex w-full items-center justify-center gap-2 rounded-md bg-ink px-4 py-3 font-semibold text-stock disabled:opacity-45"
      disabled={disabled || busy}
      aria-busy={busy}
      aria-describedby={disabled ? hint : undefined}
      onClick={onClick}
    >
      {busy && <span className="size-4 animate-spin rounded-full border-2 border-stock border-t-transparent" aria-hidden="true" />}
      {label}
    </button>
  )
}
