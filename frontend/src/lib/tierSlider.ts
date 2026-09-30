// Display maths for the tier slider (BRD-tier-slider-back-nav section 4). Pure functions.
// Prices come from the server's tier_schedule and are only shown, never added up: the browser
// works out which tier a quantity falls in, how far the next break is, and whether it sits in
// an overpay zone (FR-A11). Totals always come from /api/calculate.
import type { TierSchedule, TierSpan } from '../api/types'

export interface Segment {
  from: number
  /** Exclusive: the next segment's `from`, or the slider end. */
  to: number
  weight: number
  kind: 'below_min' | 'tier'
  tier: number // index into schedule.tiers; -1 for the below-minimum segment
}

/** The below-minimum segment is narrower than a tier segment (FR-A2). */
export const BELOW_MIN_WEIGHT = 0.5
/** Release within this share of the track width of a breakpoint snaps to it (FR-A7, D3). */
export const SNAP_FRACTION = 0.015

export const hasBelowMin = (s: TierSchedule) => s.below_min_policy === 'bill_at_min' && s.min_qty > 1
export const sliderMin = (s: TierSchedule) => (hasBelowMin(s) ? 1 : s.min_qty)

/** Tier-segmented scale: each tier gets an equal width, quantity is linear inside it (FR-A2). */
export function segments(s: TierSchedule): Segment[] {
  const out: Segment[] = []
  if (hasBelowMin(s)) out.push({ from: 1, to: s.min_qty, weight: BELOW_MIN_WEIGHT, kind: 'below_min', tier: -1 })
  s.tiers.forEach((t, i) => {
    const to = i + 1 < s.tiers.length ? s.tiers[i + 1].qty_from : Math.max(s.slider_max, t.qty_from + 1)
    out.push({ from: t.qty_from, to, weight: 1, kind: 'tier', tier: i })
  })
  return out
}

const totalWeight = (segs: Segment[]) => segs.reduce((sum, g) => sum + g.weight, 0)

/** Quantity -> 0..1 along the track; quantities past either end are pinned there. */
export function positionOf(q: number, segs: Segment[]): number {
  const total = totalWeight(segs)
  let before = 0
  for (const g of segs) {
    if (q < g.to || g === segs[segs.length - 1]) {
      const within = Math.min(1, Math.max(0, (q - g.from) / (g.to - g.from)))
      return Math.min(1, Math.max(0, (before + g.weight * within) / total))
    }
    before += g.weight
  }
  return 1
}

/** 0..1 along the track -> whole quantity. */
export function quantityAt(pos: number, segs: Segment[]): number {
  const total = totalWeight(segs)
  let at = Math.min(1, Math.max(0, pos)) * total
  for (const g of segs) {
    if (at <= g.weight || g === segs[segs.length - 1]) {
      const q = g.from + (Math.min(at, g.weight) / g.weight) * (g.to - g.from)
      return Math.max(segs[0].from, Math.min(segs[segs.length - 1].to, Math.round(q)))
    }
    at -= g.weight
  }
  return segs[segs.length - 1].to
}

export interface TierPoint {
  requested: number
  /** What the order is billed at: the minimum when below it. */
  billed: number
  belowMin: boolean
  /** Past the slider's right end (typed in). */
  beyond: boolean
  /** Above max_qty: a manual quote (FR-A9 c). */
  manual: boolean
  index: number
  tier: TierSpan
  next: { tier: TierSpan; unitsToNext: number } | null
  inOverpay: boolean
}

export function tierAt(q: number, s: TierSchedule): TierPoint {
  const belowMin = q < s.min_qty
  const billed = belowMin && s.below_min_policy === 'bill_at_min' ? s.min_qty : q
  let index = 0
  s.tiers.forEach((t, i) => {
    if (t.qty_from <= billed) index = i
  })
  const tier = s.tiers[index]
  const nextTier = s.tiers[index + 1]
  return {
    requested: q,
    billed,
    belowMin,
    beyond: q > s.slider_max,
    manual: s.max_qty !== null && q > s.max_qty,
    index,
    tier,
    next: nextTier ? { tier: nextTier, unitsToNext: nextTier.qty_from - billed } : null,
    inOverpay: s.suggest_more && tier.overpay_from !== null && billed >= tier.overpay_from && (tier.qty_to === null || billed <= tier.qty_to),
  }
}

/** FR-A7: on release, a quantity close to a breakpoint becomes that breakpoint. */
export function snap(q: number, s: TierSchedule, segs: Segment[], fraction = SNAP_FRACTION): number {
  const pos = positionOf(q, segs)
  let best: number | null = null
  let bestGap = fraction
  for (const t of s.tiers) {
    const gap = Math.abs(positionOf(t.qty_from, segs) - pos)
    if (gap <= bestGap) {
      best = t.qty_from
      bestGap = gap
    }
  }
  return best ?? q
}

/** Page Up / Page Down (FR-A8): the next breakpoint above, or the previous one below. */
export function nextBreakpoint(q: number, s: TierSchedule): number | null {
  return s.tiers.find((t) => t.qty_from > q)?.qty_from ?? null
}
export function previousBreakpoint(q: number, s: TierSchedule): number | null {
  return [...s.tiers].reverse().find((t) => t.qty_from < q)?.qty_from ?? null
}
