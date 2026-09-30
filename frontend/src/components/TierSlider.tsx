import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { TierSchedule } from '../api/types'
import { count, qtyWithUnit, shortMoney } from '../lib/format'
import {
  nextBreakpoint,
  positionOf,
  previousBreakpoint,
  quantityAt,
  segments,
  sliderMin,
  snap,
  tierAt,
  type TierPoint,
} from '../lib/tierSlider'

/** What the server said for the quantity on screen, when its answer is in (FR-A11). */
export interface ServerTier {
  requested: number
  tierFrom: number
  unitsToNext: number | null
}

interface Props {
  schedule: TierSchedule
  /** The quantity asked for; null when there isn't a valid one yet. */
  quantity: number | null
  unit: string
  /** Absent: read-only (outdoor branding, where the quantity comes from W × H × pieces). */
  onChange?: (quantity: number) => void
  /** Per-unit add-ons are chosen, so tier prices include them. */
  withAddons?: boolean
  server?: ServerTier | null
}

const pct = (p: number) => `${(p * 100).toFixed(3)}%`
// Labels need this much room (px) between neighbours: "2,000" over "₹40", or the price alone.
const LABEL_ROOM = 48
const PRICE_ROOM = 36
const NARROW = '(max-width: 419.98px)'
// A pointer that moves less than this (px) is a tap; a tap this close (px) to a dot picks it.
const TAP_SLOP = 6
const DOT_REACH = 22

function useWidth(ref: React.RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    setWidth(el.getBoundingClientRect().width)
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([entry]) => setWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [ref])
  return width
}

