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
- The quotation and GST invoice have their own layout files, measured from `docs/templates/quotation.pdf` and `docs/templates/gst_invoice.pdf`: `layout_quote.py` (+ `render_quote.py`) and `layout_gst.py` (+ `render_gst.py`). Their images are in `backend/assets/quotation/` (the band with a blank pill). The quotation carries no payment details: the template's UPI block (QR and text), the footer's two payment notes (100% advance, late payment) and its GST note are left off.
- **No payment details on printed invoices either** (owner's decision, 2026-10-03): `config/invoice.yaml` `print_payment_details: false`. The Non-GST invoice prints no payment-terms box and no advance/late-payment notes (TOTAL, the SUB TOTAL pill, the saving block and the GST note stay); the GST invoice prints no Payment Terms field, no bank details and `terms_lines_without_payment`. Print (Unpaid) and Print (Paid) therefore give the same page. Payments are still recorded, stored, shown on the Invoices page and emailed. `/api/invoice-settings` sends the flag and the cart hides the split-payment and GST Payment Terms inputs. The golden tests run with the flag on (`invoice_helpers.full_cfg`) so the reference layout stays locked; `tests/test_invoice_no_payment.py` covers the default.
- Pill and payment-box coordinates are the **outer edge** of their 1.5 pt stroke (as measured on the reference); the renderer draws the path half a stroke inside.
- `layout.TRACKING` holds per-run letter spacing that makes the stock Montserrat TTFs line up with Canva's export. Don't remove it to "clean up": G3 fails without it.
- Business text for invoices lives in `config/invoice.yaml`, never in code.
- Money is `Decimal` in Python and never a float in TypeScript (`frontend/src/lib/invoiceMoney.ts` uses BigInt paise).
- Don't edit files in `backend/assets/invoice/` or `backend/tests/fixtures/invoice/`.
- Issued invoices are never re-priced; re-downloads render from the stored record.
- Run `pytest` and the frontend tests before saying a milestone is done.

## Known deviations from the BRD text
- **L1 item count is 233, not 284.** The sheet stores mailer-bag sizes as `6 × 8 in`, `6 × 8 in in`, `6 × 8 in in in`…, which would make every tier its own item. The loader collapses repeated unit words, which is also what makes L4's count of 11 come out right.
- **Catalogue changes of 2026-10-03** (`config/products.yaml`, `tests/test_catalogue_changes.py`):
  - `active: false` withdraws a product (Customised Paper Printing): left out of `/api/catalog`, `/api/calculate` answers 422 `PRODUCT_WITHDRAWN`, so a new invoice line for it fails with `LINE_NOT_PRICEABLE`. Issued invoices still reprint from their stored lines. A withdrawn product may be deleted from the sheet without the loader refusing it.
  - `min_qty` raises a product's minimum above the sheet's first tier: that tier starts at `min_qty` at the same price (the mailer bags' "200 pcs" tier, 200-499, becomes "300 pcs", 300-499). With `below_min_policy: block` smaller orders get 422 `BELOW_MIN`; `/api/catalog` sends `below_min_policy` so the calculator refuses them inline too.
  - `test_calculate_snapshot.py` skips the four changed products (`CHANGED_PRODUCTS`); everything else must still answer as recorded.
- Item ids keep decimal points (`rigid_boxes/3.5x5.5x4-in/top-bottom`) rather than turning them into hyphens.
- The API starts even if the sheet fails to load: `/api/health` shows the reason and pricing routes return `DATA_NOT_LOADED` (503) until a fixed sheet is reloaded.
- Cart/invoice BRD deviations:
  - The standard-size spec uses the product's `size_label` (Paper, Width, Material...) for products whose "size" column isn't a size (`custom_dims: none`); dimensioned products say `Size`.
  - `CalculateRequest` gained an optional `outdoor: {width, height, pieces}` so outdoor lines can print `6*5 ft, 2 pcs`; the server otherwise only sees square feet.
  - Drafts for per-order add-on lines carry `addon_id`, used to check them against the parent's fresh quote.
  - Cart line quantities may have 2 decimals (square feet); other units are whole.
  - `invoices` has an extra `business_name` column for search.
  - `GET /api/invoices/next-bill-no` returns every series' next number (`next`), plus `gst_slab_groups` and `advance_pct` for the cart's summary box.
  - **Three documents** (not in the BRD): `POST /api/invoices` takes `document_type` (`quotation` | `invoice`) and, for invoices, `bill_type` (`non_gst` = the Printevr invoice, `gst` = the BASTTA GST invoice). A quotation needs only lines (Ship To optional) and has no `print_mode` or payments. Each document is numbered in its own series and table: `invoices` (Non-GST; continues the old numbers and holds every invoice saved before), `gst_invoices` (from `gst_invoice.bill_no_start`), `quotations` (from `quotation.quote_no_start`). Read routes take `?series=quotation|non_gst|gst` (default `non_gst`); PDFs carry `X-Document-Series`. Quotations aren't emailed.
  - **GST slabs** (replace the four "With GST billing" options): a GST invoice requires `gst_slab`, one of six keys in `config/invoice.yaml` `gst_slabs` (grouped intra/inter-state for the dropdown); a missing/unknown slab, or a slab on a quotation or Non-GST invoice, is 400 `INVALID_GST_SLAB`. Every slab has CGST, UGST and IGST (non-applicable ones 0%), each rounded half up to paise on its own, stored in the row's `gst` JSON with the GST form fields in `gst_invoices.details`. The old keys are `legacy_gst_options`, for reading old records only: old With GST invoices still reprint from their stored rows (and at 18% if they have none).
  - **HSN codes**: `hsn_code` per product in `config/products.yaml` (all blank; never guess one) pre-fills each cart line's HSN on a GST invoice; `/api/invoice-settings` sends them as `hsn_codes`. A blank HSN prints blank and only warns in the cart.
  - The Non-GST invoice keeps the golden-tested layout of `reference_bill18.pdf` (payment-terms box, now printed only with `print_payment_details`; PRICE PER PCS), not the Jairpur sample's (UPI block, market/discounted columns): G2/G3 lock it. The one change: an article and its add-on rows share a block (no rule between them), as on the sample.
  - The staff token check (401) and `INVOICING_DISABLED` (503) run in middleware, before body validation.
  - Invoicing is also disabled (503) when `SECRET_KEY` is missing.
  - **No-storage mode** (not in the BRD; production used it until 2026-10-01, when a Neon Postgres was added as `DATABASE_URL` and the Invoices tab came back): without `DATABASE_URL`, `POST /api/invoices` renders and returns the PDF without saving it, and `bill_no` is required. Routes that read stored invoices answer `503 STORAGE_DISABLED`. `GET /api/invoice-settings` (no staff token) tells the UI, which then requires the Bill No and hides the Invoices tab.
  - `DELETE /api/invoices/{bill_no}` (not in the BRD) removes an invoice for everyone; the Invoices page asks first. Its events go too (owner's choice: a deleted invoice leaves nothing in the database). Numbers are never handed out again: `document_counters` keeps each series' highest issued number, even after a delete.
  - **Invoice emails** (not in the BRD): with `SMTP_PASSWORD` set, every new invoice, Non-GST or GST (saved or not), and every recorded payment is emailed with its PDF to `email.to` in `config/invoice.yaml` (`app/invoice/mailer.py`, Gmail SMTP); quotations are not. Sending is best effort: failures are logged, never returned.
  - **Pay in full by default** (replaces the fixed 80/20 for new invoices): `POST /api/invoices` takes an optional `advance_pct`; without it the invoice asks for 100% before printing and the payment terms print no "20% ... before dispatch" line. Staff tick "Split payment" in the cart to choose a percent (it starts at config `advance_pct`, 80). Stored per document (`advance_pct` column, added on startup); old invoices have none and keep reprinting with the config's 80/20.
  - **Custom invoice** (2026-10-03): `POST /api/invoices` takes `is_custom`; the cart's "Custom invoice" tick puts a rate field on every line ("Calculated: …", "Reset to calculated price"). Everything else is the normal flow: catalogue lines are still re-priced and checked (`PRICES_CHANGED`, minimums, withdrawn products) and the invoice takes the next number in its series. Each line stores `catalogue_unit_price` (calculated) and `unit_price` (billed) with `price_edited`; the row stores `is_custom` (column added on startup), shown only as a "Custom" tag on the Invoices page. A rate may be 0 on a custom invoice only. The PDF is the same as a regular invoice's (no label, no calculated price; ticking it drops a catalogue price from the middle column). `tests/test_custom_invoice.py`.
  - **No salesperson**: the name is no longer asked for, printed or emailed. `invoices.salesperson` keeps the names already saved (never printed, even on reprints).
  - Bill No is only pre-filled once staff are signed in (the endpoint needs the token); blank means "assign the next one on print".
  - `create()` takes a Postgres advisory lock per series (`Store.lock_series`), so separate server instances number one at a time. Before this, two instances printing at the same moment could pick the same number and answer 500.

## Designer Assignment (not in any BRD; README "Designer Assignment")
- Every Non-GST and GST invoice gets exactly one design job (`design_jobs`, unique `(series, bill_no)`), made in the invoice's own transaction by `designers.service.ensure_job`. Quotations get none. Re-downloads and payments return the existing job. Deleting an invoice deletes its job (the rotation doesn't move back).
- The rotation is decided only on the server, under `SELECT ... FOR UPDATE` on the one-row `rotation_state`. Never pick a designer anywhere else: not in the frontend, not without the lock.
- On Postgres the designer tables come only from `backend/migrations/*.sql` (`backend/scripts/migrate.py`). Never `create_all` them there. `app/designers/models.py` mirrors them for SQLite and must match (`tests/test_designer_migrations.py`). For schema changes add a new numbered file; never edit an applied one.
- `PENDING_STATUSES` and the stage labels exist once in `app/designers/models.py` and once in `frontend/src/lib/designers.ts`; a test keeps them equal.
- Times are `timestamptz` from the database clock (`clock_timestamp()`), shown in IST by `frontend/src/lib/designers.ts`.
- The designer's name goes out in response headers only (`X-Designer`), never on a PDF.
- The lock and migration tests need `TEST_DATABASE_URL` (a throwaway Postgres). Without it they are skipped.
