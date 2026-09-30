# Printevr Pricing Calculator

Internal quoting tool. The spec is `docs/BRD-v2.1.pdf` (BRD v2.1); read the relevant section before changing behaviour.

## Rules
- Money is `Decimal` everywhere in the backend. Never float, never hardcoded prices.
- Business numbers (GST, surcharge, rounding step, add-ons, policies, yields) come from `config/products.yaml` or the sheet, never from code.
- Don't edit files in `data/`. Prices change only in the spreadsheet.
- Functions under `backend/app/pricing/` take plain data and return plain data: no file reads, no HTTP.
- The browser never receives tier prices; `/api/catalog` sends breakpoints only.
- Run `cd backend && python -m pytest` and `cd frontend && npm test` before calling a change done. All BRD section 11 tests must pass.

## Cart and invoices (`docs/BRD-cart-invoice.md`)
- Invoice positions, sizes and fonts live only in `backend/app/invoice/layout.py`; they were measured from `reference_bill18.pdf`. Don't change them without re-running the golden tests (`tests/test_invoice_golden.py`).
- Pill and payment-box coordinates are the **outer edge** of their 1.5 pt stroke (as measured on the reference); the renderer draws the path half a stroke inside.
- `layout.TRACKING` holds per-run letter spacing that makes the stock Montserrat TTFs line up with Canva's export. Don't remove it to "clean up": G3 fails without it.
- Business text for invoices lives in `config/invoice.yaml`, never in code.
- Money is `Decimal` in Python and never a float in TypeScript (`frontend/src/lib/invoiceMoney.ts` uses BigInt paise).
- Don't edit files in `backend/assets/invoice/` or `backend/tests/fixtures/invoice/`.
- Issued invoices are never re-priced; re-downloads render from the stored record.
- Run `pytest` and the frontend tests before saying a milestone is done.

## Known deviations from the BRD text
- **L1 item count is 233, not 284.** The sheet stores mailer-bag sizes as `6 × 8 in`, `6 × 8 in in`, `6 × 8 in in in`…, which would make every tier its own item. The loader collapses repeated unit words, which is also what makes L4's count of 11 come out right.
- Item ids keep decimal points (`rigid_boxes/3.5x5.5x4-in/top-bottom`) rather than turning them into hyphens.
- The API starts even if the sheet fails to load: `/api/health` shows the reason and pricing routes return `DATA_NOT_LOADED` (503) until a fixed sheet is reloaded.
- Cart/invoice BRD deviations:
  - The standard-size spec uses the product's `size_label` (Paper, Width, Material...) for products whose "size" column isn't a size (`custom_dims: none`); dimensioned products say `Size`.
  - `CalculateRequest` gained an optional `outdoor: {width, height, pieces}` so outdoor lines can print `6*5 ft, 2 pcs`; the server otherwise only sees square feet.
  - Drafts for per-order add-on lines carry `addon_id`, used to check them against the parent's fresh quote.
  - Cart line quantities may have 2 decimals (square feet); other units are whole.
  - `invoices` has an extra `business_name` column for search.
  - `GET /api/invoices/next-bill-no` also returns `gst_options` and `advance_pct` for the cart's summary box.
  - **Selectable GST** (replaces D4's single 18%): With GST billing requires `gst_option`, a key from `gst_options` in `config/invoice.yaml` (400 `INVALID_GST_OPTION` if missing or unknown). Each component is rounded to paise on its own and printed as its own row (`CGST @ 9%:`); the chosen option and its rows are stored in `invoices.gst` (JSON, added on startup if missing). Saved With GST invoices without it reprint at 18%.
  - The staff token check (401) and `INVOICING_DISABLED` (503) run in middleware, before body validation.
  - Invoicing is also disabled (503) when `SECRET_KEY` is missing.
  - **No-storage mode** (not in the BRD; production used it until 2026-10-01, when a Neon Postgres was added as `DATABASE_URL` and the Invoices tab came back): without `DATABASE_URL`, `POST /api/invoices` renders and returns the PDF without saving it, and `bill_no` is required. Routes that read stored invoices answer `503 STORAGE_DISABLED`. `GET /api/invoice-settings` (no staff token) tells the UI, which then requires the Bill No and hides the Invoices tab.
  - Bill No is only pre-filled once staff are signed in (the endpoint needs the token); blank means "assign the next one on print".
