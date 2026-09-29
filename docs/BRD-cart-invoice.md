# PRINTEVR Calculator — Cart and Invoice Download · BRD v1.0

Sep 29, 2026 · Owner: Sukrit Srivastava (build lead) · Business input: Ayushmaan (Operations Head) · Build tool: Claude Code, one session

---

## 0. Read this first (instructions for Claude Code)

This document adds a **cart** and a **downloadable invoice** to the existing PRINTEVR pricing calculator. Build all of it in this session, milestone by milestone, in the order given in section 12. Don't start a milestone until the previous one's tests pass.

**Survey the repo before writing code.** This BRD assumes the structure described in `docs/BRD.md` (Pricing Calculator BRD v2.1):

- FastAPI backend; pricing in `backend/app/pricing/` and `backend/app/quote.py`; `POST /api/calculate`, `GET /api/catalog`; money as `Decimal`, sent as strings.
- `config/products.yaml` with per-product settings (option labels, sale unit, custom-dimension type, add-ons).
- React 18 + TypeScript + Vite + Tailwind + TanStack Query frontend with a live `ReceiptCard`.

If the real code differs, map each requirement onto what exists and write the mapping in your M0 summary. **Don't restructure the calculator or change how it prices.** Every existing test must still pass at the end.

**Files supplied with this BRD** (the user unzips them at the repo root):

| Path | What it is |
| --- | --- |
| `docs/BRD-cart-invoice.md` | This document |
| `backend/assets/invoice/invoice_band.png` | The header band cut from Printevr's own invoice at 400 dpi: light-green band, green blob, the "INVOICE" pill and word, and the asterisk column. The Date and Bill No text has been removed. 3309 × 667 px. |
| `backend/assets/invoice/printevr_logo.png` | Printevr logo with transparency, extracted from the same invoice. 1521 × 527 px. |
| `backend/tests/fixtures/invoice/reference_bill18.pdf` | The real invoice (Bill No 18, Sogat Jutti Store). The generated PDF must match it. |
| `backend/tests/fixtures/invoice/sogat_jutti_bill18.json` | The input that must reproduce the reference, plus the expected numbers and text |
| `backend/tests/fixtures/invoice/layout_reference.json` | Every text run and shape on the reference, measured in points, with true baselines |

**Fonts.** The invoice uses **Montserrat Regular** and **Montserrat Bold**. Download the static TTF files (not the variable font) from the official Montserrat repository, `github.com/JulietaUla/Montserrat`, folder `fonts/ttf/`, together with its `OFL.txt`, into `backend/assets/fonts/`. Montserrat is under the SIL Open Font License, so committing it is allowed. Don't substitute another font. If the download fails, stop and ask the user to add `Montserrat-Regular.ttf` and `Montserrat-Bold.ttf` themselves. The word "INVOICE" uses a different font (Agrandir), but it is already drawn inside `invoice_band.png`, so no other font is needed.

**Session prompt the user will give you:**

> Read `docs/BRD-cart-invoice.md` completely, then `CLAUDE.md`. Build milestones M0 to M6 from section 12 in order, in this session. Run each milestone's tests before moving on. Don't change existing pricing behaviour. Ask me only if something blocks you.

---

## 1. Summary

Today the calculator prices one article at a time and nothing leaves the screen except a copied text quote. After this build, staff can:

1. Pick an article in the calculator (size, options, quantity) and press **Add to cart**.
2. Repeat for more articles, and add custom items the calculator can't price.
3. Enter the customer's Ship To details once.
4. Press **Print (Unpaid as of now)** or **Print (Paid)** and get one invoice PDF for the whole cart, downloaded straight from the website, in exactly Printevr's existing invoice format.
5. Later, find the invoice, record a payment, and download the updated invoice under the same bill number.

**Success criteria**

1. Rendering the Sogat Jutti fixture produces a PDF that matches `reference_bill18.pdf` (golden tests G1–G5, section 11).
2. The server re-prices every calculator line before printing. The invoice never uses a price the browser invented, except a visible, recorded manual price edit.
3. Bill numbers are sequential and never duplicated.
4. A phone user can go from the last "Add to cart" to a downloaded PDF in under a minute.

## 2. Scope

**In this build**

