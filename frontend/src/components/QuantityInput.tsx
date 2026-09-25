import { plural } from '../lib/format'

interface Props {
  value: string
  onChange: (value: string) => void
  unit: string
  minQty: number
  error: string | null
  hint?: React.ReactNode
}

function stepFor(minQty: number) {
  if (minQty >= 100) return 50
  if (minQty >= 10) return 10
  return 1
}

export function QuantityInput({ value, onChange, unit, minQty, error, hint }: Props) {
  const step = stepFor(minQty)
  const current = Number(value) || 0
  const bump = (delta: number) => onChange(String(Math.max(1, Math.round(current + delta))))

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="quantity" className="text-sm font-semibold text-ink-soft">
        Quantity <span className="font-normal">({plural(2, unit)})</span>
      </label>
      <div className="flex items-stretch gap-2">
        <button
          type="button"
          className="field w-12! shrink-0 text-xl font-semibold"
          onClick={() => bump(-step)}
          aria-label={`${step} fewer`}
        >
          −
        </button>
        <input
          id="quantity"
          className="field type-expanded text-center text-lg font-semibold"
          inputMode="numeric"
          autoComplete="off"
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/[^\d]/g, ''))}
          aria-invalid={error ? 'true' : undefined}
          aria-describedby="quantity-help"
        />
        <button
          type="button"
          className="field w-12! shrink-0 text-xl font-semibold"
          onClick={() => bump(step)}
          aria-label={`${step} more`}
        >
          +
        </button>
      </div>
      <p id="quantity-help" className={`text-sm ${error ? 'text-stop' : 'text-ink-soft'}`}>
        {error ?? hint}
      </p>
    </div>
  )
}
