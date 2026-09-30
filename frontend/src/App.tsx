import { keepPreviousData, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { ApiError, calculate, fetchCatalog, fetchSession, logout } from './api/client'
import type { InvoiceSettings } from './api/invoiceTypes'
import type { CalculateRequest, Catalog, TierSchedule } from './api/types'
import { fetchInvoiceSettings } from './api/invoices'
import { useCart, CartProvider } from './cart/CartProvider'
import { AddonList } from './components/AddonList'
import { AddToCartButton } from './components/AddToCartButton'
import { CartPage } from './components/CartPage'
import { CustomItemDialog } from './components/CustomItemDialog'
import { StaffProvider } from './components/StaffLoginDialog'
import { ToastProvider } from './components/Toast'
import { CustomSizeInputs } from './components/CustomSizeInputs'
import { PasswordPage } from './components/PasswordPage'
import { ProductPicker } from './components/ProductPicker'
import { QuantityInput } from './components/QuantityInput'
import { ReceiptCard, type ReceiptState } from './components/ReceiptCard'
import { TierSlider, type ServerTier } from './components/TierSlider'
import { defaultConfig, fromSearch, toSearch, type CalcConfig } from './lib/calcUrl'
import { count, qtyWithUnit } from './lib/format'
import { CUSTOM_SIZE, DIM_FIELDS, dimensionError, findItem, normalize, quantityError, supportsCustom } from './lib/selection'
import { CALCULATOR, CART, CalculatorLinkProvider, LOGIN, useAppNav, useCalculatorUrl, useDocumentTitle, useHistoryTracking } from './nav'

export const DEBOUNCE_MS = 250

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return debounced
}

/** Requests that differ only in quantity (or billing) share one tier schedule. */
const scheduleKey = (r: Omit<CalculateRequest, 'quantity'>) =>
  JSON.stringify([r.product_id, r.item_id, r.options, r.custom_dimensions, r.addons])

const isSignedOut = (err: unknown) => err instanceof ApiError && err.code === 'UNAUTHENTICATED'

/** Every screen has its own URL (BRD-tier-slider-back-nav 5.1); the whole app sits under one route. */
export default function App() {
  return (
    <BrowserRouter>
      <Root />
    </BrowserRouter>
  )
}

/** Password gate: /login shows the password page; once it's accepted, the page that was asked for opens. */
function Root() {
  const queryClient = useQueryClient()
  const location = useLocation()
  const navigate = useNavigate()
  const sessionQuery = useQuery({ queryKey: ['session'], queryFn: ({ signal }) => fetchSession(signal), retry: 1 })
  const locked = sessionQuery.data ? !sessionQuery.data.authenticated : false
  useHistoryTracking()

  useEffect(() => {
    if (!sessionQuery.data) return
    if (locked && location.pathname !== LOGIN) {
      navigate(LOGIN, { replace: true, state: { from: location.pathname + location.search } })
    } else if (!locked && location.pathname === LOGIN) {
      const from = (location.state as { from?: string } | null)?.from
      navigate(from && from !== LOGIN ? from : CALCULATOR, { replace: true })
    }
  }, [locked, sessionQuery.data, location, navigate])

  const signedOut = () => {
    queryClient.removeQueries({ queryKey: ['catalog'] })
    queryClient.removeQueries({ queryKey: ['calculate'] })
    queryClient.setQueryData(['session'], { authenticated: false, password_required: true })
  }

  let page: React.ReactNode
  if (sessionQuery.isPending) {
    page = <div className="min-h-dvh bg-sheet" aria-busy="true" />
  } else if (sessionQuery.isError) {
    page = (
      <Shell>
        <ServerError message="Check that the server is running, then retry." onRetry={() => sessionQuery.refetch()} />
      </Shell>
    )
  } else if (locked !== (location.pathname === LOGIN)) {
    page = null // on its way to (or away from) /login
  } else if (locked) {
    page = <SignIn onUnlocked={() => queryClient.setQueryData(['session'], { authenticated: true, password_required: true })} />
  } else {
    const onSignOut = sessionQuery.data.password_required
      ? () => {
          logout().finally(signedOut)
        }
      : undefined
    page = (
      <Shell onSignOut={onSignOut}>
        <CatalogGate onSignedOut={signedOut} />
      </Shell>
    )
  }
  return page
}

function SignIn({ onUnlocked }: { onUnlocked: () => void }) {
  useDocumentTitle('Sign in')
  return <PasswordPage onUnlocked={onUnlocked} />
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
  return <Workspace catalog={catalogQuery.data} onSignedOut={onSignedOut} />
}

// The Invoices page (components/InvoicesPage.tsx) is switched off for now: only Calculator and Cart.
type View = 'calculator' | 'cart'

const VIEW_PATHS: Record<View, string> = { calculator: CALCULATOR, cart: CART }
const TITLES: Record<string, string> = { [CALCULATOR]: 'Calculator', [CART]: 'Cart', '/checkout': 'Cart' }

