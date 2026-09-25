import { useState } from 'react'
import type { QuoteData, QuoteResponse } from '../api/types'
import { count, money, qtyWithUnit, shortMoney } from '../lib/format'
import { quoteText } from '../lib/quoteText'
import { WarningBanner } from './WarningBanner'

export type ReceiptState =
  | { kind: 'idle'; message: string }
  | { kind: 'response'; response: QuoteResponse }
  | { kind: 'error'; message: string; network: boolean }

interface Props {
  state: ReceiptState
  loading: boolean
  onUseQuantity: (qty: number) => void
  onRetry: () => void
}

function RegMarks() {
  return (
    <>
      {['tl', 'tr', 'bl', 'br'].map((c) => (
        <span key={c} className={`reg ${c}`} aria-hidden="true">
          <span />
        </span>
      ))}
    </>
  )
}

export function ReceiptCard({ state, loading, onUseQuantity, onRetry }: Props) {
  return (
    <section
      className="ticket mx-2.5 my-2.5 px-5 py-6 sm:px-7"
      data-loading={loading}
      aria-busy={loading}
      aria-live="polite"
      aria-label="Quote"
    >
      <RegMarks />
      {state.kind === 'idle' && <p className="py-10 text-center text-ink-soft">{state.message}</p>}
      {state.kind === 'error' && (
        <div className="flex flex-col items-start gap-3 py-6">
          <h2 className="type-expanded text-lg font-bold text-stop">
            {state.network ? "Can't reach the pricing server" : 'Can’t price this yet'}
          </h2>
          <p className="text-ink-soft">
            {state.network ? 'Your selections are kept. Check the connection and try again.' : state.message}
          </p>
          {state.network && (
            <button type="button" className="rounded-md bg-ink px-4 py-2 font-semibold text-stock" onClick={onRetry}>
              Retry
            </button>
          )}
        </div>
      )}
      {state.kind === 'response' && state.response.status === 'manual_quote' && (
        <div className="flex flex-col gap-3 py-6">
          <p className="text-sm text-ink-soft">{state.response.data.product.name}</p>
          <h2 className="type-expanded text-2xl font-bold">Needs a manual quote</h2>
          <p>{state.response.message}.</p>
          <p className="text-sm text-ink-soft">{state.response.data.product.description}</p>
        </div>
      )}
      {state.kind === 'response' && state.response.status === 'success' && (
        <Quote q={state.response.data} onUseQuantity={onUseQuantity} />
      )}
    </section>
  )
}

function Row({ label, children, strong }: { label: React.ReactNode; children: React.ReactNode; strong?: boolean }) {
  return (
    <div className={`flex items-baseline justify-between gap-4 ${strong ? 'font-semibold' : ''}`}>
      <dt className={strong ? '' : 'text-ink-soft'}>{label}</dt>
      <dd className="text-right">{children}</dd>
    </div>
  )
}

