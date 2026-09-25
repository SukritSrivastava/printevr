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

## Tests

```sh
cd backend && python -m pytest     # 85 tests: every BRD section 11 case, all 950 sheet prices, every API error code
cd frontend && npm test            # T1, T5 and C1 on screen, debounce, retry, copy text
```

## Changing prices and settings

| To change | Edit | Then |
|---|---|---|
| A price | The product tab in the workbook (Master prices are formulas). Save it in Excel, Google Sheets or LibreOffice so the values are recalculated. | Reload |
| A flag's status | `Review Flags` → `Status` (anything other than `Open` clears the warning) | Reload |
| GST, surcharge, rounding, add-ons, yields, policies | `config/products.yaml` | Reload |

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
