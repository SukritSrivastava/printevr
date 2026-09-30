# Printevr Quote Desk

Internal quoting tool for Printevr ops and sales staff. Pick a catalogue item (or a custom size), enter a quantity, and get an itemised quote with the matched volume tier, unit price, add-ons, 18% GST and production time. Built to `docs/BRD-v2.1.pdf`.

- **Backend:** FastAPI (Python 3.12+). Reads `data/Printevr_Pricing_Master_2025-26.xlsx` and `config/products.yaml` at startup and does all pricing.
- **Frontend:** React 18 + TypeScript + Vite + Tailwind + TanStack Query. Only shows results.

## Run it

### With Docker

```sh
cp .env.example .env        # set ADMIN_TOKEN if you want sheet reloads
docker compose up --build
```

Open http://localhost:8080. The API is also on http://localhost:8000.

### Without Docker

```sh
# Terminal 1: API on :8000
cd backend
pip install -r requirements-dev.txt
python -m uvicorn app.main:app --port 8000

# Terminal 2: UI on :5173 (proxies /api to :8000)
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. On a phone on the same Wi-Fi, run `npm run dev -- --host` and open the printed network address.

### On Vercel

Import the GitHub repo in Vercel and deploy; `vercel.json` has all the settings, so leave the root directory and framework preset as they are. The UI is served as static files and `api/index.py` runs the FastAPI app as a Python function on the same domain, so `CORS_ORIGIN` and `VITE_API_URL` aren't needed.

The sheet and config are bundled into each deployment, so to change prices, commit the updated workbook or `config/products.yaml` and push: Vercel redeploys on its own. `/api/admin/reload` does nothing useful there.

`api/requirements.txt` is what Vercel installs. Keep it the same as `backend/requirements.txt`.

If the API can't start on Vercel, every `/api/*` call answers `503 STARTUP_FAILED` with the exception, and the full traceback is in the function logs. Open `/api/health` to see it.

## Password

The site asks for a password before anything else loads (`/login`), then opens the quote desk. The check is server-side: without the signed session cookie from `POST /api/login`, every pricing endpoint answers `401`. Only `/api/health` and the sign-in routes are open. Wrong guesses are limited to 10 a minute per IP.

The password lives in the `SITE_PASSWORD` environment variable, never in the code (this repo is public). To change it on Vercel:

```sh
npx vercel env rm SITE_PASSWORD production
npx vercel env add SITE_PASSWORD production   # type the new one
```

Then redeploy. Changing the password signs everyone out.

## Cart and invoices

Staff can add priced articles (and hand-typed custom items) to a cart, fill in Ship To, and download one invoice PDF in Printevr's own format: **Print (Unpaid as of now)** or **Print (Paid)**. The **Invoices** tab lists issued invoices, re-downloads them and records payments under the same bill number. Spec: `docs/BRD-cart-invoice.md`.

- The server re-prices every calculator line before printing; a changed price answers `409 PRICES_CHANGED` and nothing is saved. A price edited in the cart is allowed and recorded (`price_edited`).
- Bill numbers start at 19 (`config/invoice.yaml` → `bill_no_start`) and are never reused.
- PDFs are drawn with ReportLab from `backend/app/invoice/layout.py` (every coordinate) and `config/invoice.yaml` (every word). Fonts: Montserrat (SIL OFL) in `backend/assets/fonts/`.
- Everything under `/api/invoices` needs the **staff passcode**, asked once per browser tab. The calculator stays open as before.

### Turning invoicing on

| Variable | Needed | Meaning |
|---|---|---|
| `STAFF_PASSCODE` | yes | The staff passcode. Unset = invoicing off (`503 INVOICING_DISABLED`) |
| `SECRET_KEY` | yes, with a passcode | Signs staff tokens (12 hours). Any long random string |
| `DATABASE_URL` | optional | Where invoices are kept. Default `sqlite:///./var/invoices.db` (repo root); on Vercel, a Neon Postgres |

**With or without storage.** On a normal server or with `docker compose`, invoices are stored in SQLite (`var/` is a volume): bill numbers are assigned by the server and the **Invoices** tab lists them and records payments.

**On Vercel** (local disk is wiped between requests) there is no default database. Without `DATABASE_URL`, invoices are **rendered and downloaded but not stored**. The cart's Bill No field is then required (it counts up by one after each print on that device), the Invoices tab is hidden, and a later payment is recorded by printing again with **Print (Paid)** and the same Bill No. Prices are still re-checked on the server and the staff passcode is still required. This site stores them: production's `DATABASE_URL` points at a free Neon Postgres (Vercel Marketplace, `iad1`), so the Invoices tab shows there. Any hosted Postgres works, e.g. `postgresql://user:pass@host/db?sslmode=require`; tables are created on first use.

```sh
npx vercel env add STAFF_PASSCODE production
npx vercel env add SECRET_KEY production
```

## Tests

```sh
cd backend && python -m pytest     # 149 tests: BRD section 11, all sheet prices, invoice golden PDF (G1-G5), money (P1-P8), drafts (K1-K6), API (A1-A11)
cd frontend && npm test            # calculator on screen, plus cart and printing U1-U7 and the Invoices page
```

The golden tests compare the rendered Sogat Jutti invoice with `backend/tests/fixtures/invoice/reference_bill18.pdf`; on a raster mismatch they save an overlay PNG to `backend/tests/output/`.

## Changing prices and settings

| To change | Edit | Then |
|---|---|---|
| A price | The product tab in the workbook (Master prices are formulas). Save it in Excel, Google Sheets or LibreOffice so the values are recalculated. | Reload |
| A flag's status | `Review Flags` → `Status` (anything other than `Open` clears the warning) | Reload |
| GST, surcharge, rounding, add-ons, yields, policies | `config/products.yaml` | Reload |
| Invoice titles and unit labels per product | `config/products.yaml` → `invoice_title`, `invoice_unit_label` | Reload |
| Invoice wording, From address, footer, GST rates on invoices (`gst_options`), 80/20 split, first bill number | `config/invoice.yaml` | Restart |

**Reload** without a restart:

```sh
curl -X POST http://localhost:8000/api/admin/reload -H "X-Admin-Token: $ADMIN_TOKEN"
```

A reload that fails (a blank price, a duplicated tier, a product missing from config...) keeps serving the last good data, and the error names the row. Reloads are disabled when `ADMIN_TOKEN` isn't set.

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_TOKEN` | *(unset)* | Required header value for `/api/admin/reload` |
| `CORS_ORIGIN` | `http://localhost:5173` | Frontend origin(s), comma-separated |
| `RATE_LIMIT_PER_MINUTE` | `60` | `/api/calculate` calls per minute per IP |
| `SITE_PASSWORD` | *(unset)* | Password for the site. Unset locally means no password; on Vercel the API refuses to run without it |
| `SESSION_SECRET` | *(unset)* | Optional extra secret for signing the session cookie |
| `SESSION_DAYS` | `7` | How long a sign-in lasts |
| `TRUST_PROXY_HEADERS` | `1` on Vercel, else `0` | Rate-limit by the forwarded client IP (`X-Real-IP` / `X-Forwarded-For`) instead of the proxy's |
| `DATA_FILE`, `CONFIG_FILE` | `data/…xlsx`, `config/products.yaml` | Override file locations |
| `VITE_API_URL` (frontend build) | *(same origin)* | API base URL when the UI and API are on different hosts |

## Open data issues

All 27 Review Flags are still `Open`, so quotes on those prices carry an amber "price under review" warning. The BRD lists F1–F11 as "fix before coding"; the tool works around them for now:

- **F7:** the second 8 × 8 × 1.5 monocarton row is kept as its own item. Custom sizes use the higher price when two sizes tie.
- **F8:** 10 × 7 × 3 appears in both Small and Medium carry bags. Both are quotable; custom sizes use the higher price.
- **F9 / F10:** the page-15 products show as "Untitled cards (pg 15)" with "Confirm production time".
- **F11:** page-17 and page-18 monocartons are interpolated together until they are labelled as different builds.

The sheet also stores mailer-bag sizes with repeated units (`6 × 8 in in in`). The loader cleans these up, but it's worth fixing in the sheet too.