function Quote({ q, onUseQuantity }: { q: QuoteData; onUseQuantity: (qty: number) => void }) {
  const [copied, setCopied] = useState<'idle' | 'done' | 'failed'>('idle')
  const unit = q.quantity.sale_unit
  const p = q.pricing
  const ce = p.custom_estimate

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(quoteText(q))
      setCopied('done')
    } catch {
      setCopied('failed')
    }
    setTimeout(() => setCopied('idle'), 2000)
  }

  return (
    <div className="flex flex-col gap-5">
      <header className="flex flex-col gap-1">
        <p className="text-sm text-ink-soft">{q.product.category ?? 'Quote'}</p>
        <h2 className="type-expanded text-xl leading-tight font-bold sm:text-2xl">{q.product.name}</h2>
        <p className="text-ink-soft">{q.product.description}</p>
        {ce && ce.anchors.length > 0 && (
          <p className="text-sm text-cyan-deep">
            {ce.method === 'floor'
              ? `Smaller than every standard size, so priced at ${ce.anchors[0].size.replace(/ in.*$/, '')}`
              : ce.anchors.length === 2
                ? `Priced between ${ce.anchors[0].size.replace(/ in.*$/, '')} and ${ce.anchors[1].size.replace(/ in.*$/, '')}`
                : `Priced as ${ce.anchors[0].size.replace(/ in.*$/, '')}`}
            {' '}({ce.metric} {ce.metric_unit})
          </p>
        )}
      </header>

      <dl className="flex flex-col gap-2">
        <Row label="Quantity">
          {qtyWithUnit(q.quantity.billed, unit)}
          {q.quantity.micro && (
            <span className="block text-sm text-ink-soft">
              = {q.quantity.micro.approx ? 'approx. ' : ''}
              {count(q.quantity.micro.amount)} {q.quantity.micro.unit}
            </span>
          )}
          {q.quantity.billed !== q.quantity.requested && (
            <span className="block text-sm text-ink-soft">{count(q.quantity.requested)} requested</span>
          )}
        </Row>
        <Row label="Tier">
          {p.tier_applied.label}
          <span className="block text-sm text-ink-soft">applies to {p.tier_applied.range}</span>
        </Row>
        <Row label={`Price per ${unit}`}>
          <span className="type-expanded text-lg font-bold">{money(p.unit_price)}</span>
          {p.micro_unit_price && (
            <span className="block text-sm text-ink-soft">
              {p.micro_approx ? 'approx. ' : ''}
              {money(p.micro_unit_price)} {p.micro_uom}
            </span>
          )}
        </Row>
        {q.addons.map((a) => (
          <Row key={a.id} label={`+ ${a.name}`}>
            {money(a.price)} {a.basis === 'per_unit' ? `per ${unit}` : 'per order'}
          </Row>
        ))}
      </dl>

      {p.next_tier && (
        <p className="border-l-[3px] border-cyan pl-3 text-sm">
          Add {count(p.next_tier.units_to_next)} more to drop to <strong>{shortMoney(p.next_tier.unit_price)}</strong> each
        </p>
      )}

      {p.better_option && (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-md bg-save-wash px-3 py-3 text-save">
          <p className="text-sm">
            <strong className="font-semibold">
              {qtyWithUnit(p.better_option.qty, unit)} cost {shortMoney(p.better_option.saving)} less
            </strong>{' '}
            than {count(q.quantity.billed)}: {money(p.better_option.subtotal)} before GST.
          </p>
          <button
            type="button"
            className="rounded-md bg-save px-3 py-1.5 text-sm font-semibold text-stock"
            onClick={() => onUseQuantity(p.better_option!.qty)}
          >
            Use {count(p.better_option.qty)}
          </button>
        </div>
      )}

      {q.warnings.length > 0 && (
        <div className="flex flex-col gap-2">
          {q.warnings.map((w) => (
            <WarningBanner key={w.code} warning={w} />
          ))}
        </div>
      )}

      <div className="perforation -mx-5 sm:-mx-7" role="presentation" />

      <dl className="flex flex-col gap-2">
        <Row label="Subtotal">{money(q.totals.subtotal)}</Row>
        {q.totals.billing_type === 'gst' ? (
          <Row label={`GST ${q.totals.gst_rate_percent}%`}>{money(q.totals.gst_amount)}</Row>
        ) : (
          <Row label="GST">Not charged (invoice billing)</Row>
        )}
        <div className="mt-1 flex items-baseline justify-between gap-4">
          <dt className="font-semibold">Total</dt>
          <dd className="type-expanded text-3xl font-extrabold tracking-tight" data-testid="grand-total">
            {money(q.totals.grand_total)}
          </dd>
        </div>
        <Row label="Production time">{q.production_time}</Row>
      </dl>

      <button
        type="button"
        onClick={copy}
        className="rounded-md border-[1.5px] border-ink px-4 py-2.5 font-semibold hover:bg-ink hover:text-stock"
      >
        {copied === 'done' ? 'Quote copied' : copied === 'failed' ? 'Copy failed - select the text instead' : 'Copy quote'}
      </button>

      <ul className="flex flex-col gap-1 text-sm text-ink-soft">
        {q.notes.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  )
}
