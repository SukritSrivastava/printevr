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

If the API can't start on Vercel, every `/api/*` call answers `503 STARTUP_FAILED` with only an error id (`/api/health` answers `{"status": "error"}`); the exception and full traceback are in the function logs under that id. Sending the `X-Admin-Token` header (the `ADMIN_TOKEN` value) also returns the exception and the end of the traceback:

```sh
curl https://<your-site>/api/admin/status -H "X-Admin-Token: $ADMIN_TOKEN"
```

## Health, errors and the operator status page

- `GET /api/health` is public and answers only `{"status": "ok"}` or `{"status": "error"}` (price data loaded or not), always with HTTP 200 while the API runs. Uptime checks and the Docker healthcheck use it.
- `GET /api/admin/status` needs `X-Admin-Token` and shows what `/api/health` used to: load time, source file, the loader error, counts, plus why invoicing is off, whether the database schema is ready (and which migrations are pending), and where login limits are counted. Without `ADMIN_TOKEN` it answers 403.
- No response carries exception text, tracebacks, file paths or environment variable names. An unexpected failure answers `500 INTERNAL_ERROR`, and a database failure on the invoice or designer routes answers `503 STORAGE_UNAVAILABLE`. Both include `details.error_id`, which is also in the message as "(ref …)" and in the server log next to the full traceback. When staff report the ref, search the log for `error_id=<ref>`.
- `DATA_NOT_LOADED` no longer carries `details.reason`; the reason is in the log and on the status page. `INVOICING_DISABLED` and `AUTH_NOT_CONFIGURED` no longer name the missing variable; the startup log and the status page do.
- Signed-in staff still get actionable messages: `STORAGE_NOT_READY` (503) means the database needs its migrations ("Ask the operator to run the database migrations"), and `DESIGNERS_NOT_SET_UP` is unchanged.

## Password

