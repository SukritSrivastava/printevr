import '@testing-library/jest-dom/vitest'
import { beforeEach } from 'vitest'

// jsdom keeps one history per test file; every test starts on a fresh calculator URL.
beforeEach(() => {
  window.history.replaceState(null, '', '/')
})

// ScrollRestoration scrolls on every navigation; jsdom has no layout to scroll.
window.scrollTo = (() => {}) as typeof window.scrollTo
