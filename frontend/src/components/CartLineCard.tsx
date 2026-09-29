import { useEffect, useRef, useState } from 'react'
import { ApiError, calculate } from '../api/client'
import type { CartLine, SpecLine } from '../api/invoiceTypes'
import { isEdited, useCart, withFreshPrice } from '../cart/CartProvider'
import { money } from '../lib/format'
import { fromPaise, lineSubtotal, toPaise } from '../lib/invoiceMoney'
import { MiddleEditor } from './MiddleEditor'
import { SpecListEditor } from './SpecListEditor'
import { WarningBanner } from './WarningBanner'

export const REQUOTE_MS = 250

interface Props {
  line: CartLine
  index: number
  count: number
  changed: boolean
}

function Specs({ items }: { items: SpecLine[] }) {
  return (
    <ul className="flex flex-col gap-0.5 text-sm">
      {items.map((s, i) => (
        <li key={i} className="flex gap-2 before:mt-2 before:size-1.5 before:shrink-0 before:rounded-full before:bg-ink">
          <span>
            {s.label && <strong className="font-semibold">{s.label.toUpperCase()}:- </strong>}
            <span className={s.emphasis && s.label ? 'font-semibold' : ''}>{s.value.toUpperCase()}</span>
          </span>
        </li>
      ))}
    </ul>
  )
}

