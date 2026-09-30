// The calculator's configuration as a URL query (BRD-tier-slider-back-nav 5.1, FR-B3, FR-B4):
//   /?product=rigid_boxes&item=rigid_boxes/3x3x2-in/top-bottom&qty=450&billing=gst
//   /?product=rigid_boxes&opt1=top-bottom&custom=3.5x3.5x2in&qty=300&billing=gst
// Pure functions: catalogue in, configuration or query string out.
import type { BillingType, Catalog, CatalogProduct, OptionKey } from '../api/types'
import { CUSTOM_SIZE, DIM_FIELDS, findItem, normalize, optionValues, supportsCustom, type Selection } from './selection'

export type DimValues = Record<'length' | 'width' | 'height' | 'side', string>
export interface OutdoorValues {
  width: string
  height: string
  pieces: string
}

export interface CalcConfig {
  productId: string
  selection: Selection
  qty: string
  dims: DimValues
  dimUnit: 'in' | 'cm'
  outdoor: OutdoorValues
  addons: string[]
  billing: BillingType
}

export const EMPTY_DIMS: DimValues = { length: '', width: '', height: '', side: '' }
const DECIMAL = /^\d*\.?\d*$/
const WHOLE = /^[1-9]\d*$/

/** Same rule as the server's item-id slugs (backend/app/loader.py `slug`). */
export function slug(text: string): string {
  return text
    .toLowerCase()
    .replace(/\s*×\s*/g, 'x')
    .replace(/[^a-z0-9.]+/g, '-')
    .replace(/^[-.]+|[-.]+$/g, '')
}

export function allProducts(catalog: Catalog): CatalogProduct[] {
  return catalog.categories.flatMap((c) => c.products)
}

export function defaultProduct(catalog: Catalog): CatalogProduct {
  const all = allProducts(catalog)
  return all.find((p) => p.id === 'rigid_boxes') ?? all[0]
}

export function defaultConfig(product: CatalogProduct): CalcConfig {
  return {
    productId: product.id,
    selection: normalize(product, { size: '', option_1: null, option_2: null }),
    qty: String(product.min_qty),
    dims: EMPTY_DIMS,
    dimUnit: 'in',
    outdoor: { width: '', height: '', pieces: '1' },
    addons: [],
    billing: 'gst',
  }
}

// Query values keep '/' and ',' readable; everything else is percent-encoded.
const enc = (v: string) => encodeURIComponent(v).replace(/%2F/gi, '/').replace(/%2C/gi, ',')

export function toSearch(c: CalcConfig, product: CatalogProduct): string {
  const parts: [string, string][] = [['product', c.productId]]
  if (c.selection.size === CUSTOM_SIZE && supportsCustom(product.custom_dims)) {
    if (c.selection.option_1) parts.push(['opt1', slug(c.selection.option_1)])
    if (c.selection.option_2) parts.push(['opt2', slug(c.selection.option_2)])
    parts.push(['custom', DIM_FIELDS[product.custom_dims].map((f) => c.dims[f.key]).join('x') + c.dimUnit])
  } else {
    const item = findItem(product, c.selection)
    if (item) parts.push(['item', item.id])
  }
  if (product.custom_dims === 'area_sqft') {
    if (c.outdoor.width) parts.push(['w', c.outdoor.width])
    if (c.outdoor.height) parts.push(['h', c.outdoor.height])
    if (c.outdoor.pieces) parts.push(['pcs', c.outdoor.pieces])
  } else if (c.qty) {
    parts.push(['qty', c.qty])
  }
  if (c.addons.length) parts.push(['addons', c.addons.join(',')])
  parts.push(['billing', c.billing])
  return '?' + parts.map(([k, v]) => `${k}=${enc(v)}`).join('&')
}

export interface ParsedConfig {
  config: CalcConfig
  /** Set when the link held values that no longer exist or can't be read. */
  notice: string | null
}

/** Never throws: anything unknown falls back to the calculator's default for that field. */
export function fromSearch(search: string, catalog: Catalog): ParsedConfig {
  const params = new URLSearchParams(search)
  const problems: string[] = []
  const products = allProducts(catalog)

  const productParam = params.get('product')
  const itemParam = params.get('item')
  let product = productParam ? products.find((p) => p.id === productParam) : undefined
  if (productParam && !product) problems.push(`product "${productParam}"`)
  let item = itemParam ? product?.items.find((i) => i.id === itemParam) : undefined
  if (itemParam && !item && !product) {
    // A link with only an item id: find its product.
    product = products.find((p) => p.items.some((i) => i.id === itemParam))
    item = product?.items.find((i) => i.id === itemParam)
  }
  if (itemParam && !item) problems.push(`item "${itemParam}"`)
  product ??= defaultProduct(catalog)

  const config = defaultConfig(product)
  const customParam = params.get('custom')
  if (item) {
    config.selection = { size: item.size, option_1: item.option_1, option_2: item.option_2 }
  } else if (customParam !== null) {
    const kind = product.custom_dims
    const m = /^(.*?)(in|cm)?$/.exec(customParam)!
    const values = m[1].split('x')
    if (!supportsCustom(kind)) {
      problems.push(`custom size for ${product.name}`)
    } else if (values.length !== DIM_FIELDS[kind].length || !values.every((v) => DECIMAL.test(v))) {
      problems.push(`custom size "${customParam}"`)
    } else {
      const dims = { ...EMPTY_DIMS }
      DIM_FIELDS[kind].forEach((f, i) => (dims[f.key] = values[i]))
      config.dims = dims
      config.dimUnit = m[2] === 'cm' ? 'cm' : 'in'
      const pick = (key: OptionKey, sel: Partial<Selection>): string | null => {
        const raw = params.get(key === 'option_1' ? 'opt1' : 'opt2')
        if (raw === null) return null
        const found = optionValues(product, key, sel).find((v) => slug(v) === raw || v === raw)
        if (!found) problems.push(`${product.option_labels[key] ?? 'option'} "${raw}"`)
        return found ?? null
      }
      const option_1 = pick('option_1', { size: CUSTOM_SIZE })
      const option_2 = pick('option_2', { size: CUSTOM_SIZE, option_1 })
      config.selection = normalize(product, { size: CUSTOM_SIZE, option_1, option_2 })
    }
  }

  const qty = params.get('qty')
  if (qty !== null) {
    if (WHOLE.test(qty)) config.qty = qty
    else problems.push(`quantity "${qty}"`)
  }
  if (product.custom_dims === 'area_sqft') {
    const outdoor = { width: params.get('w') ?? '', height: params.get('h') ?? '', pieces: params.get('pcs') ?? '1' }
    if (DECIMAL.test(outdoor.width) && DECIMAL.test(outdoor.height) && (outdoor.pieces === '' || WHOLE.test(outdoor.pieces))) {
      config.outdoor = outdoor
    } else {
      problems.push('print size')
    }
  }

  const addons = params.get('addons')
  if (addons) {
    const wanted = addons.split(',').filter(Boolean)
    config.addons = wanted.filter((id) => product.addons.some((a) => a.id === id))
    const unknown = wanted.filter((id) => !config.addons.includes(id))
    if (unknown.length) problems.push(`add-on ${unknown.map((u) => `"${u}"`).join(', ')}`)
  }

  const billing = params.get('billing')
  if (billing === 'invoice' && catalog.show_invoice_billing) config.billing = 'invoice'
  else if (billing !== null && billing !== 'gst') problems.push(`billing "${billing}"`)

  return {
    config,
    notice: problems.length
      ? `This link had settings the calculator doesn't recognise (${problems.join('; ')}), so it opened with the defaults for those.`
      : null,
  }
}
