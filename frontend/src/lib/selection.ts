import type { CatalogItem, CatalogProduct, CustomDimsKind, OptionKey } from '../api/types'

export const CUSTOM_SIZE = '__custom__'

export interface Selection {
  size: string
  option_1: string | null
  option_2: string | null
}

const unique = <T,>(values: T[]) => [...new Set(values)]

export function sizesFor(product: CatalogProduct): string[] {
  return unique(product.items.map((i) => i.size))
}

/** Values of an option that exist for the chosen size (and option 1, for option 2). */
export function optionValues(product: CatalogProduct, key: OptionKey, sel: Partial<Selection>): string[] {
  const custom = sel.size === CUSTOM_SIZE
  return unique(
    product.items
      .filter((i) => custom || i.size === sel.size)
      .filter((i) => key === 'option_1' || custom || i.option_1 === (sel.option_1 ?? null))
      .map((i) => i[key])
      .filter((v): v is string => v !== null),
  )
}

/** Which option dropdowns to show: every non-empty column, or only the anchor-match ones for custom sizes. */
export function visibleOptions(product: CatalogProduct, size: string): OptionKey[] {
  const keys = Object.keys(product.option_labels) as OptionKey[]
  return size === CUSTOM_SIZE ? keys.filter((k) => product.anchor_match.includes(k)) : keys
}

/** Keep the selection valid after an upstream change: any value no longer offered falls back to the first one. */
export function normalize(product: CatalogProduct, sel: Selection): Selection {
  const sizes = sizesFor(product)
  const size = sel.size === CUSTOM_SIZE && supportsCustom(product.custom_dims) ? sel.size : sizes.includes(sel.size) ? sel.size : sizes[0]
  const visible = visibleOptions(product, size)
  const pick = (key: OptionKey, current: string | null, partial: Partial<Selection>) => {
    if (!visible.includes(key)) return null
    const values = optionValues(product, key, partial)
    return current !== null && values.includes(current) ? current : (values[0] ?? null)
  }
  const option_1 = pick('option_1', sel.option_1, { size })
  const option_2 = pick('option_2', sel.option_2, { size, option_1 })
  return { size, option_1, option_2 }
}

export function findItem(product: CatalogProduct, sel: Selection): CatalogItem | undefined {
  if (sel.size === CUSTOM_SIZE) return undefined
  return product.items.find(
    (i) => i.size === sel.size && i.option_1 === sel.option_1 && i.option_2 === sel.option_2,
  )
}

export function supportsCustom(kind: CustomDimsKind): kind is 'box' | 'bag' | 'flat' {
  return kind === 'box' || kind === 'bag' || kind === 'flat'
}

export const DIM_FIELDS: Record<'box' | 'bag' | 'flat', { key: 'length' | 'width' | 'height' | 'side'; label: string }[]> = {
  box: [
    { key: 'length', label: 'Length' },
    { key: 'width', label: 'Width' },
    { key: 'height', label: 'Height' },
  ],
  bag: [
    { key: 'height', label: 'Height' },
    { key: 'length', label: 'Length' },
    { key: 'side', label: 'Side gusset' },
  ],
  flat: [
    { key: 'length', label: 'Length' },
    { key: 'width', label: 'Width' },
  ],
}

const MAX_IN = 60

/** Inline check that mirrors the server's FR-4 step 1. Returns an error message or null. */
export function dimensionError(raw: string, unit: 'in' | 'cm'): string | null {
  if (raw.trim() === '') return 'Required'
  if (!/^\d*\.?\d*$/.test(raw.trim())) return 'Numbers only'
  const n = Number(raw)
  if (!(n > 0)) return 'Must be above 0'
  if (/\.\d{3,}$/.test(raw.trim())) return 'Up to 2 decimals'
  const max = unit === 'cm' ? MAX_IN * 2.54 : MAX_IN
  if (n > max) return `At most ${unit === 'cm' ? '152.4 cm' : '60 in'}`
  return null
}

export function quantityError(raw: string, kind: CustomDimsKind, unit: string): string | null {
  if (raw.trim() === '') return 'Enter a quantity'
  const n = Number(raw)
  if (!Number.isFinite(n) || n <= 0) return 'Quantity must be at least 1'
  if (kind !== 'area_sqft' && !Number.isInteger(n)) return `Whole ${unit}s only`
  return null
}