export function CartLineCard({ line, index, count, changed }: Props) {
  const { dispatch, lines } = useCart()
  const [editing, setEditing] = useState(false)
  const [editPrice, setEditPrice] = useState(false)
  const [confirmRemove, setConfirmRemove] = useState(false)
  const [qty, setQty] = useState(String(line.quantity))
  const [quoteError, setQuoteError] = useState<string | null>(null)
  const children = lines.filter((l) => l.parent_id === line.id)
  const update = (patch: Partial<CartLine>) => dispatch({ type: 'update', id: line.id, patch })
  const subtotal = lineSubtotal(line.quantity, line.unit_price)
  const edited = isEdited(line)

  // Keep the field in step when the server bills a different quantity (minimum order).
  const lastQuantity = useRef(line.quantity)
  useEffect(() => {
    if (line.quantity !== lastQuantity.current) {
      lastQuantity.current = line.quantity
      setQty(String(line.quantity))
    }
  }, [line.quantity])

  // Catalogue lines: re-quote 250 ms after the last keystroke (FR-C3.3).
  const requested = line.calc_request?.quantity
  const quotedFor = useRef(requested)
  useEffect(() => {
    if (line.source !== 'catalogue' || !line.calc_request || requested === undefined) return
    if (requested === quotedFor.current) return
    quotedFor.current = requested
    const controller = new AbortController()
    const t = setTimeout(async () => {
      try {
        const r = await calculate(line.calc_request!, controller.signal)
        if (r.status !== 'success' || !r.data.invoice_lines?.length) {
          setQuoteError('This quantity needs a manual quote. Remove the line or add it as a custom item.')
          return
        }
        const fresh = r.data.invoice_lines[0]
        setQuoteError(null)
        lastQuantity.current = fresh.quantity
        setQty(String(fresh.quantity))
        dispatch({
          type: 'update',
          id: line.id,
          patch: withFreshPrice(line, { quantity: fresh.quantity, catalogue_unit_price: fresh.catalogue_unit_price ?? fresh.unit_price, warnings: fresh.warnings }),
        })
      } catch (err) {
        if ((err as Error).name === 'AbortError') return
        setQuoteError(err instanceof ApiError ? err.message : "Can't reach the pricing server")
      }
    }, REQUOTE_MS)
    return () => {
      clearTimeout(t)
      controller.abort()
    }
    // Only a new requested quantity triggers a re-quote.
  }, [requested])

  const onQuantity = (raw: string) => {
    const clean = raw.replace(/[^\d]/g, '')
    setQty(clean)
    const n = Number(clean)
    if (!clean || !(n >= 1)) return
    if (line.source === 'catalogue' && line.calc_request) {
      update({ calc_request: { ...line.calc_request, quantity: n } })
    } else {
      update({ quantity: n })
    }
  }

  const showCatalogueMiddle =
    line.middle.kind === 'reference_price' && line.catalogue_unit_price !== null && line.middle.amount === line.catalogue_unit_price

  return (
    <article
      className={`rounded-md bg-stock p-4 shadow-sm ring-1 ${changed ? 'ring-2 ring-warn' : 'ring-rule'}`}
      aria-label={`Line ${index + 1}: ${line.title}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <h3 className="font-bold tracking-tight">{line.title.toUpperCase()}</h3>
          <div className="mt-1 flex flex-wrap gap-2 text-xs">
            {line.source === 'custom' && <span className="rounded bg-cyan-wash px-1.5 py-0.5 text-cyan-deep">Custom item</span>}
            {line.source === 'addon' && <span className="rounded bg-cyan-wash px-1.5 py-0.5 text-cyan-deep">Add-on</span>}
            {edited && (
              <span className="rounded bg-warn-wash px-1.5 py-0.5 text-warn">
                Catalogue {money(line.catalogue_unit_price!)} · edited
              </span>
            )}
          </div>
        </div>
        <div className="text-right">
          <p className="text-sm text-ink-soft">
            {line.quantity} {line.unit_label} × {money(line.unit_price)}
          </p>
          <p className="type-expanded text-lg font-bold" data-testid="line-subtotal">
            {money(fromPaise(subtotal))}
          </p>
        </div>
      </div>

      {!editing && (
        <div className="mt-3 flex flex-col gap-2">
          {line.specs.length > 0 && <Specs items={line.specs} />}
          {line.customisations.length > 0 && (
            <>
              <p className="text-xs font-bold">CUSTOMISATIONS:-</p>
              <Specs items={line.customisations} />
            </>
          )}
          {line.middle.kind === 'note' && <p className="text-sm font-semibold">{line.middle.text.toUpperCase()}</p>}
          {line.middle.kind === 'reference_price' && (
            <p className="text-sm">
              Reference price <s>{money(line.middle.amount || '0')}</s>
            </p>
          )}
        </div>
      )}

      {line.warnings.length > 0 && (
        <div className="mt-3 flex flex-col gap-2">
          {line.warnings.map((w) => (
            <WarningBanner key={w.code} warning={w} />
          ))}
        </div>
      )}
      {quoteError && (
        <p role="alert" className="mt-2 text-sm text-stop">
          {quoteError}
        </p>
      )}

      {editing && (
        <div className="mt-4 flex flex-col gap-4 border-t border-rule pt-4">
          <div className="flex flex-col gap-1">
            <label htmlFor={`title-${line.id}`} className="text-sm font-semibold text-ink-soft">
              Title
            </label>
            <input id={`title-${line.id}`} className="field" maxLength={80} value={line.title} onChange={(e) => update({ title: e.target.value })} />
          </div>
          <SpecListEditor legend="Specs" items={line.specs} max={12} onChange={(specs) => update({ specs })} />
          <SpecListEditor legend="Customisations" items={line.customisations} max={8} onChange={(customisations) => update({ customisations })} />
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label htmlFor={`qty-${line.id}`} className="text-sm font-semibold text-ink-soft">
                Quantity
              </label>
              <input id={`qty-${line.id}`} className="field" inputMode="numeric" value={qty} onChange={(e) => onQuantity(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1">
              <label htmlFor={`unit-${line.id}`} className="text-sm font-semibold text-ink-soft">
                Unit label
              </label>
              <input id={`unit-${line.id}`} className="field" maxLength={20} value={line.unit_label} onChange={(e) => update({ unit_label: e.target.value })} />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`price-${line.id}`} className="text-sm font-semibold text-ink-soft">
              Unit price (₹)
            </label>
            {editPrice || line.source === 'custom' ? (
              <input
                id={`price-${line.id}`}
                className="field"
                inputMode="decimal"
                value={line.unit_price}
                onChange={(e) => update({ unit_price: e.target.value.replace(/[^\d.]/g, '') })}
                aria-invalid={(toPaise(line.unit_price) ?? 0n) > 0n ? undefined : 'true'}
              />
            ) : (
              <p className="flex items-center gap-3">
                <span id={`price-${line.id}`} className="font-semibold">
                  {money(line.unit_price)}
                </span>
                <button type="button" className="text-sm text-cyan-deep underline" onClick={() => setEditPrice(true)}>
                  Edit price
                </button>
              </p>
            )}
            {line.catalogue_unit_price !== null && (
              <label className="mt-1 flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  className="accent-cyan"
                  checked={showCatalogueMiddle}
                  onChange={(e) =>
                    update({ middle: e.target.checked ? { kind: 'reference_price', amount: line.catalogue_unit_price! } : { kind: 'none' } })
                  }
                />
                Show catalogue price in the middle column
              </label>
            )}
          </div>
          <MiddleEditor value={line.middle} onChange={(middle) => update({ middle })} />
        </div>
      )}

      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        <button type="button" className="rounded-md border-[1.5px] border-ink px-3 py-1.5 font-semibold" onClick={() => setEditing(!editing)} aria-expanded={editing}>
          {editing ? 'Done' : 'Edit'}
        </button>
        <button type="button" className="rounded-md px-2 py-1.5 disabled:opacity-30" disabled={index === 0} onClick={() => dispatch({ type: 'move', id: line.id, by: -1 })} aria-label={`Move line ${index + 1} up`}>
          ↑ Up
        </button>
        <button type="button" className="rounded-md px-2 py-1.5 disabled:opacity-30" disabled={index === count - 1} onClick={() => dispatch({ type: 'move', id: line.id, by: 1 })} aria-label={`Move line ${index + 1} down`}>
          ↓ Down
        </button>
        {confirmRemove ? (
          <span className="ml-auto flex items-center gap-2" role="group" aria-label="Confirm remove">
            <span>Remove this line and its {children.length} add-on line{children.length === 1 ? '' : 's'}?</span>
            <button type="button" className="font-semibold text-stop" onClick={() => dispatch({ type: 'remove', id: line.id })}>
              Remove
            </button>
            <button type="button" onClick={() => setConfirmRemove(false)}>
              Keep
            </button>
          </span>
        ) : (
          <button
            type="button"
            className="ml-auto rounded-md px-2 py-1.5 text-stop"
            onClick={() => (children.length ? setConfirmRemove(true) : dispatch({ type: 'remove', id: line.id }))}
          >
            Remove
          </button>
        )}
      </div>
    </article>
  )
}
