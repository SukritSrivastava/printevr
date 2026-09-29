import { useId } from 'react'
import type { SpecLine } from '../api/invoiceTypes'

interface Props {
  legend: string
  items: SpecLine[]
  max: number
  onChange: (items: SpecLine[]) => void
}

export const LABEL_MAX = 60
export const VALUE_MAX = 120

/** Editable list of { label, value, emphasis } rows: add, remove, reorder (FR-C3.2). */
export function SpecListEditor({ legend, items, max, onChange }: Props) {
  const id = useId()
  const set = (i: number, patch: Partial<SpecLine>) => onChange(items.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  const move = (i: number, by: number) => {
    const j = i + by
    if (j < 0 || j >= items.length) return
    const next = [...items]
    ;[next[i], next[j]] = [next[j], next[i]]
    onChange(next)
  }

  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1 text-sm font-semibold text-ink-soft">
        {legend} <span className="font-normal">({items.length}/{max})</span>
      </legend>
      {items.map((s, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,2fr)_minmax(0,3fr)] gap-2 rounded-md border border-rule p-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,3fr)_auto]">
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-l${i}`} className="text-xs text-ink-soft">
              Label
            </label>
            <input
              id={`${id}-l${i}`}
              className="field min-h-10!"
              maxLength={LABEL_MAX}
              value={s.label ?? ''}
              placeholder="(none)"
              onChange={(e) => set(i, { label: e.target.value || null })}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-v${i}`} className="text-xs text-ink-soft">
              Value
            </label>
            <input
              id={`${id}-v${i}`}
              className="field min-h-10!"
              maxLength={VALUE_MAX}
              value={s.value}
              onChange={(e) => set(i, { value: e.target.value })}
              aria-invalid={s.value.trim() ? undefined : 'true'}
            />
          </div>
          <div className="col-span-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm sm:col-span-1 sm:self-end sm:pb-2">
            <label className="flex items-center gap-1.5">
              <input type="checkbox" className="accent-cyan" checked={s.emphasis} onChange={(e) => set(i, { emphasis: e.target.checked })} />
              Bold value
            </label>
            <button type="button" className="px-1 text-ink-soft hover:text-ink disabled:opacity-30" onClick={() => move(i, -1)} disabled={i === 0} aria-label={`Move ${legend.toLowerCase()} row ${i + 1} up`}>
              ↑
            </button>
            <button type="button" className="px-1 text-ink-soft hover:text-ink disabled:opacity-30" onClick={() => move(i, 1)} disabled={i === items.length - 1} aria-label={`Move ${legend.toLowerCase()} row ${i + 1} down`}>
              ↓
            </button>
            <button type="button" className="px-1 text-stop hover:underline" onClick={() => onChange(items.filter((_, j) => j !== i))} aria-label={`Remove ${legend.toLowerCase()} row ${i + 1}`}>
              Remove
            </button>
          </div>
        </div>
      ))}
      {items.length < max && (
        <button
          type="button"
          className="self-start rounded-md border border-dashed border-ink-soft px-3 py-1.5 text-sm hover:border-ink"
          onClick={() => onChange([...items, { label: '', value: '', emphasis: false }])}
        >
          + Add {legend.toLowerCase().replace(/s$/, '')}
        </button>
      )}
    </fieldset>
  )
}
