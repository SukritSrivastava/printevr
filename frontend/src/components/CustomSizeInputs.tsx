import { DIM_FIELDS, dimensionError } from '../lib/selection'

export type DimValues = Record<'length' | 'width' | 'height' | 'side', string>

interface Props {
  kind: 'box' | 'bag' | 'flat'
  values: DimValues
  unit: 'in' | 'cm'
  onChange: (values: DimValues) => void
  onUnit: (unit: 'in' | 'cm') => void
}

export function CustomSizeInputs({ kind, values, unit, onChange, onUnit }: Props) {
  const fields = DIM_FIELDS[kind]
  return (
    <fieldset className="flex flex-col gap-3 rounded-md border-[1.5px] border-dashed border-cyan/60 bg-cyan-wash/50 p-4">
      <div className="flex items-center justify-between gap-3">
        <legend className="float-left text-sm font-semibold">
          Custom size{kind === 'bag' ? ' (H × L × S)' : ''}
        </legend>
        <div role="radiogroup" aria-label="Unit" className="flex overflow-hidden rounded-md border-[1.5px] border-rule bg-stock text-sm">
          {(['in', 'cm'] as const).map((u) => (
            <button
              key={u}
              type="button"
              role="radio"
              aria-checked={unit === u}
              onClick={() => onUnit(u)}
              className={`px-3 py-1 font-semibold ${unit === u ? 'bg-ink text-stock' : 'text-ink-soft'}`}
            >
              {u}
            </button>
          ))}
        </div>
      </div>
      <div className={`grid gap-3 ${fields.length === 3 ? 'grid-cols-3' : 'grid-cols-2'}`}>
        {fields.map((f) => {
          const raw = values[f.key]
          const error = raw === '' ? null : dimensionError(raw, unit)
          return (
            <div key={f.key} className="flex min-w-0 flex-col gap-1">
              <label htmlFor={`dim-${f.key}`} className="text-sm text-ink-soft">
                {f.label}
              </label>
              <input
                id={`dim-${f.key}`}
                className="field text-center font-semibold"
                inputMode="decimal"
                autoComplete="off"
                placeholder={unit}
                value={raw}
                onChange={(e) => onChange({ ...values, [f.key]: e.target.value.replace(/[^\d.]/g, '') })}
                aria-invalid={error ? 'true' : undefined}
                aria-describedby={error ? `dim-${f.key}-error` : undefined}
              />
              {error && (
                <p id={`dim-${f.key}-error`} className="text-sm text-stop">
                  {error}
                </p>
              )}
            </div>
          )
        })}
      </div>
    </fieldset>
  )
}
