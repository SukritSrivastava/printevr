import { useId } from 'react'
import type { Middle } from '../api/invoiceTypes'

/** The invoice's middle column: nothing, a short note, or a crossed-out reference price (FR-C3.6). */
export function MiddleEditor({ value, onChange }: { value: Middle; onChange: (m: Middle) => void }) {
  const id = useId()
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-semibold text-ink-soft">Middle column</legend>
      <div className="flex flex-wrap gap-4">
        {(
          [
            ['none', 'None'],
            ['note', 'Note'],
            ['reference_price', 'Reference price'],
          ] as const
        ).map(([kind, label]) => (
          <label key={kind} className="flex items-center gap-2">
            <input
              type="radio"
              name={`${id}-middle`}
              className="accent-cyan"
              checked={value.kind === kind}
              onChange={() =>
                onChange(kind === 'none' ? { kind } : kind === 'note' ? { kind, text: '' } : { kind, amount: '' })
              }
            />
            {label}
          </label>
        ))}
      </div>
      {value.kind === 'note' && (
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-note`} className="text-xs text-ink-soft">
            Note (40 characters)
          </label>
          <input
            id={`${id}-note`}
            className="field"
            maxLength={40}
            placeholder="Without ribbon closing :-"
            value={value.text}
            onChange={(e) => onChange({ kind: 'note', text: e.target.value })}
          />
        </div>
      )}
      {value.kind === 'reference_price' && (
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-ref`} className="text-xs text-ink-soft">
            Reference price (₹)
          </label>
          <input
            id={`${id}-ref`}
            className="field"
            inputMode="decimal"
            value={value.amount}
            onChange={(e) => onChange({ kind: 'reference_price', amount: e.target.value.replace(/[^\d.]/g, '') })}
          />
        </div>
      )}
    </fieldset>
  )
}
