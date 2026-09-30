import { useCallback, useEffect, useState } from 'react'
import { ApiError, NetworkError } from '../api/client'
import { addPayment, deleteInvoice, downloadInvoice, listInvoices } from '../api/invoices'
import type { InvoiceList, InvoiceStatus, InvoiceSummary, PaymentInput } from '../api/invoiceTypes'
import { saveBlob } from '../lib/download'
import { money } from '../lib/format'
import { toPaise } from '../lib/invoiceMoney'
import { Dialog } from './Dialog'
import { PaymentDialog } from './PaymentDialog'
import { StaffCancelled, useStaff } from './StaffLoginDialog'
import { useToast } from './Toast'

const PAGE = 25
const STATUS: Record<InvoiceStatus, { label: string; cls: string }> = {
  unpaid: { label: 'Unpaid', cls: 'bg-warn-wash text-warn' },
  part_paid: { label: 'Part-paid', cls: 'bg-cyan-wash text-cyan-deep' },
  paid: { label: 'Paid', cls: 'bg-save-wash text-save' },
}

function describe(err: unknown): string | null {
  if (err instanceof StaffCancelled) return null
  if (err instanceof NetworkError) return "Can't reach the server."
  if (err instanceof ApiError && err.code === 'INVOICING_DISABLED') return "Invoicing isn't set up on this server."
  return err instanceof Error ? err.message : String(err)
}