- Cart built from calculator quotes, with per-order add-ons as their own lines.
- Custom items typed by hand (for jobs the calculator can't price).
- Editing each line's invoice text: title, spec lines, customisations, unit label, middle-column note or reference price, and the unit price.
- Ship To form, bill number, invoice date, billing type (without or with GST), optional "saving" amount.
- Two print modes: Unpaid (as of now) and Paid.
- Invoice PDF in Printevr's format, generated on the server and downloaded in the browser.
- Invoices list with search, re-download, and "Record payment".
- Staff passcode protecting everything that creates or shows invoices.
- Invoices stored in a database.

**Not in this build**

- A customer address book or autocomplete.
- Editing or cancelling an issued invoice, other than adding payments.
- Sending invoices by e-mail or WhatsApp.
- CGST/SGST/IGST split, GSTIN and HSN fields, e-invoicing.
- Accounting export.
- User accounts and roles (one shared staff passcode only).

## 3. User flow

1. **Calculator.** The user picks category, product, size (or custom size), options, add-ons and quantity as today. The receipt shows the live price.
2. **Add to cart.** A new button on the receipt card adds the article. Per-order add-ons (e.g. butter paper multicolour ₹1,000) arrive as a separate linked line. If the calculator says "Needs a manual quote", the button becomes **Add as custom item**, which opens the custom-item form pre-filled with the title and specs; the user types the price.
3. **Cart.** A cart button in the header shows the line count. The cart lists every line with its invoice text, quantity, unit price and subtotal, and the running total. The user can reorder, remove, edit text, change quantity (re-priced live), edit a price, or add a custom item.
4. **Checkout.** Below the lines: Ship To (business name, contact person, address, phone), Bill No (pre-filled with the next number), invoice date (today, IST), billing type (Without GST, the default, or With GST), and an optional saving amount.
5. **Print (Unpaid as of now).** Downloads the invoice with no payment recorded.
6. **Print (Paid).** Opens a small dialog: amount received (defaults to the full payable amount; lower for an advance), date received (defaults to today), mode (UPI, cash, bank transfer, cheque; not printed). Several payments can be entered. Confirm downloads the invoice with the payments shown.
7. **After printing.** A success message names the bill number. The cart stays until the user presses **Clear cart**, so a reprint is one tap.
8. **Invoices page.** Lists recent invoices (bill no, date, customer, payable, received, status). Each row has **Download** and **Record payment**. Recording a payment downloads the updated invoice with the same bill number.

## 4. Cart requirements (FR-C)

### FR-C1 Invoice line drafts from the calculator (server)

The server builds the invoice text for a quoted article, so the rules live next to `products.yaml` and are tested with real prices.

1. Add a field `invoice_lines` to the success response of `POST /api/calculate`. This is additive; existing fields don't change. `invoice_lines[0]` is the main line; any further entries are per-order add-on lines.
2. Main line rules:
   - `title`: the product's new optional `invoice_title` from `products.yaml`; otherwise `"Customised {product name} printing"`, without doubling "Customised" if the product name already starts with it. In M3, fill `invoice_title` for all 27 products using the pattern "Customised … printing" (e.g. Rigid Boxes → "Customised rigid box printing") and list them in your summary for the user to check.
   - `specs`, in this order:
     - **Size** (`emphasis: true`). Standard size: the sheet's Size / Spec text with ×, x or X turned into `*`, spaces around `*` removed, the unit kept, plus a dimension-order hint from `custom_dims`: box `(LxWxH)`, bag `(HxLxS)`, flat `(LxW)`, none → no hint. Custom size: the entered numbers without trailing zeros and in the entered unit, e.g. `3.5*3.5*2 in (LxWxH)`. Outdoor (`area_sqft`): `{W}*{H} ft, {pieces} pcs`.
     - One line per chosen option: label from `option_labels`, value as chosen, e.g. `Box type` / `Top-Bottom`.
     - One line per per-unit add-on: label `Add-on`, value the add-on name.
   - `customisations`: empty.
   - `quantity`: the **billed** quantity (after the minimum-order rule).
   - `unit_label`: the product's new optional `invoice_unit_label`; otherwise the plural of `sale_unit` from `config/invoice.yaml` → `unit_plurals` (box → boxes, card → cards, roll → rolls, and so on).
   - `catalogue_unit_price` and `unit_price`: the unit price **plus all per-unit add-ons** (T9: ₹5 + ₹1 round edges = ₹6).
   - `middle`: `{ "kind": "none" }`.
   - `warnings`: copied from the quote, for display in the cart only.
3. Each per-order add-on (and a sample charge, if the quote includes one) becomes its own line: title `"{add-on name} (add-on)"`, one spec `{ label: "For", value: <main line title> }`, quantity 1, unit label `order`, unit price = the add-on price, `source: "addon"`.
4. The drafts' subtotals must add up to the quote's pre-GST subtotal exactly. Test K4 checks this.
5. `manual_quote` responses get no `invoice_lines`.

### FR-C2 Add to cart (frontend)

1. The receipt card gets **Add to cart** under the totals. It is disabled while a calculation is loading or failed.
2. Pressing it stores, for each draft in `invoice_lines`, a cart line with a new `id` (UUID). Catalogue lines also store `calc_request`, the exact request that produced the quote. Add-on lines store `parent_id` pointing at their catalogue line.
3. A toast confirms "Added to cart" with a **View cart** link. The calculator keeps its current selection.
4. On `manual_quote`, the button reads **Add as custom item** and opens the custom-item form (FR-C4) with the title and a Size spec pre-filled from the current selection and the price empty.

### FR-C3 Editing cart lines

Each cart line is a card showing the invoice text as it will print, with an **Edit** toggle. In edit mode:

1. **Title**: text, 80 characters max.
2. **Specs** and **Customisations**: two editable lists of `{ label, value, emphasis }`. Add, remove, reorder. Label may be blank (value prints alone). Max 12 specs and 8 customisations per line; label 60 and value 120 characters.
3. **Quantity** (catalogue lines): changing it updates `calc_request.quantity`, re-calls `/api/calculate` 250 ms after the last keystroke, and replaces billed quantity, catalogue price and warnings from the response. Custom and add-on lines: plain integer input.
4. **Unit label**: text, e.g. "boxes".
5. **Unit price**: shown read-only with an **Edit price** link. An edited price that differs from `catalogue_unit_price` shows the badge "Catalogue ₹75.00 · edited". A **Show catalogue price in the middle column** checkbox sets `middle` to `{ kind: "reference_price", amount: catalogue_unit_price }`, which prints like the "15 → 08" thank-you-card row on the sample.
6. **Middle column**: a choice of None, Note (text, 40 characters, e.g. "Without ribbon closing :-"), or Reference price (amount). Only one at a time.
7. Remove a line (removing a catalogue line also removes its add-on lines, after a confirm). Move up and down; the invoice prints lines in cart order.
8. Warnings from the quote (`CUSTOM_ESTIMATE`, `MOQ_APPLIED`, `PRICE_UNDER_REVIEW`) show on the card in amber. They never print on the invoice.

### FR-C4 Custom items

**Add custom item** (in the cart, and from a manual quote) opens a form with title, specs, customisations, quantity, unit label, unit price and middle column. All required except specs, customisations and middle. `source: "custom"`, `catalogue_unit_price: null`.

### FR-C5 Cart persistence

The cart lives in React state and is saved to `localStorage` under `printevr.cart.v1` after every change, together with the unsaved checkout form. If parsing fails on load, start empty and log a console warning. This is the team's own website, so browser storage is fine here.

### FR-C6 Re-pricing and stale prices

1. When the cart page opens, re-quote every catalogue line once (in parallel, max 4 at a time). If billed quantity or catalogue price changed, update the line, keep any edited price, and show the banner "Prices changed since these were added. Check before printing."
2. The server re-checks on print (FR-P7). The UI handles its `PRICES_CHANGED` answer the same way and doesn't download anything until the user presses Print again.

### Cart line shape (shared by frontend and API)

```json
{
  "id": "0b7e6c2a-…",
  "source": "catalogue",
  "parent_id": null,
  "calc_request": { "product_id": "rigid_boxes", "item_id": "rigid_boxes/3x3x2-in/top-bottom", "options": {}, "custom_dimensions": null, "quantity": 350, "addons": [], "billing_type": "gst" },
  "title": "Customised rigid box printing",
  "specs": [
    { "label": "Size", "value": "3*3*2 in (LxWxH)", "emphasis": true },
    { "label": "Box type", "value": "Top-Bottom", "emphasis": false }
  ],
  "customisations": [],
  "quantity": 350,
  "unit_label": "boxes",
  "middle": { "kind": "none" },
  "catalogue_unit_price": "75.00",
  "unit_price": "75.00",
  "warnings": []
}
```

`middle` is one of `{ "kind": "none" }`, `{ "kind": "note", "text": "…" }` or `{ "kind": "reference_price", "amount": "15" }`. The invoice always uses pre-GST unit prices, whatever `billing_type` the calculator request carried.

## 5. Checkout and printing (FR-P)

### FR-P1 Checkout form

Shown under the cart lines.

| Field | Rule |
| --- | --- |
| Business name | Required, 60 chars |
| Contact person | Optional, 60 chars |
| Address | Required, 140 chars |
| Phone | Required, 7–20 characters of digits, spaces, `+`, `-` |
| Bill No | Integer. Pre-filled from `GET /api/invoices/next-bill-no` when the cart page opens and after each print. Editable, e.g. to continue a paper series. |
| Invoice date | Date, default today in Asia/Kolkata |
| Billing type | Without GST billing (default) · With GST billing |
| Saving amount | Optional amount ≥ 0. A **Use suggested** link fills Σ (reference price − unit price) × quantity over lines whose middle column is a reference price above the unit price, rounded down to the nearest 100. Blank or 0 hides the saving block on the invoice. |

A summary box shows Total, GST (if With GST), Payable, and the 80% / 20% split, using the same rules as the PDF (section 6), computed in the browser for display only.

### FR-P2 The two print buttons

Two full-width buttons at the bottom, in this order:

1. **Print (Unpaid as of now)**
2. **Print (Paid)**

Both are disabled until the cart has at least one line, every line has a unit price above 0, and the form is valid. Helper text under them: "Downloads the invoice PDF."

### FR-P3 Print (Unpaid as of now)

Sends `print_mode: "unpaid"` with `payments: []`. The invoice shows the payment-terms lines for an unpaid invoice (section 6.4).

### FR-P4 Print (Paid)

Opens a dialog with one payment row pre-filled: amount = payable, date = today (IST), mode = UPI. **Add another payment** adds a row (max 4). The dialog shows "Received ₹X of ₹Y" and blocks confirm if the total received is 0 or above the payable amount. Confirm sends `print_mode: "paid"` and the payments. A full payment prints "PAID IN FULL"; a part payment (like the Sogat Jutti ₹30,000 advance) prints the pending amounts (section 6.4).

### FR-P5 Download

1. The API answers with the PDF itself (`application/pdf`). The browser turns the response into a Blob, creates an object URL, clicks a temporary `<a download>` with the file name from `Content-Disposition`, then revokes the URL.
2. File name: `Invoice_{bill_no}_{Business-Name}_{Unpaid|Part-paid|Paid}.pdf`, e.g. `Invoice_18_Sogat-Jutti-Store_Part-paid.pdf`. Keep only letters, digits and hyphens in the business part.
3. On iOS Safari the PDF may open in a new tab instead of saving; that's acceptable, and the user can share or save from there.
4. After success: toast "Invoice 18 downloaded", a **Clear cart** button, and the Bill No field refreshed to the next number.

### FR-P6 Invoices page and recording payments

1. A third view next to Calculator and Cart: **Invoices**. Use the app's router if it has one; otherwise a simple tab state.
2. Table: Bill No, date, business name, payable, received, status (Unpaid, Part-paid, Paid). Newest first, 25 per page, search by business name or bill number.
3. Row actions: **Download** (re-renders the stored invoice; identical content) and **Record payment** (same dialog as FR-P4, pre-filled with the remaining amount). Recording a payment updates the invoice and downloads the new version under the same bill number.
4. Paid invoices hide Record payment.

### FR-P7 Server checks on print

On `POST /api/invoices` the server:

1. Validates every field (limits above; at most 30 lines per invoice; quantity 1–10,000,000; unit price 0.01–10,000,000).
2. Re-runs the quote for every catalogue line from its `calc_request`. If billed quantity or catalogue unit price differ from what the client sent, it answers `409 PRICES_CHANGED` with the fresh values per line id and saves nothing. Add-on lines are checked against their parent's fresh quote.
3. Accepts a `unit_price` different from `catalogue_unit_price` as a manual edit and records `price_edited: true` on that line.
4. Refuses a catalogue line whose quote is now `manual_quote` with `422 LINE_NOT_PRICEABLE`.
5. Checks the print mode: `unpaid` needs no payments; `paid` needs at least one; total received must not exceed payable (`422 OVERPAID`).
6. Assigns or checks the bill number (section 8.3), computes the money (section 6), stores the invoice, renders the PDF and returns it.

### FR-P8 Staff access

Everything under `/api/invoices` needs a staff token. The calculator stays open as it is today.

1. `POST /api/staff/login` with `{ "passcode": "…" }` returns a signed token valid 12 hours. Compare the passcode in constant time. Limit to 5 attempts per minute per IP.
2. The frontend asks for the passcode the first time the user prints or opens Invoices, keeps the token in `sessionStorage`, and sends `Authorization: Bearer <token>`. On any 401 it asks again and retries once.
3. If `STAFF_PASSCODE` isn't set on the server, invoice endpoints answer `503 INVOICING_DISABLED` and the cart shows "Invoicing isn't set up on this server."

## 6. Money rules

All money is `Decimal`, never float. Round half-up to ₹0.01. Put these rules in pure functions (`backend/app/invoice/money.py`) with no I/O.

### 6.1 Totals

| Symbol | Rule |
| --- | --- |
| line subtotal | quantity × unit price |
| **T** total | Σ line subtotals |
| **G** GST | Without GST billing: 0. With GST billing: T × `gst_rate` (0.18 from `config/invoice.yaml`) |
| **P** payable | T + G |
| **A** advance | P × `advance_pct` / 100 (80%) |
| **B** balance | P − A (so A + B always equals P) |
| **R** received | Σ payment amounts |
| applied | min(R, A) |
| pending | A − applied |
| excess | max(R − A, 0) |
| balance due | B − excess |

### 6.2 Status

R = 0 → `unpaid`. 0 < R < P → `part_paid`. R = P → `paid`. R > P is refused (`OVERPAID`).

### 6.3 Number and date formats on the invoice

| What | Rule | Examples |
| --- | --- | --- |
| Amounts | Whole rupees: digits only, no separators. Otherwise two decimals. | 148000 · 88.50 |
| Price per pcs | Same, but a whole amount below 10 gets a leading zero (`pad_single_digit_unit_price: true`) | 08 · 140 · 5.50 |
| Quantity | Integer digits, no separators | 1000 |
| Invoice date | `{day} {MON} , {year}`: day without leading zero, three-letter month in capitals, then space, comma, space | 14 SEP , 2026 · 9 SEP , 2026 |
| Payment date | `{day} {Month} {year}` | 9 September 2026 |

The web UI keeps its existing `en-IN` currency format (₹1,48,000.00). Only the PDF uses the plain style above.

### 6.4 Payment-terms lines

The box title is `PAYMENT TERMS     (WITHOUT GST BILLING)` or `PAYMENT TERMS     (WITH GST BILLING)`, with five spaces, as on the sample. The lines come from templates in `config/invoice.yaml`; `**…**` marks bold text. Wording and spacing are copied from the sample on purpose, including the spelling "Recieved" (decision D3).

| # | Template | Shown when |
| --- | --- | --- |
| 1 | `**Total Amount:- Rs. {P}/-**` | Always |
| 2 | `**{advance_pct}% amount pending (before printing & after sample & final confirmation):-  {A}/-**` | Always |
| 3 | `Recieved Amount:- Rs. {amount}/- ({payment date})`, one line per payment in date order | R > 0 |
| 4 | `Amount Pending (out of {advance_pct}%) :- {A}/-  (-)  {applied}/-  =  **{pending}/-**` | R > 0 |
| 5a | `{balance_pct}% Amount:- Rs. {B}/- (Before Dispatching the Order)` | excess = 0 |
| 5b | `{balance_pct}% Amount:- Rs. {B}/-  (-)  {excess}/-  =  **{balance due}/-** (Before Dispatching the Order)` | excess > 0 |
| 6 | `**Payment Status:- PAID IN FULL**` | status `paid` |

So an unpaid invoice shows lines 1, 2 and 5a. The Sogat Jutti invoice shows 1, 2, 3, 4, 5a.

### 6.5 Worked examples (these are tests P1–P8)

| ID | Input | Expected |
| --- | --- | --- |
| P1 | Sogat Jutti fixture: T 148000, without GST, one payment 30000 on 9 Sep 2026 | P 148000, A 118400, B 29600, applied 30000, pending 88400; lines exactly as `expected.payment_lines` in the fixture; `part_paid` |
| P2 | Same lines, no payments | Lines 1, 2, 5a only; `unpaid` |
| P3 | One payment 148000 | Line 4 `… 118400/-  (-)  118400/-  =  0/-`; line 5b `… 29600/-  (-)  29600/-  =  0/- …`; line 6 present; `paid` |
| P4 | One payment 130000 | Line 4 pending 0; line 5b `20% Amount:- Rs. 29600/-  (-)  11600/-  =  18000/- (Before Dispatching the Order)`; `part_paid` |
| P5 | Payments 30000 (9 Sep) and 20000 (12 Sep) | Two "Recieved" lines; line 4 `118400/-  (-)  50000/-  =  68400/-` |
| P6 | Sogat Jutti lines, With GST billing, no payments | G 26640, P 174640, A 139712, B 34928; title `(WITH GST BILLING)`; totals block TOTAL 148000, GST (18%) 26640, SUB TOTAL 174640 |
| P7 | Payment 150000 on T 148000 | `422 OVERPAID`, nothing saved |
| P8 | One line 1 × 88.50 | T 88.50, A 70.80, B 17.70; line 1 `Total Amount:- Rs. 88.50/-` |

## 7. Invoice format specification

The PDF must look like `reference_bill18.pdf`. Every number here was measured from that file; `layout_reference.json` holds the full measurements. Put all constants in one module, `backend/app/invoice/layout.py`, and use nothing else for positions.

### 7.1 Page, units and drawing rules

1. Page size **595.5 × 842.25 pt** (Canva's A4). Use exactly this, not ReportLab's A4 constant.
2. In this section, coordinates are points from the **top-left** corner, y growing downward, and a text's y is its **baseline**. In ReportLab, `y_rl = 842.25 − y`.
3. Render with **ReportLab** on a canvas (`reportlab.pdfgen.canvas`), created with `invariant=1` so the same input always gives the same bytes. ReportLab is pure Python, so it runs in Docker and on serverless hosts alike, and the format is coordinate-exact. Don't use WeasyPrint or an HTML-to-PDF step.
4. Fonts: register `Montserrat` (Regular) and `Montserrat-Bold` from `backend/assets/fonts/`. Embed them (ReportLab's `TTFont` does this).
5. All text and lines are black `#000000`.
6. Pills are rounded rectangles with corner radius = half their height, white fill, black stroke 1.5 pt. The payment box is a plain rectangle with a 1.5 pt black stroke. Row separators are filled black bars 0.7 pt tall.
7. Images: draw with `mask="auto"` so the logo keeps its transparency.
8. PDF metadata: title `INVOICE {bill_no} - {BUSINESS NAME}`, author `PRINTEVR VENTURE`.

### 7.2 Fixed top of page 1

| Element | Content | Font and size | x | y (baseline, or box top–bottom) |
| --- | --- | --- | --- | --- |
| Header band | `invoice_band.png`, width 595.5 | — | 0 | box 0 – 120.03 |
| Logo | `printevr_logo.png`, 88.6 × 30.7 | — | 494.3 | box 119.6 – 150.3 |
| Date label | `Date` | Regular 12 | 28.55 | 78.22 |
| Date value | `:  14 SEP , 2026` (colon, two spaces, date) | Regular 12 | 73.49 | 78.22 |
| Bill label | `Bill No` | Regular 12 | 28.55 | 96.23 |
| Bill value | `:  18` | Regular 12 | 73.49 | 96.23 |
| Ship To heading | `SHIP TO` | Regular 13.94 | 39.40 | 143.39 |
| Ship To underline | bar | — | 39.4 – 99.2 | 144.2 – 145.1 |
| From heading | `FROM - PRINTEVR` | Regular 13.51 | 353.01 | 141.38 |
| From underline | bar | — | 353.0 – 475.4 | 142.2 – 143.0 |
| From lines 1–4 | `from_lines` from config | Regular 10.55 | 354.39 | 160.08 · 175.26 · 190.43 · 205.61 |
| Ship To lines | section 7.3 | 8.26 | 39.40 | 164.21 · 176.60 · 189.00 · 201.39 |
| Table header pill | — | — | 22.1 – 553.3 | 248.4 – 275.9 |
| `ITEM` | — | Regular 10.11 | 43.47 | 266.58 |
| `QUANTITY` | — | Regular 10.38 | 264.37 | 264.36 |
| `PRICE PER PCS` | — | Regular 9.10 | 412.87 | 263.24 |
| `SUBTOTAL` | — | Regular 9.13 | 488.55 | 263.20 |

The four header labels really do have slightly different sizes and baselines on the sample; copy them as given. Don't draw the word "INVOICE", the pill around it, the band colour or the asterisks: they're all in `invoice_band.png`.

### 7.3 Ship To block

Line step 12.39 pt, starting at baseline 164.21, x 39.40, size 8.26.

1. Business name in capitals plus a trailing comma, **Bold**.
2. Contact person in capitals plus a trailing comma, **Bold**. If blank, skip the line and move the rest up one step.
3. Address in capitals, Regular, no trailing comma. Wrap at x 339.4 into at most two lines.
4. Phone exactly as typed plus a trailing comma, **Bold**.

### 7.4 Item rows

The sample's two rows were laid out by hand in Canva with different font sizes and column positions. Generated rows follow **one standard layout** (decision D9): the title and specs follow the thank-you-card row, and the numbers follow the corrugated-box row and the column headers.

**Column anchors**

| Cell | Font | Placement |
| --- | --- | --- |
| Quantity | Bold 9.66 | centred on x 291.4 |
| Unit label, e.g. `(BOXES)` | Regular 5.74 | centred on x 291.4 |
| Middle: note | Bold 7.66 | left at x 313.15, must end by x 432 |
| Middle: reference price | Regular 9.66 | centred on x 387.5 |
| Price per pcs | Regular 9.66 | centred on x 448.0 |
| Subtotal | Bold 9.66 | centred on x 512.9 |

**Layout of one row**, starting at row top `R` (275.9 for the first row on page 1; 67.5 on continuation pages):

1. **Title**: capitals, Bold 11, x 37.7, baseline `R + 22.2`. It must end by x 272. If it's too wide, reduce the size in 0.25 pt steps down to 9 pt; if it still doesn't fit, wrap into two lines 12.5 pt apart.
2. **Numbers baseline** `nb` = first title baseline + 7.2. Quantity, reference price, price and subtotal sit on `nb`; the note sits on `nb − 0.8`; the unit label on `nb + 6.1`.
3. A note wider than its space shrinks down to 6 pt, then wraps to a second line 8.5 pt lower.
4. **Specs**: first baseline = last title baseline + 12.65, then every 8.0 pt, size 6. Each spec starts with a black dot 2.0 pt across, centred at x 49.3 and 1.55 pt above the baseline. Text starts at x 55.46: `{LABEL}:-` in Bold, one space, then the value in Regular (Bold when `emphasis` is true). A spec with no label prints its value alone in Regular. Text must end by x 272; wrap longer text onto continuation lines (8.0 pt step, no dot) that start under the value, or at x 55.46 if the label is wider than 150 pt.
5. **Customisations** (only if any): heading `CUSTOMISATIONS:-`, Bold 6, x 39.4, baseline = previous baseline + 12.0 (or last title baseline + 12.65 when there are no specs). Items follow every 8.0 pt, formatted exactly like specs.
6. **Row separator**: a bar from x 17.9 to 559.4, 0.7 pt tall, centred on `y = lowest baseline in the row (including unit label and a wrapped note) + 10.5`. The next row's `R` is that `y`.
7. Text in rows is in capitals: title, labels, values, unit label and note. Numbers use the formats in 6.3.

Check against the reference's second row: `R` 372.5 gives title 394.7 (reference 395.05), first spec 407.35 (407.70), separator 449.85 (450.2). The first row will come out taller than the reference because its specs are 6 pt instead of Canva's 4 pt; that's expected, and the tests in section 11 allow for it.

### 7.5 Payment terms box

1. Box top `T` = last row separator + 20.7. Box from x 22.1 to 580.9, 1.5 pt stroke.
2. Title: Bold 15.01, x 31.19, baseline `T + 24.75`.
3. Lines (section 6.4): size 12, x 51.24, first baseline `T + 43.95`, then every 24.01 pt. Bold parts in Montserrat-Bold, the rest Regular.
4. Each line has a black dot 3.8 pt across, centred at x 40.2 and 4.15 pt above its baseline.
5. Box bottom = last line baseline + 13.4. With five lines the box is 153.4 pt tall, as on the sample.
6. A line wider than 522 pt (x 51.24 to 573.2) shrinks down to 10 pt; if still too wide, it wraps onto a continuation line at x 51.24, 16 pt lower, and the box grows.

### 7.6 Totals, saving and footer

These sit at fixed positions at the bottom of the **last** page.

| Element | Content | Font and size | x | Baseline |
| --- | --- | --- | --- | --- |
| Total label | `TOTAL:` | Bold 12.70 | 434.48 | 703.89 |
| Total value | T | Regular 12.70 | right edge at 536.93 | 703.80 |
| Sub total pill | — | — | 374.9 – 559.4 | box 710.3 – 744.1 |
| Pill label | `SUB TOTAL :` | Regular 16.97 | 382.45 | 733.27 |
| Pill value | P | Regular 14.95 | right edge at 547.58; if it would start left of x 490, shrink down to 11 pt | 733.72 |
| Saving line 1 | `TOTAL **SAVING** YOU DID FROM GETTING` | 7.52 | 17.89 | 744.38 |
| Saving line 2 | `YOUR PRINTING DONE FROM **PRINTEVR** IS` | 7.52 | 17.89 | 753.16 |
| Saving amount | saving amount | Bold 17.91 | 28.50 | 778.09 |
| `APPROX` | — | Regular 7.52 | amount's right edge + 1.66 | 774.24 |
| Thanks | `THANK YOU FOR YOUR BUSINESS.` | Regular 7.97 | 14.45 | 797.51 |
| Contact | `If you have any questions, please contact us at ` + email | Regular 6.84 | 14.45 | 807.25 |
| Email underline | bar under the e-mail address only | — | email's x0 – x1 | 807.6 – 808.1 |
| Advance note | `100% OF THE PAYMENT WILL BE TAKEN IN ADVANCE FOR PRINTING ORDERS` | Regular 5.13 | 14.45 | 817.17 |
| Colour note | `Colours can vary up to 10-20% from Digital to Print.` | Regular 5.13 | 14.62 | 825.37 |
| Late note | `Late payment will attract additional 5% Charges` | Regular 5.13 | 169.70 | 825.37 |
| Terms note | `Terms & Condition applied (Refer to T&C pdf)` | Regular 5.13 | 14.62 | 833.66 |
| GST note | see 7.8 | Regular 5.69 | 169.26 | 833.74 |

The saving block (lines 1–2, amount, APPROX) is drawn only when a saving amount above 0 was given. All footer text comes from `config/invoice.yaml`.

### 7.7 Pagination

1. Place rows in order. A row whose separator would fall below y 800 moves to a new continuation page.
2. After the last row, the payment box must end at or above y 684 (668 with GST billing, because the totals block is one line taller). If it doesn't fit, it moves to a new page with `T = 40.0` and no table header.
3. The totals, saving and footer block goes on the page that holds the payment box.
4. Continuation pages have no band, logo, date or Ship To. They show `Bill No : {n} (continued)` in Regular 9 at x 28.55, baseline 28.0, and, when they carry rows, a table header pill at 40.0–67.5 with the four labels at the same offsets from the pill top as on page 1 (ITEM +18.18, QUANTITY +15.96, PRICE PER PCS +14.84, SUBTOTAL +14.80).
5. When there is more than one page, every page shows `Page {n} of {N}` in Regular 6, right edge at x 580.9, baseline 834.0.
6. A row is never split across pages.

### 7.8 With GST billing

1. Payment box title reads `(WITH GST BILLING)`; the lines use P including GST.
2. The totals block gains a line. `TOTAL:` and its value move up 16 pt (baselines 687.89 and 687.80). A new line `GST (18%):` (Bold 12.70, right edge at 481.62 so its colon lines up with `TOTAL:`) with value G (Regular 12.70, right edge 536.93) takes the old TOTAL baselines 703.89 / 703.80. The pill shows P.
3. The GST note reads `gst_note_with_gst` from config instead of `gst_note_without_gst`.
4. Without GST billing the page matches the sample exactly: there is no GST line.

## 8. Backend

### 8.1 Modules

```
backend/app/invoice/
├── layout.py      # every coordinate, size and font from section 7 (single source)
├── models.py      # Pydantic: SpecLine, Middle, CartLine, Customer, Payment, InvoiceCreate, InvoiceRecord
├── money.py       # section 6.1–6.2, pure
├── fmt.py         # section 6.3 formats and capitalisation, pure
├── terms.py       # section 6.4 payment-terms lines as runs [(text, bold)], pure
├── from_quote.py  # FR-C1 invoice line drafts from a quote result, pure
├── paginate.py    # row measurement and page breaking (section 7.4, 7.7), pure apart from font metrics
├── render.py      # ReportLab drawing: InvoiceDocument -> bytes
├── store.py       # SQLAlchemy models and queries
├── service.py     # create invoice, add payment: validate, re-price, bill number, save, render
├── auth.py        # staff login and token check
└── routes.py      # FastAPI router mounted under /api
backend/assets/invoice/   invoice_band.png, printevr_logo.png   (supplied)
backend/assets/fonts/     Montserrat-Regular.ttf, Montserrat-Bold.ttf, OFL.txt   (download)
config/invoice.yaml
```

New dependencies: `reportlab`, `Pillow`, `SQLAlchemy` 2.x, `itsdangerous` (or `hmac` from the standard library) for tokens; dev only: `pdfplumber`, `pypdfium2`, `numpy`. If you add Postgres support, `psycopg[binary]`.

### 8.2 Data model

One database, chosen by `DATABASE_URL` (default `sqlite:///./var/invoices.db`; create `var/` and git-ignore it).

**invoices**

| Column | Type | Notes |
| --- | --- | --- |
| id | integer PK | |
| bill_no | integer, unique, not null | |
| invoice_date | date | |
| billing_type | text | `without_gst` or `with_gst` |
| customer | JSON | business_name, contact_person, address, phone |
| lines | JSON | the cart lines as printed, including `price_edited` |
| payments | JSON | list of amount, date, mode, note, recorded_at |
| saving_amount | numeric(12,2), null | |
| total, gst_amount, payable, received | numeric(12,2) | stored for the list view |
| status | text | `unpaid`, `part_paid`, `paid` |
| version | integer | starts at 1; +1 on each payment |
| created_at, updated_at | timestamp (UTC) | |

**invoice_events**: id, bill_no, event (`created`, `payment_added`, `downloaded`), at (UTC), detail (JSON: version, amounts; never customer details).

Stored invoices are never re-priced. Re-downloading renders from the stored JSON, so a later price-sheet change can't alter an issued invoice.

### 8.3 Bill numbers

1. `next = max(bill_no) + 1`, or `bill_no_start` from config (19, since the last paper bill was 18) when the table is empty.
2. If the request has no `bill_no`, assign `next` and insert; on a unique-constraint clash, retry up to 3 times with a fresh `next`.
3. If the request gives a `bill_no` that exists, answer `409 BILL_NO_TAKEN` with `details.next_bill_no`.

### 8.4 API

Errors keep the existing shape `{ "status": "error", "error": { "code", "message", "details" } }`. All `/api/invoices…` routes need `Authorization: Bearer <token>`.

| Method | Path | Does |
| --- | --- | --- |
| POST | `/api/calculate` | Existing. Success responses gain `data.invoice_lines` (FR-C1). |
| POST | `/api/staff/login` | `{ passcode }` → `{ token, expires_at }` |
| GET | `/api/invoices/next-bill-no` | `{ next_bill_no }` |
| POST | `/api/invoices` | Create and return the PDF (below) |
| GET | `/api/invoices?q=&status=&limit=25&offset=0` | List rows for the Invoices page |
| GET | `/api/invoices/{bill_no}` | Full stored record as JSON |
| GET | `/api/invoices/{bill_no}/pdf` | Render the stored invoice |
| POST | `/api/invoices/{bill_no}/payments` | `{ amount, date, mode, note }` → updated PDF |

**Create request**

```json
{
  "bill_no": null,
  "invoice_date": "2026-09-29",
  "billing_type": "without_gst",
  "customer": { "business_name": "…", "contact_person": "…", "address": "…", "phone": "…" },
  "lines": [ /* cart lines, section 4 */ ],
  "payments": [ { "amount": "30000", "date": "2026-09-29", "mode": "upi", "note": null } ],
  "saving_amount": "30000",
  "print_mode": "paid"
}
```

**PDF responses** (create, pdf, payments): status 201 (create) or 200, `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="Invoice_18_Sogat-Jutti-Store_Part-paid.pdf"`, plus headers `X-Bill-No` and `X-Invoice-Status`. Add these three headers to CORS `expose_headers`, or the browser can't read them from another origin.

**Error codes**

| Code | HTTP | When |
| --- | --- | --- |
| `AUTH_REQUIRED` | 401 | Missing, bad or expired token |
| `BAD_PASSCODE` | 401 | Wrong passcode |
| `RATE_LIMITED` | 429 | More than 5 logins a minute from one IP |
| `INVOICING_DISABLED` | 503 | `STAFF_PASSCODE` not set |
| `VALIDATION_ERROR` | 422 | Any field outside its limits; wrong payments for the print mode |
| `LINE_NOT_PRICEABLE` | 422 | A catalogue line now gets `manual_quote` |
| `OVERPAID` | 422 | Received would exceed payable |
| `PRICES_CHANGED` | 409 | Re-pricing changed a line; `details.lines` = `[{ id, quantity, catalogue_unit_price, warnings }]` |
| `BILL_NO_TAKEN` | 409 | Given bill number exists; `details.next_bill_no` |
| `NOT_FOUND` | 404 | Unknown bill number |
| `ALREADY_PAID` | 422 | Payment added to a paid invoice |

### 8.5 Configuration: `config/invoice.yaml`

Business text lives here, never in code.

```yaml
bill_no_start: 19
gst_rate: 0.18
advance_pct: 80
pad_single_digit_unit_price: true
filename: "Invoice_{bill_no}_{business}_{status}.pdf"
status_labels: { unpaid: Unpaid, part_paid: Part-paid, paid: Paid }
unit_plurals: { box: boxes, bag: bags, card: cards, roll: rolls, sheet: sheets, label: labels, piece: pcs, "sq ft": "sq ft" }
from_lines:
  - "#Plot no - 1795 2nd Floor,"
  - "Hallo Mazra 160002"
  - "Chandigarh"
  - "Ph- 6239645912, 7696771179"
payment_terms:
  title: "PAYMENT TERMS     ({billing_label})"
  billing_labels: { without_gst: "WITHOUT GST BILLING", with_gst: "WITH GST BILLING" }
  total: "**Total Amount:- Rs. {payable}/-**"
  advance: "**{advance_pct}% amount pending (before printing & after sample & final confirmation):-  {advance}/-**"
  received: "Recieved Amount:- Rs. {amount}/- ({date})"
  pending: "Amount Pending (out of {advance_pct}%) :- {advance}/-  (-)  {applied}/-  =  **{pending}/-**"
  balance: "{balance_pct}% Amount:- Rs. {balance}/- (Before Dispatching the Order)"
  balance_after_excess: "{balance_pct}% Amount:- Rs. {balance}/-  (-)  {excess}/-  =  **{balance_due}/-** (Before Dispatching the Order)"
  paid_in_full: "**Payment Status:- PAID IN FULL**"
totals:
  gst_label: "GST ({gst_pct}%):"
saving_lines:
  - "TOTAL **SAVING** YOU DID FROM GETTING"
  - "YOUR PRINTING DONE FROM **PRINTEVR** IS"
footer:
  thanks: "THANK YOU FOR YOUR BUSINESS."
  contact_prefix: "If you have any questions, please contact us at "
  email: "Printevrventure@gmail.com"
  advance_note: "100% OF THE PAYMENT WILL BE TAKEN IN ADVANCE FOR PRINTING ORDERS"
  colour_note: "Colours can vary up to 10-20% from Digital to Print."
  late_note: "Late payment will attract additional 5% Charges"
  terms_note: "Terms & Condition applied (Refer to T&C pdf)"
  gst_note_without_gst: "Note:-  18%  gst as applicable will be extra on total"
  gst_note_with_gst: "Note:-  18%  gst has been added to the total"
```

`products.yaml` gains two optional fields per product: `invoice_title` and `invoice_unit_label`.

### 8.6 Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `STAFF_PASSCODE` | none | Turns invoicing on |
| `SECRET_KEY` | none; required when `STAFF_PASSCODE` is set | Signs staff tokens |
| `DATABASE_URL` | `sqlite:///./var/invoices.db` | Invoice storage |
| existing CORS origin variable | — | Also expose `Content-Disposition`, `X-Bill-No`, `X-Invoice-Status` |

**Hosting note.** On a normal server or with `docker compose`, the SQLite default is fine (mount `var/` as a volume). On a serverless host such as Vercel, local disk is wiped between requests, so set `DATABASE_URL` to a hosted Postgres (Neon, Supabase or Vercel Postgres). Write this in the README.

## 9. Frontend

### 9.1 Components

| Component | Job |
| --- | --- |
| `CartProvider` (context + reducer) | Cart lines and checkout form; saves to `localStorage` (FR-C5) |
| `AddToCartButton` | On the receipt card (FR-C2) |
| `CartButton` | Header badge with line count |
| `CartPage` | Lines, custom item, stale-price banner, checkout, print buttons |
| `CartLineCard` / `CartLineEditor` | View and edit one line (FR-C3) |
| `SpecListEditor` | Shared by specs and customisations |
| `CustomItemDialog` | FR-C4 |
| `CheckoutForm` | FR-P1 with the money summary |
| `PrintButtons` + `PaymentDialog` | FR-P2 to FR-P4 |
| `StaffLoginDialog` | FR-P8 |
| `InvoicesPage` | FR-P6 |
| `lib/invoiceMoney.ts` | Section 6.1–6.2 for display, using a decimal library or integer paise; never floats for money |
| `lib/download.ts` | Blob download (FR-P5) |

### 9.2 Behaviour details

1. The cart page works one-handed on a 375 px phone: cards stack, the print buttons stick to the bottom of the screen above the keyboard-safe area.
2. Every input has a label; the whole flow works by keyboard.
3. While a print request runs, both print buttons show a spinner and are disabled; a second tap does nothing.
4. Network failure: "Can't reach the server. Nothing was saved." with a Retry button; the cart and form stay filled.
5. `409 BILL_NO_TAKEN`: put `next_bill_no` into the field and say "Bill No 18 is already used. Changed to 19; press Print again."
6. `409 PRICES_CHANGED`: apply the fresh values, show the stale-price banner, highlight changed lines.
7. Show amounts in the UI with the existing `en-IN` currency formatter.

## 10. Non-functional requirements

| Area | Requirement |
| --- | --- |
| Speed | PDF for up to 10 lines rendered in under 800 ms at the 95th percentile |
| Size | Invoice PDF under 1 MB (the band image is about 300 KB) |
| Accuracy | `Decimal` for all money in Python; no floats for money in TypeScript |
| Determinism | Same stored invoice → byte-identical PDF (`invariant=1`) |
| Privacy | Customer details live only in the database and the PDF. Logs record bill number, totals, status and line count, never names, phones or addresses. |
| Security | Staff token on all invoice routes; passcode compared in constant time; login rate-limited; tokens expire after 12 hours |
| Integrity | Issued invoices are never re-priced or edited, only extended with payments; every change bumps `version` and writes an event |
| Browsers | Current Chrome, Edge and iOS Safari |

## 11. Tests

Add these to the existing pytest and Vitest suites. The build isn't done until all old and new tests pass.

### 11.1 Golden invoice tests (`backend/tests/test_invoice_golden.py`)

Render `sogat_jutti_bill18.json` and compare with `reference_bill18.pdf`.

**Coordinate note.** The reference PDF's MediaBox is `[0 7.83 595.5 850.08]`, so tools read it 7.83 pt off: pdfplumber reports shape tops 7.83 pt too high and character matrix positions 7.83 pt too low. `layout_reference.json` is already corrected. When you measure the reference yourself, correct it the same way; when you measure your own PDF (MediaBox starting at 0), no correction is needed. For text, take the baseline from each character's matrix: `baseline = page_top − matrix[5]`.

| ID | Check |
| --- | --- |
| G1 | One page, 595.5 × 842.25 pt |
| G2 | Every reference text run with baseline < 280 or > 690 (header, Ship To, From, table header, totals, saving, footer) appears in the output with the same text, same font (Montserrat Regular or Bold), size within 0.05 pt, x0 within 1.0 pt and baseline within 1.0 pt. Skip the INVOICE word (it's in the band image). |
| G3 | Rasterise both PDFs at 100 dpi with pypdfium2, greyscale. In the regions y 0–280 and y 690–842.25, pixels differing by more than 48 levels must be under 1.5% of the region. On failure, save a red/blue overlay PNG to `backend/tests/output/` to show where. |
| G4 | Payment box: its five lines equal `expected.payment_lines` character for character; bold runs are exactly those marked in section 6.4; box top = last row separator + 20.7 (± 0.3); box height 153.4 (± 0.5); five dots |
| G5 | Items: each row's quantity, unit, middle, price and subtotal strings equal `expected.line_cells`; each is centred or left-aligned on its column anchor (section 7.4) within 0.5 pt; one separator bar under each row; titles and specs print in capitals |

### 11.2 Unit tests

| ID | Check |
| --- | --- |
| P1–P8 | Section 6.5 |
| F1 | `amount(148000)` → `148000`; `amount(88.5)` → `88.50`; `unit_price(8)` → `08`; `unit_price(140)` → `140`; `unit_price(5.5)` → `5.50` |
| F2 | Invoice date 2026-09-14 → `14 SEP , 2026`; 2026-09-09 → `9 SEP , 2026`; payment date 2026-09-09 → `9 September 2026` |
| F3 | Filename for bill 18, "Sogat Jutti Store!", part paid → `Invoice_18_Sogat-Jutti-Store_Part-paid.pdf` |
| R1 | A cart of 12 lines of 8 specs each paginates: no row split, payment box and totals on the last page, `Page n of N` on every page |
| R2 | A With GST invoice (P6) draws TOTAL at 687.89, GST at 703.89, SUB TOTAL 174640 in the pill |
| R3 | Same stored invoice rendered twice → identical bytes |

### 11.3 Cart line drafts (`backend/tests/test_invoice_from_quote.py`)

Use the calculator's golden cases from `docs/BRD.md` section 11.

| ID | Quote | Expected `invoice_lines` |
| --- | --- | --- |
| K1 | T1: Rigid 3×3×2 Top-Bottom, 350 | One line; title from `invoice_title`; specs `Size: 3*3*2 in (LxWxH)` (emphasis) and `Box type: Top-Bottom`; quantity 350; unit `boxes`; unit price 75.00; subtotal 26250.00 |
| K2 | T3: same, 60 | Quantity 100 (billed); warning `MOQ_APPLIED` carried |
| K3 | T9: cards + round edges | Unit price 6.00; spec `Add-on: Round edges` |
| K4 | T14: butter paper 1,500 + multicolour | Two lines: 1500 × 5.50 = 8250.00, and `Multicolour print (add-on)` 1 × 1000 = 1000.00; together 9250.00, equal to the quote subtotal |
| K5 | C1: custom 3.5×3.5×2, 300 | Spec `Size: 3.5*3.5*2 in (LxWxH)`; unit price 88.50; subtotal 26550.00; warning `CUSTOM_ESTIMATE` carried |
| K6 | C4: custom 20×20×5 | `manual_quote`, no `invoice_lines` |

### 11.4 API tests (`backend/tests/test_invoice_api.py`)

| ID | Check |
| --- | --- |
| A1 | `POST /api/invoices` without a token → 401 `AUTH_REQUIRED` |
| A2 | Wrong passcode → 401; sixth attempt within a minute → 429 |
| A3 | Unpaid invoice from K1 → 201, PDF bytes start with `%PDF`, `X-Bill-No` = 19 on an empty DB, `X-Invoice-Status: unpaid`, one row and one `created` event |
| A4 | Two creates at the same time without `bill_no` → two different, consecutive numbers |
| A5 | Explicit `bill_no` that exists → 409 `BILL_NO_TAKEN` with `next_bill_no` |
| A6 | K1 line sent with `catalogue_unit_price` 70 → 409 `PRICES_CHANGED` with 75.00; sent with catalogue 75 and `unit_price` 70 → 201 and `price_edited: true` stored |
| A7 | `print_mode: paid` with no payments → 422; `unpaid` with a payment → 422 |
| A8 | Add a payment to bill 19 → 200 PDF, same bill number, status updated, `version` 2, `payment_added` event; paying the rest → `paid`; one more payment → 422 `ALREADY_PAID` |
| A9 | `GET /api/invoices/19/pdf` twice → identical bytes |
| A10 | `STAFF_PASSCODE` unset → invoice routes 503 `INVOICING_DISABLED`; `/api/calculate` unaffected |
| A11 | CORS response exposes `Content-Disposition`, `X-Bill-No`, `X-Invoice-Status` |

### 11.5 Frontend tests (Vitest + React Testing Library, API mocked)

| ID | Check |
| --- | --- |
| U1 | Add to cart from a receipt → badge shows 1; `localStorage` holds the line; remount restores it |
| U2 | Changing a catalogue line's quantity calls `/api/calculate` once after typing stops and updates the subtotal |
| U3 | Print buttons stay disabled until business name, address, phone and at least one priced line are present |
| U4 | Print (Unpaid as of now) posts `print_mode: "unpaid"` and `payments: []`, then downloads with the file name from `Content-Disposition` |
| U5 | Print (Paid) dialog pre-fills the payable amount and today's IST date; confirming posts one payment |
| U6 | A 409 `PRICES_CHANGED` updates the line and shows the banner without downloading |
| U7 | A manual-quote receipt shows "Add as custom item" and opens the dialog with the price empty |

### 11.6 Manual acceptance (on a phone, after M6)

1. Add three articles (one standard size, one custom size, one with a per-order add-on) and one custom item.
2. Print (Unpaid as of now): open the PDF next to `reference_bill18.pdf`. Header, Ship To, From, table header, totals and footer should be indistinguishable in position and style.
3. On the Invoices page, record a part payment, then the rest. Check the payment lines against section 6.4 each time.
4. Try With GST billing once and check the totals block.

## 12. Build plan (one session)

| # | Milestone | Build | Done when |
| --- | --- | --- | --- |
| M0 | Survey and setup | Read the repo; write the mapping from this BRD to the real files (5–15 lines). Download the Montserrat TTFs and `OFL.txt`. Add dependencies. Create `config/invoice.yaml`. | Existing tests still pass; fonts load in a 3-line ReportLab smoke script |
| M1 | Money and formats | `money.py`, `fmt.py`, `terms.py` | P1–P8, F1–F3 pass |
| M2 | Invoice renderer | `layout.py`, `paginate.py`, `render.py` | G1–G5, R1–R3 pass. Open the rendered fixture next to the reference once yourself. |
| M3 | Line drafts | `from_quote.py`; `invoice_lines` on `/api/calculate`; `invoice_title` for all 27 products | K1–K6 pass; existing calculator tests unchanged |
| M4 | Storage, auth and API | `store.py`, `auth.py`, `service.py`, `routes.py`; CORS headers | A1–A11 pass |
| M5 | Cart and printing UI | Components in 9.1 except `InvoicesPage` | U1–U7 pass |
| M6 | Invoices page and wrap-up | `InvoicesPage`, Record payment; README (env vars, hosting note, how to run tests); `CLAUDE.md` additions | Full pytest and Vitest suites green; summary lists the 27 invoice titles, any deviations from this BRD, and the manual acceptance steps in 11.6 |

Work on M2 carefully: it's the part the user will judge by eye. If G2 or G3 fail, fix the constants in `layout.py` from `layout_reference.json`; don't loosen the tests.

## 13. Decisions taken by default

Each has a default already built in. Change it later in config or with a small follow-up.

| ID | Decision | Default | Why |
| --- | --- | --- | --- |
| D1 | What "Print (Paid)" records | Amount received, defaulting to the full payable amount; can be lowered for an advance, and several payments can be added | The sample invoice is a part payment (₹30,000 of ₹1,48,000), so "paid" has to cover advances too |
| D2 | Payment lines on an unpaid invoice | Total, 80% line and 20% line only | "Received ₹0" and "pending out of 80%" would repeat the 80% line |
| D3 | Sample wording and spelling | Copied exactly, including "Recieved" and the double spaces | The request was for the exact format; each phrase is one line in `config/invoice.yaml` if anyone wants it corrected |
| D4 | GST on the invoice | One rate (18%) from `config/invoice.yaml`; GST shown as one line | Matches the sample's footer note; per-category rates and the CGST/SGST split are out of scope |
| D5 | Editing prices in the cart | Allowed, with a visible "edited" badge and `price_edited` stored | Sales negotiates; the sample shows an ₹8 price against a ₹15 reference |
| D6 | Bill numbers | Auto-assigned from 19, editable, duplicates refused | Continues the paper series after Bill No 18 |
| D7 | Saving amount | Typed by staff, with a suggested figure; hidden when blank | The sample's "30000 APPROX" isn't derived from the line prices |
| D8 | Access | One staff passcode for invoicing; calculator stays open | Invoices hold customer names, phones and addresses |
| D9 | Item row layout | One standard layout (section 7.4) instead of Canva's hand-sized rows | Generated rows must handle any text; header and footer still match the sample exactly |
| D10 | Tax-invoice fields | None added (no GSTIN, HSN, place of supply) | Printevr's current format has none. If "With GST billing" invoices are used as tax invoices, check the required fields with the CA. |

## 14. Additions to `CLAUDE.md`

- Invoice positions, sizes and fonts live only in `backend/app/invoice/layout.py`; they were measured from `reference_bill18.pdf`. Don't change them without re-running the golden tests.
- Business text for invoices lives in `config/invoice.yaml`, never in code.
- Money is `Decimal` in Python and never a float in TypeScript.
- Don't edit files in `backend/assets/invoice/` or `backend/tests/fixtures/invoice/`.
- Issued invoices are never re-priced; re-downloads render from the stored record.
- Run `pytest` and the frontend tests before saying a milestone is done.
