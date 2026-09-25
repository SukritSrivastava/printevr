import { keepPreviousData, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { ApiError, calculate, fetchCatalog, fetchSession, logout } from './api/client'
import type { BillingType, CalculateRequest, Catalog, CatalogProduct } from './api/types'
import { AddonList } from './components/AddonList'
import { CustomSizeInputs, type DimValues } from './components/CustomSizeInputs'
import { PasswordPage } from './components/PasswordPage'
import { ProductPicker } from './components/ProductPicker'
import { QuantityInput } from './components/QuantityInput'
import { ReceiptCard, type ReceiptState } from './components/ReceiptCard'
import { TierLadder } from './components/TierLadder'
import { count, qtyWithUnit } from './lib/format'
import {
  CUSTOM_SIZE,
  DIM_FIELDS,
  dimensionError,
  findItem,
  normalize,
  quantityError,
  supportsCustom,
  type Selection,
} from './lib/selection'

export const DEBOUNCE_MS = 250
const EMPTY_DIMS: DimValues = { length: '', width: '', height: '', side: '' }

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

const LOGIN_PATH = '/login'

const isSignedOut = (err: unknown) => err instanceof ApiError && err.code === 'UNAUTHENTICATED'

/** Password gate: /login shows the password page; once it's accepted, the quote desk opens at /. */
export default function App() {
  const queryClient = useQueryClient()
  const sessionQuery = useQuery({ queryKey: ['session'], queryFn: ({ signal }) => fetchSession(signal), retry: 1 })
  const locked = sessionQuery.data ? !sessionQuery.data.authenticated : false

  useEffect(() => {
    if (!sessionQuery.data) return
    const target = locked ? LOGIN_PATH : window.location.pathname === LOGIN_PATH ? '/' : null
    if (target && window.location.pathname !== target) window.history.replaceState(null, '', target)
  }, [locked, sessionQuery.data])

  const signedOut = () => {
    queryClient.removeQueries({ queryKey: ['catalog'] })
    queryClient.removeQueries({ queryKey: ['calculate'] })
    queryClient.setQueryData(['session'], { authenticated: false, password_required: true })
  }

  if (sessionQuery.isPending) return <div className="min-h-dvh bg-sheet" aria-busy="true" />
  if (sessionQuery.isError) {
    return (
      <Shell>
        <ServerError message="Check that the server is running, then retry." onRetry={() => sessionQuery.refetch()} />
      </Shell>
    )
  }
  if (locked) {
    return <PasswordPage onUnlocked={() => queryClient.setQueryData(['session'], { authenticated: true, password_required: true })} />
  }
  const onSignOut = sessionQuery.data.password_required
    ? () => {
        logout().finally(signedOut)
      }
    : undefined
  return (
    <Shell onSignOut={onSignOut}>
      <CatalogGate onSignedOut={signedOut} />
    </Shell>
  )
}

function CatalogGate({ onSignedOut }: { onSignedOut: () => void }) {
  const catalogQuery = useQuery({ queryKey: ['catalog'], queryFn: ({ signal }) => fetchCatalog(signal), staleTime: Infinity, retry: 1 })

  useEffect(() => {
    if (isSignedOut(catalogQuery.error)) onSignedOut()
  }, [catalogQuery.error, onSignedOut])

  if (catalogQuery.isPending) {
    return <p className="p-8 text-ink-soft">Loading the price catalogue…</p>
  }
  if (catalogQuery.isError) {
    const err = catalogQuery.error
    return (
      <ServerError
        title={err instanceof ApiError && err.code === 'DATA_NOT_LOADED' ? 'The price sheet failed to load' : undefined}
        message={err instanceof ApiError ? String(err.details.reason ?? err.message) : 'Check that the server is running, then retry.'}
        onRetry={() => catalogQuery.refetch()}
      />
    )
  }
  return <QuoteDesk catalog={catalogQuery.data} onSignedOut={onSignedOut} />
}

function ServerError({ title, message, onRetry }: { title?: string; message: string; onRetry: () => void }) {
  return (
    <div className="m-6 flex max-w-lg flex-col items-start gap-3 rounded-md bg-stock p-6">
      <h2 className="type-expanded text-lg font-bold text-stop">{title ?? "Can't reach the pricing server"}</h2>
      <p className="text-ink-soft">{message}</p>
      <button type="button" className="rounded-md bg-ink px-4 py-2 font-semibold text-stock" onClick={onRetry}>
        Retry
      </button>
    </div>
  )
}

function Shell({ children, onSignOut }: { children: React.ReactNode; onSignOut?: () => void }) {
  return (
    <div className="min-h-dvh">
      <header className="bg-ink text-stock">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
          <h1 className="type-expanded text-lg font-extrabold tracking-tight">
            Printevr <span className="font-normal text-cyan">Quote Desk</span>
          </h1>
          <div className="flex items-center gap-4 text-sm">
            <p className="opacity-75 max-sm:hidden">2025-26 catalogue</p>
            {onSignOut && (
              <button type="button" onClick={onSignOut} className="rounded-md border border-stock/40 px-3 py-1 hover:bg-stock/10">
                Sign out
              </button>
            )}
          </div>
        </div>
      </header>
      {children}
    </div>
  )
}

function firstProduct(catalog: Catalog): CatalogProduct {
  const all = catalog.categories.flatMap((c) => c.products)
  return all.find((p) => p.id === 'rigid_boxes') ?? all[0]
}

export function QuoteDesk({ catalog, onSignedOut }: { catalog: Catalog; onSignedOut?: () => void }) {
  const products = useMemo(() => new Map(catalog.categories.flatMap((c) => c.products).map((p) => [p.id, p])), [catalog])
  const [productId, setProductId] = useState(() => firstProduct(catalog).id)
  const product = products.get(productId)!
  const [selection, setSelection] = useState<Selection>(() =>
    normalize(product, { size: '', option_1: null, option_2: null }),
  )
  const [qty, setQty] = useState(String(product.min_qty))
  const [dims, setDims] = useState<DimValues>(EMPTY_DIMS)
  const [dimUnit, setDimUnit] = useState<'in' | 'cm'>('in')
  const [outdoor, setOutdoor] = useState({ width: '', height: '', pieces: '1' })
  const [addons, setAddons] = useState<string[]>([])
  const [billing, setBilling] = useState<BillingType>('gst')

  const chooseProduct = (id: string) => {
    const next = products.get(id)!
    setProductId(id)
    setSelection(normalize(next, { size: '', option_1: null, option_2: null }))
    setQty(String(next.min_qty))
    setAddons([])
    setDims(EMPTY_DIMS)
  }

  const custom = selection.size === CUSTOM_SIZE && supportsCustom(product.custom_dims)
  const item = findItem(product, selection)
  const isOutdoor = product.custom_dims === 'area_sqft'
  const availableAddons = product.addons.filter((a) => !a.from_sheet || item?.has_sample)

  // Outdoor: the UI multiplies width × height × pieces into square feet (FR-4).
  const outdoorSqft = (() => {
    const w = Number(outdoor.width), h = Number(outdoor.height), n = Number(outdoor.pieces)
    if (!(w > 0 && h > 0 && n >= 1 && Number.isInteger(n))) return null
    return Math.round(w * h * n * 100) / 100
  })()
  const quantity = isOutdoor ? outdoorSqft : Number(qty)
  const qtyError = isOutdoor ? null : quantityError(qty, product.custom_dims, product.sale_unit)

  const request: CalculateRequest | null = (() => {
    if (quantity === null || !(quantity > 0) || qtyError) return null
    const base = {
      product_id: product.id,
      quantity,
      addons: addons.filter((id) => availableAddons.some((a) => a.id === id)),
      billing_type: billing,
    }
    if (custom) {
      const fields = DIM_FIELDS[product.custom_dims as 'box' | 'bag' | 'flat']
      if (fields.some((f) => dimensionError(dims[f.key], dimUnit))) return null
      return {
        ...base,
        item_id: null,
        options: { option_1: selection.option_1, option_2: selection.option_2 },
        custom_dimensions: { ...Object.fromEntries(fields.map((f) => [f.key, Number(dims[f.key])])), unit: dimUnit },
      }
    }
    if (!item) return null
    return { ...base, item_id: item.id, options: {}, custom_dimensions: null }
  })()

  const requestKey = request ? JSON.stringify(request) : null
  const debouncedKey = useDebounced(requestKey, DEBOUNCE_MS)
  const queryClient = useQueryClient()
  const quoteQuery = useQuery({
    queryKey: ['calculate', debouncedKey],
    queryFn: ({ signal }) => calculate(JSON.parse(debouncedKey!) as CalculateRequest, signal),
    enabled: debouncedKey !== null,
    placeholderData: keepPreviousData,
    retry: false,
    staleTime: 60_000,
  })
  // Cancel any in-flight quote that is no longer the current one.
  useEffect(() => {
    queryClient.cancelQueries({
      queryKey: ['calculate'],
      predicate: (q) => q.queryKey[1] !== debouncedKey,
    })
  }, [debouncedKey, queryClient])

  useEffect(() => {
    if (isSignedOut(quoteQuery.error)) onSignedOut?.()
  }, [quoteQuery.error, onSignedOut])

  const receipt: ReceiptState = (() => {
    if (quoteQuery.isError && !quoteQuery.isFetching) {
      const err = quoteQuery.error
      if (err instanceof ApiError) return { kind: 'error', message: err.message, network: false }
      return { kind: 'error', message: (err as Error).message, network: true }
    }
    if (quoteQuery.data && requestKey !== null) return { kind: 'response', response: quoteQuery.data }
    if (custom) return { kind: 'idle', message: 'Enter the custom dimensions to see a price.' }
    if (isOutdoor) return { kind: 'idle', message: 'Enter the width, height and number of pieces.' }
    return { kind: 'idle', message: qtyError ?? 'Pick a product to start a quote.' }
  })()
  const loading = requestKey !== null && (requestKey !== debouncedKey || quoteQuery.isFetching)

  const breakpoints = item?.breakpoints ?? product.breakpoints
  const productionTime = item?.production_time ?? product.production_time

  return (
    <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,27rem)] lg:gap-10 lg:py-10">
      <form className="flex flex-col gap-6" onSubmit={(e) => e.preventDefault()} aria-label="Quote setup">
        <ProductPicker
          catalog={catalog}
          product={product}
          selection={selection}
          onProduct={chooseProduct}
          onSelection={(s) => setSelection(normalize(product, s))}
        />

        <p className="-mt-2 text-sm text-ink-soft">
          Priced per {product.sale_unit}
          {product.yield_factor > 1 && product.micro_unit
            ? ` (${product.micro_approx ? 'approx. ' : ''}${count(product.yield_factor)} ${product.micro_unit})`
            : ''}
          . Minimum order {qtyWithUnit(product.min_qty, product.sale_unit)}. Production {productionTime}.
          {product.max_qty ? ` Above ${count(product.max_qty)} needs a manual quote.` : ''}
        </p>

        {custom && (
          <CustomSizeInputs
            kind={product.custom_dims as 'box' | 'bag' | 'flat'}
            values={dims}
            unit={dimUnit}
            onChange={setDims}
            onUnit={setDimUnit}
          />
        )}

        {isOutdoor ? (
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1.5 text-sm font-semibold text-ink-soft">Print size</legend>
            <div className="grid grid-cols-3 gap-3">
              {(
                [
                  ['width', 'Width (ft)'],
                  ['height', 'Height (ft)'],
                  ['pieces', 'Pieces'],
                ] as const
              ).map(([key, label]) => (
                <div key={key} className="flex min-w-0 flex-col gap-1">
                  <label htmlFor={`outdoor-${key}`} className="text-sm text-ink-soft">
                    {label}
                  </label>
                  <input
                    id={`outdoor-${key}`}
                    className="field text-center font-semibold"
                    inputMode={key === 'pieces' ? 'numeric' : 'decimal'}
                    value={outdoor[key]}
                    onChange={(e) =>
                      setOutdoor({ ...outdoor, [key]: e.target.value.replace(key === 'pieces' ? /[^\d]/g : /[^\d.]/g, '') })
                    }
                  />
                </div>
              ))}
            </div>
            <p className="text-sm text-ink-soft" aria-live="polite">
              {outdoorSqft !== null ? `${count(outdoorSqft)} sq ft in total; tiers use the whole order` : 'Tiers use the total square feet of the order'}
            </p>
          </fieldset>
        ) : (
          <QuantityInput
            value={qty}
            onChange={setQty}
            unit={product.sale_unit}
            minQty={product.min_qty}
            error={qtyError}
            hint={
              product.yield_factor > 1 && product.micro_unit && Number(qty) > 0
                ? `${qtyWithUnit(Number(qty), product.sale_unit)} = ${product.micro_approx ? 'approx. ' : ''}${count(Number(qty) * product.yield_factor)} ${product.micro_unit}`
                : undefined
            }
          />
        )}

        <TierLadder breakpoints={breakpoints} quantity={quantity ?? 0} />

        <AddonList
          addons={availableAddons}
          selected={addons}
          unit={product.sale_unit}
          onToggle={(id) => setAddons((cur) => (cur.includes(id) ? cur.filter((a) => a !== id) : [...cur, id]))}
        />

        {catalog.show_invoice_billing && (
          <fieldset className="flex gap-4">
            <legend className="mb-1.5 text-sm font-semibold text-ink-soft">Billing</legend>
            {(['gst', 'invoice'] as const).map((b) => (
              <label key={b} className="flex items-center gap-2">
                <input type="radio" name="billing" className="accent-cyan" checked={billing === b} onChange={() => setBilling(b)} />
                {b === 'gst' ? 'GST bill' : 'Invoice'}
              </label>
            ))}
          </fieldset>
        )}
      </form>

      <div className="lg:sticky lg:top-6 lg:self-start">
        <ReceiptCard
          state={receipt}
          loading={loading}
          onUseQuantity={(n) => setQty(String(n))}
          onRetry={() => quoteQuery.refetch()}
        />
      </div>
    </main>
  )
}
