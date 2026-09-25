import type { Catalog, CatalogProduct, OptionKey } from '../api/types'
import { CUSTOM_SIZE, optionValues, sizesFor, supportsCustom, visibleOptions, type Selection } from '../lib/selection'

interface Props {
  catalog: Catalog
  product: CatalogProduct
  selection: Selection
  onProduct: (productId: string) => void
  onSelection: (selection: Selection) => void
}

function Select(props: {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={props.id} className="text-sm font-semibold text-ink-soft">
        {props.label}
      </label>
      <select id={props.id} className="field" value={props.value} onChange={(e) => props.onChange(e.target.value)}>
        {props.children}
      </select>
    </div>
  )
}

export function ProductPicker({ catalog, product, selection, onProduct, onSelection }: Props) {
  const category = catalog.categories.find((c) => c.products.some((p) => p.id === product.id))!
  const custom = supportsCustom(product.custom_dims)

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <Select
        id="category"
        label="Category"
        value={category.name}
        onChange={(name) => onProduct(catalog.categories.find((c) => c.name === name)!.products[0].id)}
      >
        {catalog.categories.map((c) => (
          <option key={c.name}>{c.name}</option>
        ))}
      </Select>
      <Select id="product" label="Product" value={product.id} onChange={onProduct}>
        {category.products.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </Select>
      <Select
        id="size"
        label={product.size_label}
        value={selection.size}
        onChange={(size) => onSelection({ ...selection, size })}
      >
        {sizesFor(product).map((s) => (
          <option key={s}>{s}</option>
        ))}
        {custom && <option value={CUSTOM_SIZE}>Custom size…</option>}
      </Select>
      {visibleOptions(product, selection.size).map((key: OptionKey) => (
        <Select
          key={key}
          id={key}
          label={product.option_labels[key] ?? key}
          value={selection[key] ?? ''}
          onChange={(value) => onSelection({ ...selection, [key]: value })}
        >
          {optionValues(product, key, selection).map((v) => (
            <option key={v}>{v}</option>
          ))}
        </Select>
      ))}
    </div>
  )
}
