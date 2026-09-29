import type { CartLine, SpecLine } from '../api/invoiceTypes'
import type { CalculateRequest, CatalogItem, CatalogProduct, QuoteResponse } from '../api/types'
import { newId, useCart } from '../cart/CartProvider'
import { plural } from '../lib/format'
import { DIM_FIELDS, supportsCustom } from '../lib/selection'
import { useToast } from './Toast'

const HINTS = { box: '(LxWxH)', bag: '(HxLxS)', flat: '(LxW)' } as const

interface Props {
  response: QuoteResponse | undefined
  /** The exact request that produced `response`. */
  request: CalculateRequest | null
  disabled: boolean
  product: CatalogProduct
  item: CatalogItem | undefined
  onViewCart: () => void
}

function titleFor(name: string): string {
  return /^customised/i.test(name) ? `${name} printing` : `Customised ${name} printing`
}

/** The Size spec for a manual quote, from the current selection (FR-C2.4). */
function sizeSpec(product: CatalogProduct, item: CatalogItem | undefined, request: CalculateRequest | null): SpecLine | null {
  if (request?.outdoor) {
    const o = request.outdoor
    return { label: 'Size', value: `${o.width}*${o.height} ft, ${o.pieces} pcs`, emphasis: true }
  }
  const kind = product.custom_dims
  if (request?.custom_dimensions && supportsCustom(kind)) {
    const dims = request.custom_dimensions
    const numbers = DIM_FIELDS[kind].map((f) => dims[f.key]).join('*')
    return { label: 'Size', value: `${numbers} ${dims.unit} ${HINTS[kind]}`, emphasis: true }
  }
  if (item) {
    const head = supportsCustom(kind) ? item.size.split('(')[0].trim() : item.size
    const text = head.replace(/(?<=\d)\s*[×xX*]\s*(?=\d)/g, '*')
    return { label: supportsCustom(kind) ? 'Size' : product.size_label, value: supportsCustom(kind) ? `${text} ${HINTS[kind]}` : text, emphasis: true }
  }
  return null
}

export function AddToCartButton({ response, request, disabled, product, item, onViewCart }: Props) {
  const { dispatch, openCustomItem } = useCart()
  const toast = useToast()

  if (response?.status === 'manual_quote') {
    const size = sizeSpec(product, item, request)
    const options = (['option_1', 'option_2'] as const)
      .map((k): SpecLine | null => {
        const value = request?.custom_dimensions ? request.options[k] : item?.[k]
        return value ? { label: product.option_labels[k] ?? `Option ${k.at(-1)}`, value, emphasis: false } : null
      })
      .filter((s): s is SpecLine => s !== null)
    return (
      <button
        type="button"
        className="w-full rounded-md bg-ink px-4 py-3 font-semibold text-stock disabled:opacity-50"
        disabled={disabled}
        onClick={() =>
          openCustomItem({
            title: titleFor(product.name),
            specs: [...(size ? [size] : []), ...options],
            unit_label: plural(2, product.sale_unit),
          })
        }
      >
        Add as custom item
      </button>
    )
  }

  const drafts = response?.status === 'success' ? response.data.invoice_lines : undefined
  const add = () => {
    if (!drafts?.length || !request) return
    const mainId = newId()
    const lines: CartLine[] = drafts.map((d, i) => ({
      ...d,
      id: i === 0 ? mainId : newId(),
      parent_id: i === 0 ? null : mainId,
      calc_request: i === 0 ? request : null,
    }))
    dispatch({ type: 'add', lines })
    toast('Added to cart', { label: 'View cart', onClick: onViewCart })
  }

  return (
    <button
      type="button"
      className="w-full rounded-md bg-ink px-4 py-3 font-semibold text-stock disabled:opacity-50"
      disabled={disabled || !drafts?.length || !request}
      onClick={add}
    >
      Add to cart
    </button>
  )
}
