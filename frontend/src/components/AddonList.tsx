import type { CatalogAddon } from '../api/types'
import { shortMoney } from '../lib/format'

interface Props {
  addons: CatalogAddon[]
  selected: string[]
  unit: string
  onToggle: (id: string) => void
}

export function AddonList({ addons, selected, unit, onToggle }: Props) {
  if (addons.length === 0) return null
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1.5 text-sm font-semibold text-ink-soft">Add-ons</legend>
      {addons.map((a) => (
        <label
          key={a.id}
          className="flex min-h-11 cursor-pointer items-center gap-3 rounded-md border-[1.5px] border-rule bg-stock px-3 py-2 has-checked:border-cyan"
        >
          <input
            type="checkbox"
            className="size-4 accent-cyan"
            checked={selected.includes(a.id)}
            onChange={() => onToggle(a.id)}
          />
          <span className="flex-1">{a.name}</span>
          <span className="text-sm text-ink-soft">
            {a.price !== null
              ? `+${shortMoney(a.price)} ${a.basis === 'per_unit' ? `per ${unit}` : 'per order'}`
              : 'Priced per item'}
          </span>
        </label>
      ))}
    </fieldset>
  )
}
