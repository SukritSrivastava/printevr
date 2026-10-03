// Browser Back / Forward inside the app (BRD-tier-slider-back-nav section 5).
// Screen changes push a history entry; calculator edits only replace the current one.
import { createContext, useContext, useEffect, useLayoutEffect, useRef } from 'react'
import { useLocation, useNavigate, useNavigationType } from 'react-router-dom'

export const CALCULATOR = '/'
export const CART = '/cart'
export const INVOICES = '/invoices'
export const DESIGNERS = '/designers'
export const PRODUCTION = '/production'
export const LOGIN = '/login'

/** FR-B2: calculator edits reach the URL this long after the last change. */
export const URL_DEBOUNCE_MS = 300

/** FR-B9: "Cart · Printevr" in the tab and in the browser's history menu. */
export function useDocumentTitle(title: string) {
  useEffect(() => {
    document.title = `${title} · Printevr`
  }, [title])
}

/** Position of the current entry in this tab's history, as React Router numbers it (0 = first in-app page). */
const historyIdx = (): number => (window.history.state as { idx?: number } | null)?.idx ?? 0

// Which path each in-app entry shows, so an in-app back button knows what browser Back would open.
const visited = new Map<number, string>()
// Scroll position of each entry, by position in history (a calculator URL update replaces the
// entry but keeps its place).
const scrolls = new Map<number, number>()

/**
 * Records what each history entry shows, and restores its scroll position on Back / Forward;
 * a new screen opens at the top (FR-B3).
 */
export function useHistoryTracking() {
  const location = useLocation()
  const navigationType = useNavigationType()

  useEffect(() => {
    visited.set(historyIdx(), location.pathname)
  }, [location])

  useEffect(() => {
    if ('scrollRestoration' in window.history) window.history.scrollRestoration = 'manual'
    let frame = 0
    const save = () => {
      cancelAnimationFrame(frame)
      frame = requestAnimationFrame(() => scrolls.set(historyIdx(), window.scrollY))
    }
    window.addEventListener('scroll', save, { passive: true })
    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('scroll', save)
    }
  }, [])

  useLayoutEffect(() => {
    if (navigationType === 'PUSH') window.scrollTo(0, 0)
    else if (navigationType === 'POP') window.scrollTo(0, scrolls.get(historyIdx()) ?? 0)
    // Only screen changes move the page; a calculator URL update (REPLACE) never does.
  }, [location.key])
}

interface CalculatorLink {
  /** The calculator's current query, e.g. "?product=rigid_boxes&item=...&qty=450&billing=gst". */
  search: string
  /** Write a pending (debounced) calculator URL now, before leaving the calculator. */
  flush: () => void
}

const CalculatorLinkContext = createContext<React.MutableRefObject<CalculatorLink> | null>(null)

export function CalculatorLinkProvider({ children }: { children: React.ReactNode }) {
  const link = useRef<CalculatorLink>({ search: '', flush: () => {} })
  return <CalculatorLinkContext.Provider value={link}>{children}</CalculatorLinkContext.Provider>
}

function useCalculatorLink() {
  const link = useContext(CalculatorLinkContext)
  if (!link) throw new Error('useCalculatorLink outside CalculatorLinkProvider')
  return link
}

/** Moving between screens: always a new history entry (FR-B1), plus in-app back buttons (FR-B6). */
export function useAppNav() {
  const navigate = useNavigate()
  const link = useCalculatorLink()
  const href = (path: string) => (path === CALCULATOR ? CALCULATOR + link.current.search : path)
  const go = (path: string) => {
    link.current.flush()
    navigate(href(path))
  }
  /** Go back when the previous entry is `path` inside the app; otherwise open `path` as a new entry. */
  const backTo = (path: string) => {
    const idx = historyIdx()
    if (idx > 0 && visited.get(idx - 1) === path) {
      link.current.flush()
      navigate(-1)
    } else {
      go(path)
    }
  }
  return { go, backTo, href }
}

/**
 * Keeps the calculator's configuration in its URL (FR-B2, FR-B3).
 *
 * `search` is the query the current configuration would have. It is written with `replace`,
 * 300 ms after the last change, and only while the calculator is showing. `apply` is called
 * when the calculator is (re)opened on an entry whose URL may differ from the configuration:
 * a pasted link, a refresh, or Back / Forward to an older calculator entry.
 */
export function useCalculatorUrl(search: string, apply: (search: string) => void) {
  const location = useLocation()
  const navigationType = useNavigationType()
  const navigate = useNavigate()
  const link = useCalculatorLink()
  const active = location.pathname === CALCULATOR
  // What each calculator entry should show, including an edit still waiting for its URL write,
  // so Back to an entry restores what it showed when it was left.
  const intended = useRef(new Map<number, string>())
  const latest = useRef(search)
  latest.current = search

  useEffect(() => {
    link.current = {
      search: latest.current,
      flush: () => {
        if (window.location.pathname !== CALCULATOR || window.location.search === latest.current) return
        // Straight to the history API: the router is about to leave this entry anyway.
        window.history.replaceState(window.history.state, '', CALCULATOR + latest.current)
      },
    }
  })

  // Arrival on a calculator entry.
  useEffect(() => {
    if (!active) return
    const target = (navigationType === 'POP' ? intended.current.get(historyIdx()) : undefined) ?? location.search
    apply(target)
    // Runs once per entry arrival; `apply` and `navigationType` are read as they are then.
  }, [location.key, active])

  useEffect(() => {
    if (!active) return
    intended.current.set(historyIdx(), search)
    if (search === location.search) return
    const t = setTimeout(() => navigate({ search }, { replace: true }), URL_DEBOUNCE_MS)
    return () => clearTimeout(t)
  }, [search, active, location.search, navigate])
}
