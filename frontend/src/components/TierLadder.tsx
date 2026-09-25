import type { Breakpoint } from '../api/types'
import { count } from '../lib/format'

interface Props {
  breakpoints: Breakpoint[]
  quantity: number
}

/** Tier ladder drawn as a printer's colour-control strip. Breakpoints only; prices never reach the browser. */
export function TierLadder({ breakpoints, quantity }: Props) {
  if (breakpoints.length < 2) return null
  const active = quantity < breakpoints[0].qty_from ? 0 : breakpoints.filter((b) => b.qty_from <= quantity).length - 1

  return (
    <figure className="flex flex-col gap-2">
      <figcaption className="text-sm font-semibold text-ink-soft">Volume tiers</figcaption>
      <ol className="strip" aria-label="Volume tiers">
        {breakpoints.map((b, i) => (
          <li
            key={b.qty_from}
            className={i === active ? 'active' : i < active ? 'done' : undefined}
            aria-current={i === active ? 'step' : undefined}
          >
            <div className="patch" />
            <div className={`type-condensed mt-1 truncate text-sm ${i === active ? 'font-bold text-cyan-deep' : 'text-ink-soft'}`}>
              {count(b.qty_from)}+
            </div>
          </li>
        ))}
      </ol>
    </figure>
  )
}