function useNarrow() {
  const [narrow, setNarrow] = useState(() => typeof window.matchMedia === 'function' && window.matchMedia(NARROW).matches)
  useEffect(() => {
    if (typeof window.matchMedia !== 'function') return
    const mq = window.matchMedia(NARROW)
    const on = () => setNarrow(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return narrow
}

/** The screen-reader value: "450 boxes, ₹75 each, 50 short of the ₹55 tier" (FR-A8). */
export function valueText(p: TierPoint, unit: string): string {
  const parts = [qtyWithUnit(p.requested, unit)]
  if (p.belowMin) parts.push(`billed as ${count(p.billed)}`)
  parts.push(`${shortMoney(p.tier.unit_price)} each`)
  if (p.manual) parts.push('needs a manual quote')
  else if (p.beyond) parts.push('beyond scale')
  else if (p.next) parts.push(`${count(p.next.unitsToNext)} short of the ${shortMoney(p.next.tier.unit_price)} tier`)
  return parts.join(', ')
}

/**
 * Tier slider with price-break highlighting (BRD-tier-slider-back-nav section 4). Replaces the
 * v2.1 tier ladder. The chip and markers are worked out here from tier_schedule on every frame;
 * the totals still come only from /api/calculate.
 */
export function TierSlider({ schedule: s, quantity, unit, onChange, withAddons, server }: Props) {
  const box = useRef<HTMLDivElement>(null)
  const width = useWidth(box)
  const narrow = useNarrow()
  const drag = useRef<{ id: number; x: number; startX: number; frame: number } | null>(null)
  const [dragging, setDragging] = useState(false)
  const segs = segments(s)
  const interactive = !!onChange
  const multiTier = s.tiers.length > 1
  const has = quantity !== null && quantity > 0
  const local = has ? tierAt(quantity, s) : null

  // FR-A11: the server's answer for this quantity wins; a disagreement is a bug worth seeing.
  let point = local
  if (local && server && server.requested === local.requested) {
    const agrees = server.tierFrom === local.tier.qty_from && server.unitsToNext === (local.next?.unitsToNext ?? null)
    if (!agrees) {
      if (import.meta.env.DEV) console.warn('Tier slider disagrees with /api/calculate; showing the server values', { local, server })
      const index = Math.max(0, s.tiers.findIndex((t) => t.qty_from === server.tierFrom))
      const next = s.tiers[index + 1]
      point = {
        ...local,
        index,
        tier: s.tiers[index],
        next: next && server.unitsToNext !== null ? { tier: next, unitsToNext: server.unitsToNext } : null,
      }
    }
  }

  const thumb = has ? positionOf(quantity, segs) : null
  const lo = sliderMin(s)

  const fromClientX = (clientX: number) => {
    const rect = box.current?.getBoundingClientRect()
    if (!rect || rect.width <= 0) return null
    return quantityAt((clientX - rect.left) / rect.width, segs)
  }
  const set = (q: number | null) => {
    if (q !== null && onChange && q !== quantity) onChange(q)
  }

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!interactive || e.button !== 0) return
    e.currentTarget.setPointerCapture?.(e.pointerId)
    e.currentTarget.focus()
    drag.current = { id: e.pointerId, x: e.clientX, startX: e.clientX, frame: 0 }
    setDragging(true)
    set(fromClientX(e.clientX))
  }
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    d.x = e.clientX
    // One quantity update per animation frame, however fast the pointer events come (FR-A5).
    if (!d.frame) {
      d.frame = requestAnimationFrame(() => {
        if (drag.current) {
          drag.current.frame = 0
          set(fromClientX(drag.current.x))
        }
      })
    }
  }
  const endDrag = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current
    if (!d || d.id !== e.pointerId) return
    cancelAnimationFrame(d.frame)
    drag.current = null
    setDragging(false)
    const q = fromClientX(e.clientX)
    if (q === null) return
    // A tap on a breakpoint's dot sets exactly that breakpoint (FR-A3).
    const rect = box.current!.getBoundingClientRect()
    const tapped =
      Math.abs(e.clientX - d.startX) < TAP_SLOP
        ? s.tiers.find((t) => Math.abs(positionOf(t.qty_from, segs) * rect.width - (e.clientX - rect.left)) <= DOT_REACH)
        : undefined
    set(tapped ? tapped.qty_from : snap(q, s, segs)) // FR-A7: a released drag snaps; keys and typing never do
  }

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!interactive) return
    const q = has ? quantity : s.min_qty
    const target = (() => {
      switch (e.key) {
        case 'ArrowRight':
        case 'ArrowUp':
          return Math.min(s.slider_max, Math.max(lo, q + 1))
        case 'ArrowLeft':
        case 'ArrowDown':
          return Math.max(lo, Math.min(s.slider_max, q - 1))
        case 'PageUp':
          return nextBreakpoint(q, s) ?? s.slider_max
        case 'PageDown':
          return previousBreakpoint(q, s) ?? lo
        case 'Home':
          return s.min_qty
        case 'End':
          return s.slider_max
        default:
          return null
      }
    })()
    if (target === null) return
    e.preventDefault()
    set(target)
  }

  // Marker labels: quantity over price, or price only on narrow screens; never overlapping (FR-A12).
  const compact = narrow || (width > 0 && segs.length * LABEL_ROOM > width)
  const room = compact ? PRICE_ROOM : LABEL_ROOM
  let lastShown = -Infinity
  const markers = s.tiers.map((t, i) => {
    const pos = positionOf(t.qty_from, segs)
    const px = pos * (width || 1000)
    const showLabel = px - lastShown >= room || width === 0
    if (showLabel) lastShown = px
    const state = point && t.qty_from <= point.billed ? 'passed' : point?.next?.tier.qty_from === t.qty_from ? 'next' : 'later'
    return { t, i, pos, showLabel, state }
  })
  // The end label ("4,000", "1,000 max") is right-aligned; it shows only where it clears the last label.
  const endText = `${count(s.slider_max)}${s.max_qty !== null ? ' max' : ''}`
  const lastLabel = [...markers].reverse().find((m) => m.showLabel)
  const endRoom = (1 - (lastLabel?.pos ?? 0)) * (width || 1000) >= room / 2 + endText.length * 7 + 6
  const currentSeg = point ? segs.find((g) => g.kind === 'tier' && g.tier === point.index) : undefined
  const zones = s.suggest_more
    ? s.tiers.flatMap((t, i) => (t.overpay_from === null ? [] : [{ i, from: positionOf(t.overpay_from, segs), to: positionOf(t.qty_to! + 1, segs) }]))
    : []
  const belowSeg = segs.find((g) => g.kind === 'below_min')
  const belowEnd = belowSeg ? positionOf(belowSeg.to, segs) : 0

  const label = interactive ? 'Price breaks' : 'Price breaks for this size'
  const chipShown = interactive && multiTier && point !== null
  const text = point ? valueText(point, unit) : `Price breaks from ${count(s.min_qty)}`

  return (
    <figure className="flex flex-col gap-1" data-testid="tier-slider">
      <figcaption className="text-sm font-semibold text-ink-soft">{interactive ? 'Price breaks' : 'Price breaks (set by the print size)'}</figcaption>
      <div ref={box} className={`relative mx-4 select-none ${chipShown ? 'pt-16' : 'pt-1'}`}>
        {chipShown && point && thumb !== null && (
          <div
            aria-hidden="true"
            data-testid="tier-chip"
            className={`absolute top-0 z-10 w-max max-w-[15rem] -translate-x-1/2 rounded-md border-[1.5px] bg-stock px-2.5 py-1.5 text-sm leading-snug shadow-sm ${point.inOverpay ? 'border-warn' : 'border-cyan'}`}
            style={{ left: `clamp(7.5rem, ${pct(thumb)}, 100% - 7.5rem)` }}
          >
            <p className="font-semibold whitespace-nowrap">
              {point.beyond
                ? `${count(point.requested)} · beyond scale`
                : point.belowMin
                  ? `${qtyWithUnit(point.requested, unit)} · Billed as ${count(point.billed)}`
                  : `${qtyWithUnit(point.requested, unit)} · ${shortMoney(point.tier.unit_price)} each`}
            </p>
            {point.manual ? (
              <p className="whitespace-nowrap text-warn">Needs a manual quote</p>
            ) : point.belowMin ? (
              <p className="whitespace-nowrap">{shortMoney(point.tier.unit_price)} each{point.next && <NextLine next={point.next} withAddons={withAddons} />}</p>
            ) : (
              point.next && !point.beyond && <NextLine next={point.next} withAddons={withAddons} block />
            )}
          </div>
        )}

        <div
          role={interactive ? 'slider' : 'img'}
          tabIndex={interactive ? 0 : undefined}
          aria-label={interactive ? label : `${label}: ${text}`}
          aria-valuemin={interactive ? lo : undefined}
          aria-valuemax={interactive ? s.slider_max : undefined}
          aria-valuenow={interactive && has ? Math.min(quantity, s.slider_max) : undefined}
          aria-valuetext={interactive ? text : undefined}
          aria-orientation={interactive ? 'horizontal' : undefined}
          className={`tier-slider relative h-11 touch-none rounded-md ${interactive ? 'cursor-pointer' : ''}`}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onKeyDown={onKeyDown}
        >
          <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 overflow-hidden rounded-full bg-rule/70">
            {belowSeg && <div className="tier-hatch absolute inset-y-0 left-0" style={{ width: pct(belowEnd) }} />}
            {currentSeg && thumb !== null && (
              <>
                <div
                  className="absolute inset-y-0 bg-cyan-soft"
                  style={{ left: pct(belowEnd), width: pct(Math.max(0, positionOf(currentSeg.from, segs) - belowEnd)) }}
                />
                <div
                  className="absolute inset-y-0 bg-cyan"
                  style={{ left: pct(positionOf(currentSeg.from, segs)), width: pct(Math.max(0, thumb - positionOf(currentSeg.from, segs))) }}
                  data-testid="tier-current"
                />
              </>
            )}
            {zones.map((z) => (
              <div
                key={z.i}
                className={`tier-overpay absolute inset-y-0 ${point?.index === z.i ? 'opacity-100' : 'opacity-60'}`}
                style={{ left: pct(z.from), width: pct(z.to - z.from) }}
                data-testid="tier-overpay"
              />
            ))}
          </div>
          {multiTier &&
            markers.map(({ t, pos, state }) => (
              <span
                key={t.qty_from}
                aria-hidden="true"
                className="tier-dot pointer-events-none absolute top-1/2 block size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2"
                style={{ left: pct(pos) }}
                data-state={state}
                data-pulse={state === 'next' && point?.inOverpay ? 'true' : undefined}
                data-testid={`tier-dot-${t.qty_from}`}
              />
            ))}
          {thumb !== null && (
            <div
              className="pointer-events-none absolute top-1/2 grid size-11 -translate-x-1/2 -translate-y-1/2 place-items-center"
              style={{ left: pct(thumb) }}
              data-testid="tier-thumb"
            >
              <span className={`tier-thumb block size-5 rounded-full border-[3px] border-cyan bg-stock shadow ${dragging ? 'scale-110' : ''}`} />
            </div>
          )}
        </div>

        {multiTier && (
          <div className="relative h-9">
            {markers.map(({ t, pos, showLabel, state }) =>
              showLabel ? (
                <button
                  key={t.qty_from}
                  type="button"
                  tabIndex={-1}
                  disabled={!interactive}
                  title={`${count(t.qty_from)} · ${shortMoney(t.unit_price)}`}
                  aria-label={`${count(t.qty_from)} or more: ${shortMoney(t.unit_price)} each${state === 'next' ? ', next price break' : ''}`}
                  onClick={() => set(t.qty_from)}
                  className={`absolute top-0 flex min-h-9 -translate-x-1/2 flex-col items-center px-1 text-xs leading-tight whitespace-nowrap ${state === 'next' ? 'font-bold text-save' : 'text-ink-soft'}`}
                  style={{ left: pct(pos) }}
                >
                  {!compact && <span className={state === 'next' ? '' : 'text-ink'}>{count(t.qty_from)}</span>}
                  <span>{shortMoney(t.unit_price)}</span>
                </button>
              ) : null,
            )}
            {endRoom && (
              <span className="absolute top-0 right-0 text-xs text-ink-soft" aria-hidden="true">
                {endText}
              </span>
            )}
          </div>
        )}
      </div>
      {multiTier && (
        <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-soft" aria-label="Key">
          <li className="flex items-center gap-1.5"><span className="inline-block h-2 w-4 rounded-sm bg-cyan" />Current tier</li>
          {zones.length > 0 && <li className="flex items-center gap-1.5"><span className="tier-overpay inline-block h-2 w-4 rounded-sm" />Overpay zone (cheaper to order a higher break)</li>}
          <li className="flex items-center gap-1.5"><span className="inline-block size-2.5 rounded-full border-2 border-save bg-save-wash" />Next price break</li>
          {belowSeg && <li className="flex items-center gap-1.5"><span className="tier-hatch inline-block h-2 w-4 rounded-sm" />Below minimum</li>}
        </ul>
      )}
    </figure>
  )
}

function NextLine({ next, withAddons, block }: { next: NonNullable<TierPoint['next']>; withAddons?: boolean; block?: boolean }) {
  const text = `Add ${count(next.unitsToNext)} more → ${shortMoney(next.tier.unit_price)} each${withAddons ? ' incl. add-ons' : ''}`
  return block ? <p className="font-semibold whitespace-nowrap text-save">{text}</p> : <span className="block font-semibold text-save">{text}</span>
}