/** Calculator and Cart. The stores sit above the screens, so switching screens keeps them. */
function Workspace({ catalog, onSignedOut }: { catalog: Catalog; onSignedOut: () => void }) {
  const settingsQuery = useQuery({
    queryKey: ['invoice-settings'],
    queryFn: ({ signal }) => fetchInvoiceSettings(signal),
    staleTime: Infinity,
    retry: 1,
  })
  return (
    <CalculatorLinkProvider>
      <ToastProvider>
        <StaffProvider required={settingsQuery.data?.staff_passcode ?? true}>
          <CartProvider>
            <Screens catalog={catalog} onSignedOut={onSignedOut} settingsQuery={settingsQuery} />
            <CustomItemHost />
          </CartProvider>
        </StaffProvider>
      </ToastProvider>
    </CalculatorLinkProvider>
  )
}

/** The calculator stays mounted (hidden) on other screens so its selection survives. */
function Screens({
  catalog,
  onSignedOut,
  settingsQuery,
}: {
  catalog: Catalog
  onSignedOut: () => void
  settingsQuery: UseQueryResult<InvoiceSettings>
}) {
  const { pathname } = useLocation()
  const { go, backTo } = useAppNav()
  const view = (Object.keys(VIEW_PATHS) as View[]).find((v) => VIEW_PATHS[v] === pathname) ?? null
  useDocumentTitle(TITLES[pathname] ?? 'Page not found')
  return (
    <>
      <ViewTabs view={view} onView={(v) => go(VIEW_PATHS[v])} />
      <div hidden={view !== 'calculator'}>
        <QuoteDesk catalog={catalog} onSignedOut={onSignedOut} onViewCart={() => go(CART)} />
      </div>
      <Routes>
        <Route path={CALCULATOR} element={null} />
        <Route path={CART} element={<CartPage onCalculator={() => backTo(CALCULATOR)} invoiceSettings={settingsQuery.data} />} />
        {/* The checkout form is part of the cart (M0 screen inventory). */}
        <Route path="/checkout" element={<Navigate to={CART} replace />} />
        {/* The Invoices page (components/InvoicesPage.tsx) is switched off for now, so /invoices is not found. */}
        <Route path="*" element={<NotFound />} />
      </Routes>
    </>
  )
}

function NotFound() {
  const { href } = useAppNav()
  return (
    <main className="mx-auto flex max-w-3xl flex-col items-start gap-4 px-4 py-10 sm:px-6">
      <h1 className="type-expanded text-2xl font-bold">Page not found</h1>
      <p className="text-ink-soft">There's nothing at this address.</p>
      <Link to={href(CALCULATOR)} className="rounded-md bg-ink px-4 py-2.5 font-semibold text-stock">
        Go to the calculator
      </Link>
    </main>
  )
}

function CustomItemHost() {
  const { customItem } = useCart()
  return customItem ? <CustomItemDialog /> : null
}