The site asks for a password before anything else loads (`/login`), then opens the quote desk. The check is server-side: without the signed session cookie from `POST /api/login`, every pricing endpoint answers `401`. Only `/api/health` and the sign-in routes are open (`/api/admin/*` has its own token). Wrong guesses are limited to 10 a minute per client IP (the staff passcode to 5); see [Rate limits](#rate-limits).

**Sign out** also clears the customer details saved in this browser and the staff token (see [Browser storage](#browser-storage)).

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
- **Non-GST invoices** print in the Printevr template; **GST invoices** keep the BASTTA layout. Under the items, every Non-GST invoice prints a **PAYMENT TERMS** box (total, advance %, and the balance before dispatch when the payment is split) and, once a payment is recorded, a **RECIEVABLES** box listing each payment (date, amount, mode) and the amount still pending (total minus everything received). It's filled in from the invoice; the wording is in `config/invoice.yaml` → `payment_summary`.
- Everything under `/api/invoices` needs the **staff passcode**, asked once per browser tab. The calculator stays open as before.

### Browser storage

The cart is saved in `localStorage` (`printevr.cart.v2`) so it survives a reload. The retention policy (`frontend/src/cart/storage.ts`):

| What | Kept |
|---|---|
| Cart lines (articles, specs, quantities, prices) and the cart's own settings (document type, Bill/Quote No, date, GST slab, saving, payment split) | Until **Clear cart**, as before; also across Sign out and expiry. They describe the order, not the customer, and prices are re-checked on the server anyway |
| Customer details: Ship To / buyer name, contact person, address, phone, buyer and consignee GSTINs, consignee details, and the GST invoice's order and transport fields (delivery and payment terms, PO date, GR/RR, transport, vehicle, e-way bill, station) | **12 hours after the checkout form last changed** (opening the page or re-pricing the lines doesn't restart it), then cleared, also in a page left open. Cleared at once on **Sign out** |
| Site session | Never in browser storage: an `httpOnly` cookie |
| Staff token | `sessionStorage` (this tab only), removed on Sign out |

A cart saved by an older version (`printevr.cart.v1`) is read once: its lines are kept, its customer details are dropped (their age is unknown), and the old key is deleted. Storage that is blocked, full, corrupt, from an unknown version or holding wrongly typed fields never breaks the page: the bad parts are ignored and a console warning is logged.

### Turning invoicing on

| Variable | Needed | Meaning |
|---|---|---|
| `STAFF_PASSCODE` | yes | The staff passcode. Unset = invoicing off (`503 INVOICING_DISABLED`) |
| `SECRET_KEY` | yes, with a passcode | Signs staff tokens (12 hours). Any long random string |
| `DATABASE_URL` | optional | Where invoices are kept. Default `sqlite:///./var/invoices.db` (repo root); on Vercel, a Neon Postgres |
| `SMTP_PASSWORD` | optional | Gmail app password. Set = every new invoice and recorded payment is emailed with its PDF to `email.to` in `config/invoice.yaml`. A failed email never stops an invoice |
| `SMTP_USER` | optional | The Gmail account that sends. Default: the `email.to` address |

**With or without storage.** On a normal server or with `docker compose`, invoices are stored in SQLite (`var/` is a volume): bill numbers are assigned by the server and the **Invoices** tab lists them and records payments.

**On Vercel** (local disk is wiped between requests) there is no default database. Without `DATABASE_URL`, invoices are **rendered and downloaded but not stored**. The cart's Bill No field is then required (it counts up by one after each print on that device), the Invoices tab is hidden, and a later payment is recorded by printing again with **Print (Paid)** and the same Bill No. Prices are still re-checked on the server and the staff passcode is still required. This site stores them: production's `DATABASE_URL` points at a free Neon Postgres (Vercel Marketplace, `iad1`), so the Invoices tab shows there. Any hosted Postgres works, e.g. `postgresql://user:pass@host/db?sslmode=require`. On Postgres the tables come from the [migrations](#database-migrations), applied before deploying; SQLite applies them on start.

```sh
npx vercel env add STAFF_PASSCODE production
npx vercel env add SECRET_KEY production
```

## Designer Assignment

Every **Non-GST or GST invoice** printed in the portal becomes a **design job**, assigned automatically to the next designer in turn (Namit → Ajendra → Namit → …). Quotations don't make jobs. The **Designer Assignment** tab is shown wherever invoices are stored, behind the same staff passcode. It has:

- **Jobs board**: every job, newest first. It shows invoice #, customer, designer, when it was assigned, a progress dropdown, vendor name and last update. Filters: designer, status, **Pending only** (on by default) and search by customer or invoice number. "Next job goes to" shows at the top.
- **Designer workload**: one card per designer: pending jobs, count per stage, how long the oldest pending job has waited, and their jobs. Click a job (here or on the board) for its status history.
- **Manage designers**: add, rename, pause or resume. Paused designers are skipped by the rotation.

**Progress stages:** 1 Work assigned (new jobs) · 2 Sent to customer for approval · 3 Approval received · 4 Sent for sampling.
- Stages 1–3 count as **pending**. The definition is `PENDING_STATUSES` in `backend/app/designers/models.py` and `frontend/src/lib/designers.ts`; a test keeps the two equal.
- A dropdown change saves at once. If the save fails, the dropdown goes back and a message says so. Moving back to an earlier stage is allowed. Every change is logged with its time.
- The vendor field saves on Enter or when you leave it. It suggests names used before, and the server trims it and caps it at 80 characters.
- Times are stored in UTC and shown in IST ("3 Oct 2026, 4:35 PM · 2 hours ago").

After printing, the cart shows "Assigned to Namit · 3 Oct 2026, 4:35 PM". The designer is never printed on the invoice.

**Sync.** The database is the only copy. The open tab refetches every 10 seconds while it's visible and stops while the browser tab is hidden. It refetches at once when you come back and after your own changes. If two people edit the same job, the last save wins.

### How the rotation works

- **Tables:** `designers` (name, active, `rotation_order`) and a one-row `rotation_state`. Its `last_order` is the `rotation_order` of whoever got the last job; `seq` counts the jobs assigned so far.
- **Printing** an invoice (`POST /api/invoices`) creates its job **in the same database transaction as the invoice**:
  1. If the invoice (series + bill number) already has a job, that job is returned and the rotation doesn't move. Re-downloads and **Record payment** (unpaid → paid on the same bill) never create jobs, and `design_jobs` has a unique key on `(series, bill_no)`.
  2. Otherwise `SELECT … FROM rotation_state FOR UPDATE` locks the pointer. The job goes to the first **active** designer whose `rotation_order` comes after `last_order`, wrapping round to the first. Simultaneous invoices queue on that lock, so nobody is skipped or picked twice.
  3. The job and its first history row are inserted, `assigned_at` is taken from the database clock (`clock_timestamp()`), and the pointer moves.
- **Nobody active:** the job is saved **unassigned** and the rotation doesn't move. A new designer joins at the end of the rotation.
- **Print (Paid) from the cart** issues a *new* bill number, so it is a new invoice and a new job. To mark the same invoice paid, use **Record payment** on the Invoices tab.
- **Deleting an invoice** deletes its job and history too. The rotation doesn't move back.
- **If the job step fails**, the invoice is still saved and printed (the job step runs in a savepoint) and the error is logged.
- **Bill numbers across instances:** on Postgres, printing also takes a per-series advisory lock (`pg_advisory_xact_lock`) for the length of the transaction. That stops separate Vercel instances from picking the same bill number at the same moment.

**API** (needs the staff token, like `/api/invoices`):
- `GET /api/designers`, `POST /api/designers`, `PATCH /api/designers/{id}` (`name`, `active`)
- `GET /api/jobs?designer=&status=&pending=&q=`, `PATCH /api/jobs/{id}` (`status` 1–4, `vendor_name`), `GET /api/jobs/{id}/history`
- `GET /api/workload`, `GET /api/rotation/next`, `GET /api/vendors?q=`

PDF responses carry `X-Job-Id`, `X-Designer` (percent-encoded) and `X-Assigned-At`.

### Database migrations

Every table comes from a versioned file in `backend/migrations/`, applied in order by `app/migrations.py` and recorded in `schema_migrations`:

| File | Database | What |
|---|---|---|
| `0001_designer_jobs.sql` | Postgres | Designer Assignment tables (SQLite builds them from `app/designers/models.py`) |
| `0002_seed_designers.sql` | Postgres | Namit and Ajendra |
| `0003_invoice_tables.py` | Postgres + SQLite | `invoices`, `gst_invoices`, `quotations`, `document_counters`, `invoice_events`. Creates what is missing and adds the nullable columns added since the first schema (`gst`, `salesperson`, `advance_pct`, `invoice_events.series`). It never drops, rewrites or backfills a row: issued invoices, payments, events, counters and design jobs stay as they are |
| `0004_rate_limits.py` | Postgres + SQLite | `rate_limit_counters`, for login limits shared by every instance |

- `.sql` files are Postgres-only; `.py` files define `upgrade(ctx)` with hand-written SQL for both dialects, so a migration never changes when the models do. `app/invoice/store.py` and `app/designers/models.py` must match them (`tests/test_invoice_migrations.py` and `tests/test_designer_migrations.py` compare them).
- Each file runs once, in its own transaction, together with its `schema_migrations` row, so a failing file leaves nothing half-done. The transaction first takes a lock (Postgres `pg_advisory_xact_lock`, SQLite `BEGIN IMMEDIATE`) and only then checks whether the file is still pending. Several processes or instances can therefore run the migrations at once: one applies each file, the others wait and skip it. The lock is transaction-scoped, so it works through Neon's pooler too.
- The app never changes the schema at runtime on Postgres. It checks the tables it needs when it first opens the database. If they're missing, invoice and designer routes answer `503 STORAGE_NOT_READY` and the calculator keeps working. If they're there but `0003` isn't recorded (a database built by the old runtime code), it works and logs a warning to run the migrations.
- **SQLite** (local, `docker compose`) applies pending migrations by itself when the API first opens the database, under the same lock, so `uvicorn --workers N` is safe. Your existing `var/invoices.db` is upgraded in place.
- To change the schema later, add `0005_….py` (or a Postgres-only `.sql`); never edit an applied file. Update the models to match.

**Deployment order (Postgres / Vercel):**

1. **Back up** (Neon: create a branch, or `pg_dump`).
2. **Apply the migrations** with the new code checked out, against the **unpooled** connection string (Neon console, or Vercel → Storage → your Neon database):
   ```sh
   pip install -r backend/requirements.txt
   DATABASE_URL_UNPOOLED='postgresql://…' python backend/scripts/migrate.py --status   # see what's pending
   DATABASE_URL_UNPOOLED='postgresql://…' python backend/scripts/migrate.py            # apply it
   ```
   In PowerShell: `$env:DATABASE_URL_UNPOOLED='postgresql://…'; python backend/scripts/migrate.py`. Running it again does nothing.
3. **Deploy** the app (push / merge; Vercel builds it). Every migration only adds tables and nullable columns, so the version still running keeps working while step 2 runs and until step 3 finishes.
4. **Check** `GET /api/admin/status` with `X-Admin-Token`: `storage.ready` should be `true` and `pending_migrations` empty.

With `docker compose` and Postgres: `docker compose run --rm api python scripts/migrate.py`, then `docker compose up -d`. With SQLite nothing extra is needed.

The app itself keeps using `DATABASE_URL`, which on Vercel should be the **pooled** Neon string (host with `-pooler`). The API turns off server-side prepared statements so it works through the pooler, and gives up connecting after 10 seconds (a `connect_timeout` in the URL overrides it) instead of libpq's default of minutes.

### Rate limits

| Limit | Where it is counted |
|---|---|
| Site password: 10 tries a minute per client | The database when `DATABASE_URL` is Postgres (`RATE_LIMIT_BACKEND=auto`), so all instances share it; otherwise in memory |
| Staff passcode: 5 tries a minute per client | Same as above |
| `/api/calculate`: `RATE_LIMIT_PER_MINUTE` per client | Always in memory, per instance: a database write per quote would cost more than the limit protects |

- **Shared** (`app/ratelimit.py`, table `rate_limit_counters`): uses the Neon Postgres the site already has, so there's no new service or cost. It is a sliding-window counter over the current and previous minute. Every attempt counts, including those refused while over the limit, so a client that keeps trying stays blocked until it stops for a minute. Client addresses are stored only as SHA-256 hashes, and rows older than a minute are deleted as it goes.
- **Fallback:** if the shared counter can't be used (migration 0004 not applied, database unreachable), each instance counts in memory and logs a warning at most every 5 minutes. On Vercel, a client could then get up to *limit × running instances* tries. `GET /api/admin/status` shows which backend is configured.
- **Memory is bounded:** each in-memory limiter sweeps out clients idle for a minute and keeps at most `RATE_LIMIT_MAX_KEYS` (10,000) clients, forgetting the least recently seen first.
- **Client IP:** forwarded headers are believed only with `TRUST_PROXY_HEADERS=1` (the default on Vercel, whose edge overwrites `X-Forwarded-For`) and, if `TRUSTED_PROXIES` is set, only from those peers. `X-Forwarded-For` is read from the right: with `TRUSTED_PROXY_HOPS=1` the last entry (the address the proxy saw) is the client, and anything the client wrote further left is ignored. `X-Real-IP` is used only when there is no `X-Forwarded-For`. `docker compose` sets this up for its nginx and publishes the API port on `127.0.0.1` only. Never turn it on where clients can reach the API directly.

## Tests

```sh
cd backend && python -m pytest     # BRD section 11, all sheet prices, invoice golden PDF (G1-G5), money (P1-P8), drafts (K1-K6), API (A1-A11), designer assignment
cd frontend && npm test            # calculator on screen, cart and printing U1-U7, the Invoices page, the Designer Assignment tab
```

SQLite has no row locks, so the designer, migration and rate-limit tests can also run against real Postgres when `TEST_DATABASE_URL` is set. Use a local Postgres or a spare Neon branch, **never production**; each test works in its own throwaway schema. This adds the Postgres migration checks (new database, upgrades with existing invoices and design jobs, eight processes migrating at once), the shared login limits across instances and the "10 invoices at the same moment" test:

```sh
TEST_DATABASE_URL='postgresql://postgres@localhost:5432/postgres' python -m pytest tests/test_designer*.py tests/test_invoice_migrations.py tests/test_rate_limits.py
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
| `ADMIN_TOKEN` | *(unset)* | Required `X-Admin-Token` value for `/api/admin/reload` and `/api/admin/status` |
| `CORS_ORIGIN` | `http://localhost:5173` | Frontend origin(s), comma-separated |
| `RATE_LIMIT_PER_MINUTE` | `60` | `/api/calculate` calls per minute per IP |
| `RATE_LIMIT_BACKEND` | `auto` | Where login limits are counted: `auto` (the database when `DATABASE_URL` is Postgres), `database`, or `memory` ([Rate limits](#rate-limits)) |
| `RATE_LIMIT_MAX_KEYS` | `10000` | Most clients an in-memory limiter remembers |
| `SITE_PASSWORD` | *(unset)* | Password for the site. Unset locally means no password; on Vercel the API refuses to run without it |
| `SESSION_SECRET` | *(unset)* | Optional extra secret for signing the session cookie |
| `SESSION_DAYS` | `7` | How long a sign-in lasts |
| `TRUST_PROXY_HEADERS` | `1` on Vercel, else `0` | Rate-limit by the forwarded client IP (`X-Forwarded-For`, read from the right; `X-Real-IP` only without it) instead of the proxy's |
| `TRUSTED_PROXY_HOPS` | `1` | How many proxies append to `X-Forwarded-For` in front of the API |
| `TRUSTED_PROXIES` | *(unset)* | Comma-separated IPs/CIDRs: believe forwarded headers only from these peers |
| `DATABASE_URL_UNPOOLED` | *(unset)* | Only for `backend/scripts/migrate.py`: Neon's direct (unpooled) connection string. Not needed on Vercel |
| `TEST_DATABASE_URL` | *(unset)* | Only for tests: a throwaway Postgres for the lock, migration and shared rate-limit tests |
| `DATA_FILE`, `CONFIG_FILE` | `data/…xlsx`, `config/products.yaml` | Override file locations |
| `VITE_API_URL` (frontend build) | *(same origin)* | API base URL when the UI and API are on different hosts |

## Open data issues

All 27 Review Flags are still `Open`, so quotes on those prices carry an amber "price under review" warning. The BRD lists F1–F11 as "fix before coding"; the tool works around them for now:

- **F7:** the second 8 × 8 × 1.5 monocarton row is kept as its own item. Custom sizes use the higher price when two sizes tie.
- **F8:** 10 × 7 × 3 appears in both Small and Medium carry bags. Both are quotable; custom sizes use the higher price.
- **F9 / F10:** the page-15 products show as "Untitled cards (pg 15)" with "Confirm production time".
- **F11:** page-17 and page-18 monocartons are interpolated together until they are labelled as different builds.

The sheet also stores mailer-bag sizes with repeated units (`6 × 8 in in in`). The loader cleans these up, but it's worth fixing in the sheet too.

The full list of decisions waiting on the data owner (every flag, the HSN codes and the config assumptions), with the evidence for each, is in `docs/source-data-decisions.md`. None of them is guessed in code.
