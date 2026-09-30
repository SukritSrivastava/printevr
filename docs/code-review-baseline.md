# Code review baseline (FR-C1)

Recorded on 1 October 2026 at commit `26fb063` (main), branch `feature/tier-slider-back-nav`,
before any change for `docs/BRD-tier-slider-back-nav.pdf`. Windows 11, Python 3.14.7, Node
from the repo's `package-lock.json`.

## Tests

| Suite | Command | Result |
|---|---|---|
| Backend | `cd backend && python -m pytest` | **153 passed**, 0 failed (1 Starlette deprecation warning about `httpx`) |
| Frontend | `cd frontend && npm test` | **22 passed** in 2 files (`App.test.tsx`, `Cart.test.tsx`) |

Added in M0 so later milestones can prove nothing moved (not part of the 153):

- `backend/tests/test_calculate_snapshot.py` + `fixtures/calculate_snapshot.json`: 3,311
  `/api/calculate` requests (every item at quantities around every breakpoint, add-ons,
  invoice billing, custom sizes in inches and cm, out-of-range sizes, manual quotes, error
  cases) with a SHA-256 of each baseline response. 2 tests, both pass at baseline.
- `backend/tests/bench_calculate.py`: the latency benchmark below.

## Frontend production bundle (`npm run build`, Vite 6)

| File | Raw | gzip |
|---|---|---|
| `index.html` | 0.81 kB | 0.43 kB |
| `assets/index-*.css` | 23.73 kB | 5.63 kB |
| `assets/index-*.js` (single chunk) | 255.38 kB | **79.16 kB** |

## `/api/calculate` latency

`cd backend && python -m tests.bench_calculate 200`: in-process (FastAPI TestClient), 200
requests cycling through standard, below-minimum, custom box, custom bag, add-on, sample,
outdoor and multi-add-on requests after a warm-up. Three runs:

| Run | p50 | p95 | max |
|---|---|---|---|
| 1 | 2.52 ms | 3.49 ms | 28.08 ms |
| 2 | 2.46 ms | 3.17 ms | 26.48 ms |
| 3 | 2.44 ms | 3.23 ms | 26.58 ms |

Baseline p95: **about 3.2–3.5 ms** (target in BRD section 8: under 50 ms).

## Typecheck and lint

| Check | Result |
|---|---|
| `tsc -b` (frontend, `strict`, `noUnusedLocals`, `noUnusedParameters`) | **0 errors** |
| ESLint | Not configured in the repo (no config, not a dependency) |
| Python lint (ruff/flake8) | Not configured in the repo |

R5 therefore applies to `tsc` only; adding a linter would be a new dependency (ask first, FR-C6).

## Console errors per screen

Local dev servers (`uvicorn app.main:app`, `vite`), no site password, staff passcode set, Chromium
via Playwright. Walked: calculator (quoted 450 boxes, ₹39,825.00), Add to cart, Cart (with the
Ship To / invoice form), Invoices (after the staff passcode dialog), Add custom item dialog.

| Screen | Console errors | Warnings |
|---|---|---|
| Calculator | 0 | 0 |
| Cart + checkout form | 0 | 0 |
| Invoices | 0 | 0 |
| Custom item dialog | 0 | 0 |

The URL stayed `/` on every screen: this is the Back-button problem in BRD section 1.

## Screen inventory (M0)

| Screen / overlay | Kind today | Reached from |
|---|---|---|
| Password page | Full screen; the app already sets `/login` with `history.replaceState` | Any visit while signed out |
| Calculator | Tab (kept mounted, hidden when another tab shows) | "Calculator" tab; "Go to calculator" on the empty cart |
| Cart, including the checkout form (Ship To, Bill No, date, GST billing type, saving, Print Unpaid / Print Paid) | Tab | "Cart" tab; "View cart" toast action after Add to cart |
| Invoices (list, search, re-download, record payment) | Tab, only when the server stores invoices | "Invoices" tab |
| Add custom item | Modal dialog (bottom sheet on phones) | Cart; "Add as custom item" on a manual quote |
| Print (Paid) payment dialog | Modal dialog | Cart |
| Record payment dialog | Modal dialog | Invoices |
| Staff passcode | Modal dialog | First print / Invoices visit |

There is no separate checkout screen: the checkout form is part of the cart. Existing back-type
buttons: "Go to calculator" (empty cart) and "View cart" (toast). No invoice preview overlay
exists; invoices download directly.