function ViewTabs({ view, onView }: { view: View | null; onView: (v: View) => void }) {
  const { lines } = useCart()
  const tab = (v: View, label: React.ReactNode, extra?: string) => (
    <button
      type="button"
      onClick={() => onView(v)}
      aria-current={view === v ? 'page' : undefined}
      className={`flex items-center gap-2 border-b-[3px] px-3 py-2.5 font-semibold ${view === v ? 'border-cyan text-ink' : 'border-transparent text-ink-soft hover:text-ink'} ${extra ?? ''}`}
    >
      {label}
    </button>
  )
  return (
    <nav className="border-b border-rule bg-stock" aria-label="Sections">
      <div className="mx-auto flex max-w-6xl gap-1 px-2 sm:px-4">
        {tab('calculator', 'Calculator')}
        {tab(
          'cart',
          <>
            Cart
            <span
              className={`min-w-6 rounded-full px-1.5 text-center text-sm ${lines.length ? 'bg-cyan text-stock' : 'bg-sheet text-ink-soft'}`}
              aria-label={`${lines.length} line${lines.length === 1 ? '' : 's'}`}
              data-testid="cart-count"
            >
              {lines.length}
            </span>
          </>,
        )}
      </div>
    </nav>
  )
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

export function QuoteDesk({
  catalog,
  onSignedOut,
  onViewCart,
}: {
  catalog: Catalog
  onSignedOut?: () => void
  onViewCart?: () => void
}) {
  const products = useMemo(() => new Map(catalog.categories.flatMap((c) => c.products).map((p) => [p.id, p])), [catalog])
  const location = useLocation()
  // The configuration lives in the URL query (FR-B3); an unreadable link falls back with a notice (FR-B4).
  const [opened] = useState(() => fromSearch(location.pathname === CALCULATOR ? location.search : '', catalog))
  const [config, setConfig] = useState<CalcConfig>(opened.config)
  const [notice, setNotice] = useState<string | null>(opened.notice)
  const { selection, qty, dims, dimUnit, outdoor, addons, billing } = config
  const product = products.get(config.productId)!
  const set = (patch: Partial<CalcConfig>) => setConfig((c) => ({ ...c, ...patch }))
  const setQty = (value: string) => set({ qty: value })

  const search = toSearch(config, product)
  useCalculatorUrl(search, (target) => {
    const parsed = fromSearch(target, catalog)
    const changed = toSearch(parsed.config, products.get(parsed.config.productId)!) !== search
    if (changed) setConfig(parsed.config)
    if (parsed.notice || changed) setNotice(parsed.notice)
  })

  const chooseProduct = (id: string) => {
    const next = products.get(id)!
    setConfig((c) => ({ ...defaultConfig(next), dimUnit: c.dimUnit, outdoor: c.outdoor, billing: c.billing }))
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

  // Everything the quote depends on except the quantity (which the tier slider changes every frame).
  const selectionRequest: Omit<CalculateRequest, 'quantity'> | null = (() => {
    const base = {
      product_id: product.id,
      addons: addons.filter((id) => availableAddons.some((a) => a.id === id)),
      billing_type: billing,
      ...(isOutdoor
        ? { outdoor: { width: Number(outdoor.width), height: Number(outdoor.height), pieces: Number(outdoor.pieces) } }
        : {}),
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
  const request: CalculateRequest | null =
    selectionRequest && quantity !== null && quantity > 0 && !qtyError ? { ...selectionRequest, quantity } : null

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

  // Tier prices for the slider come with each quote; they stay while only the quantity moves.
  const [tiers, setTiers] = useState<{ key: string; schedule: TierSchedule } | null>(null)
  useEffect(() => {
    const schedule = quoteQuery.data?.data.tier_schedule
    if (schedule && debouncedKey && !quoteQuery.isPlaceholderData) {
      setTiers({ key: scheduleKey(JSON.parse(debouncedKey) as CalculateRequest), schedule })
    }
  }, [quoteQuery.data, quoteQuery.isPlaceholderData, debouncedKey])
  const schedule = selectionRequest && tiers?.key === scheduleKey(selectionRequest) ? tiers.schedule : null
  const confirmed = !loading && !quoteQuery.isPlaceholderData && quoteQuery.data?.status === 'success' ? quoteQuery.data.data : null
  const serverTier: ServerTier | null = confirmed
    ? {
        requested: confirmed.quantity.requested,
        tierFrom: confirmed.pricing.tier_applied.qty_from,
        unitsToNext: confirmed.pricing.next_tier?.units_to_next ?? null,
      }
    : null
  const perUnitAddons = availableAddons.some((a) => a.basis === 'per_unit' && addons.includes(a.id))
  const productionTime = item?.production_time ?? product.production_time

  return (
    <main className="mx-auto grid max-w-6xl gap-6 px-4 py-6 sm:px-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,27rem)] lg:gap-10 lg:py-10">
      <form className="flex flex-col gap-6" onSubmit={(e) => e.preventDefault()} aria-label="Quote setup">
        {notice && (
          <div role="status" className="flex items-start justify-between gap-3 rounded-md bg-warn-wash px-3 py-2.5 text-sm text-warn">
            <p>{notice}</p>
            <button type="button" className="shrink-0 font-semibold underline" onClick={() => setNotice(null)}>
              Dismiss
            </button>
          </div>
        )}
        <ProductPicker
          catalog={catalog}
          product={product}
          selection={selection}
          onProduct={chooseProduct}
          onSelection={(s) => set({ selection: normalize(product, s) })}
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
            onChange={(values) => set({ dims: values })}
            onUnit={(unit) => set({ dimUnit: unit })}
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
                      set({ outdoor: { ...outdoor, [key]: e.target.value.replace(key === 'pieces' ? /[^\d]/g : /[^\d.]/g, '') } })
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

        {schedule && (
          <TierSlider
            schedule={schedule}
            quantity={isOutdoor ? outdoorSqft : qtyError ? null : Number(qty)}
            unit={product.sale_unit}
            onChange={isOutdoor ? undefined : (n) => setQty(String(n))}
            withAddons={perUnitAddons}
            server={serverTier}
          />
        )}

        <AddonList
          addons={availableAddons}
          selected={addons}
          unit={product.sale_unit}
          onToggle={(id) => set({ addons: addons.includes(id) ? addons.filter((a) => a !== id) : [...addons, id] })}
        />

        {catalog.show_invoice_billing && (
          <fieldset className="flex gap-4">
            <legend className="mb-1.5 text-sm font-semibold text-ink-soft">Billing</legend>
            {(['gst', 'invoice'] as const).map((b) => (
              <label key={b} className="flex items-center gap-2">
                <input type="radio" name="billing" className="accent-cyan" checked={billing === b} onChange={() => set({ billing: b })} />
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
          action={
            onViewCart && (
              <AddToCartButton
                response={receipt.kind === 'response' ? receipt.response : undefined}
                request={debouncedKey ? (JSON.parse(debouncedKey) as CalculateRequest) : null}
                disabled={loading || receipt.kind !== 'response'}
                product={product}
                item={item}
                onViewCart={onViewCart}
              />
            )
          }
        />
      </div>
    </main>
  )
}