/** Recent invoices: search, re-download, record payments (FR-P6). */
export function InvoicesPage() {
  const withStaff = useStaff()
  const toast = useToast()
  const [q, setQ] = useState('')
  const [search, setSearch] = useState('')
  const [offset, setOffset] = useState(0)
  const [data, setData] = useState<InvoiceList | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [paying, setPaying] = useState<InvoiceSummary | null>(null)
  const [busy, setBusy] = useState<number | null>(null)
  const [payError, setPayError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<InvoiceSummary | null>(null)
  const [deleteError, setDeleteError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      setData(await withStaff(() => listInvoices({ q: search, limit: PAGE, offset })))
    } catch (err) {
      setError(describe(err) ?? 'Enter the staff passcode to see invoices.')
    } finally {
      setLoading(false)
    }
  }, [withStaff, search, offset])

  useEffect(() => {
    load()
  }, [load])

  useEffect(() => {
    const t = setTimeout(() => {
      setOffset(0)
      setSearch(q.trim())
    }, 300)
    return () => clearTimeout(t)
  }, [q])

  const download = async (row: InvoiceSummary) => {
    setBusy(row.bill_no)
    try {
      const pdf = await withStaff(() => downloadInvoice(row.bill_no))
      saveBlob(pdf.blob, pdf.filename)
      toast(`Invoice ${row.bill_no} downloaded`)
    } catch (err) {
      const message = describe(err)
      if (message) toast(message)
    } finally {
      setBusy(null)
    }
  }

  const record = async (row: InvoiceSummary, payments: PaymentInput[]) => {
    setBusy(row.bill_no)
    setPayError(null)
    try {
      const pdf = await withStaff(() => addPayment(row.bill_no, payments[0]))
      saveBlob(pdf.blob, pdf.filename)
      setPaying(null)
      toast(`Payment recorded. Invoice ${row.bill_no} downloaded`)
      await load()
    } catch (err) {
      setPayError(describe(err))
    } finally {
      setBusy(null)
    }
  }

  const remove = async (row: InvoiceSummary) => {
    setBusy(row.bill_no)
    setDeleteError(null)
    try {
      await withStaff(() => deleteInvoice(row.bill_no))
      setDeleting(null)
      toast(`Invoice ${row.bill_no} deleted`)
      // The last row of a later page: step back so the list isn't empty.
      if (data && offset > 0 && data.invoices.length === 1) setOffset(Math.max(0, offset - PAGE))
      else await load()
    } catch (err) {
      setDeleteError(describe(err))
    } finally {
      setBusy(null)
    }
  }

  const remaining = (row: InvoiceSummary) => (toPaise(row.payable) ?? 0n) - (toPaise(row.received) ?? 0n)

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-5 px-4 py-6 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h1 className="type-expanded text-2xl font-bold">Invoices</h1>
        <div className="flex w-full flex-col gap-1 sm:w-72">
          <label htmlFor="invoice-search" className="text-sm font-semibold text-ink-soft">
            Search business or bill no
          </label>
          <input id="invoice-search" type="search" className="field" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>

      {error && (
        <div role="alert" className="flex flex-wrap items-center gap-3 text-stop">
          <span>{error}</span>
          <button type="button" className="rounded-md bg-ink px-3 py-1 text-sm font-semibold text-stock" onClick={load}>
            Retry
          </button>
        </div>
      )}

      {data && data.invoices.length === 0 && !loading && <p className="text-ink-soft">{search ? 'No invoices match.' : 'No invoices yet.'}</p>}

      {data && data.invoices.length > 0 && (
        <div className="overflow-x-auto rounded-md bg-stock shadow-sm ring-1 ring-rule" aria-busy={loading}>
          <table className="w-full min-w-[40rem] text-left text-sm">
            <thead className="border-b border-rule text-ink-soft">
              <tr>
                <th className="px-3 py-2 font-semibold">Bill No</th>
                <th className="px-3 py-2 font-semibold">Date</th>
                <th className="px-3 py-2 font-semibold">Business</th>
                <th className="px-3 py-2 text-right font-semibold">Payable</th>
                <th className="px-3 py-2 text-right font-semibold">Received</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {data.invoices.map((row) => (
                <tr key={row.bill_no} className="border-b border-rule last:border-0">
                  <td className="px-3 py-2 font-semibold">{row.bill_no}</td>
                  <td className="px-3 py-2 whitespace-nowrap">{row.invoice_date}</td>
                  <td className="px-3 py-2">{row.business_name}</td>
                  <td className="px-3 py-2 text-right">{money(row.payable)}</td>
                  <td className="px-3 py-2 text-right">{money(row.received)}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded px-1.5 py-0.5 text-xs font-semibold ${STATUS[row.status].cls}`}>{STATUS[row.status].label}</span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex justify-end gap-2">
                      <button
                        type="button"
                        className="rounded-md border-[1.5px] border-ink px-2.5 py-1 font-semibold disabled:opacity-50"
                        disabled={busy === row.bill_no}
                        onClick={() => download(row)}
                        aria-label={`Download invoice ${row.bill_no}`}
                      >
                        Download
                      </button>
                      {row.status !== 'paid' && (
                        <button
                          type="button"
                          className="rounded-md bg-ink px-2.5 py-1 font-semibold whitespace-nowrap text-stock disabled:opacity-50"
                          disabled={busy === row.bill_no}
                          onClick={() => {
                            setPayError(null)
                            setPaying(row)
                          }}
                          aria-label={`Record payment for invoice ${row.bill_no}`}
                        >
                          Record payment
                        </button>
                      )}
                      <button
                        type="button"
                        className="rounded-md px-2.5 py-1 font-semibold text-stop ring-1 ring-stop/40 hover:bg-stop/10 disabled:opacity-50"
                        disabled={busy === row.bill_no}
                        onClick={() => {
                          setDeleteError(null)
                          setDeleting(row)
                        }}
                        aria-label={`Delete invoice ${row.bill_no}`}
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && data.total > PAGE && (
        <nav className="flex items-center justify-between gap-3 text-sm" aria-label="Pages">
          <button type="button" className="rounded-md px-3 py-1.5 ring-1 ring-rule disabled:opacity-40" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            ← Newer
          </button>
          <span className="text-ink-soft">
            {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
          </span>
          <button type="button" className="rounded-md px-3 py-1.5 ring-1 ring-rule disabled:opacity-40" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
            Older →
          </button>
        </nav>
      )}

      {paying && (
        <PaymentDialog
          title={`Record payment · Bill No ${paying.bill_no}`}
          limit={remaining(paying)}
          maxRows={1}
          confirmLabel="Record and download"
          busy={busy === paying.bill_no}
          error={payError}
          onConfirm={(payments) => record(paying, payments)}
          onClose={() => setPaying(null)}
        />
      )}

      {deleting && (
        <Dialog title={`Delete invoice ${deleting.bill_no}?`} onClose={() => setDeleting(null)}>
          <p className="text-ink-soft">
            {deleting.business_name} · {money(deleting.payable)}. It disappears from this list for everyone and can't be downloaded again. This can't be undone.
          </p>
          {deleteError && (
            <p role="alert" className="mt-3 text-sm text-stop">
              {deleteError}
            </p>
          )}
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" className="rounded-md px-4 py-2 font-semibold ring-1 ring-rule" onClick={() => setDeleting(null)}>
              Cancel
            </button>
            <button
              type="button"
              className="rounded-md bg-stop px-4 py-2 font-semibold text-stock disabled:opacity-50"
              disabled={busy === deleting.bill_no}
              onClick={() => remove(deleting)}
            >
              Delete invoice
            </button>
          </div>
        </Dialog>
      )}
    </main>
  )
}
