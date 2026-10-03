# Outstanding source-data decisions

Recorded 3 October 2026 from `data/Printevr_Pricing_Master_2025-26.xlsx` (tab **Review Flags**, read only) and `config/products.yaml`. These are for the data owner (Operations) to decide. The code doesn't guess any of them: prices stay exactly as printed, every flag stays `Open`, and quotes on flagged prices keep the amber "price under review" warning (`flagged_price_policy: warn`). To close one, correct the product tab in the workbook and set the flag's `Status` to anything but `Open`, then reload (README "Changing prices and settings").

"Row" is the row on the Review Flags tab.

## Blocking per BRD v2.1 section 4.2 ("fix before coding"; the tool works around them)

| Flag (row) | Product | Decision needed | Evidence |
|---|---|---|---|
| F7 (11) | Monocarton 8 × 8 × 1.5 in, both GSM rows | What the duplicated second row should be, or delete it | Same size listed twice with identical prices (p. 17). The loader keeps it as its own item; custom sizes take the higher price on a tie (README "Open data issues") |
| F8 (12) | Carry bag 10 × 7 × 3 in | Small (70/47/36/24/20) or Medium (85/47/36/29/24)? | One bag, two prices (pp. 23–24); both quotable today |
| F9 (13) | Cards (pg 15), whole page | Product name, production time, unit; fill or remove the four blank 600 GSM rows | Shows as "Untitled cards (pg 15)" with "Confirm production time" (`config/products.yaml` lines 205–215) |
| F10 (14) | Cards (pg 15), table A vs B | Which table is current; were 2.5 × 1.5 / 4.5 × 3 copy-pasted? | Table A repeats table B for three sizes; 4.5 × 3 is cheaper than the smaller 2 × 3.5 |
| F11 (15) | Monocartons p. 17 vs p. 18 | Is p. 17 a different build or board (label it), or is one page mispriced? | e.g. 8×8×2 = ₹15 at 2,500 vs 8×8×1.5 = ₹55; the two pages are interpolated together today |
| F1 (5) | Rigid 8 × 10 × 2.5 Magnetic/Slider, 1,000 qty | Correct price (printed ₹120; the sheet suggests ₹215) | Row 270/240/220/120/205; loader warns "price doesn't fall"; golden test T13 depends on it while Open |
| F2 (6) | Rigid 18 × 12 × 4 Magnetic/Slider, all qty | Correct ladder (printed 360 ×5) | No volume discount; loader warning |
| F3 (7) | Rigid 7 × 3 × 2.5 Magnetic/Slider, 2,000 qty | Correct price (printed ₹95; suggested ₹105) | Only +₹10 over Top-Bottom where all others are +₹20 |
| F4 (8) | Rigid 7 × 5 × 2 Magnetic/Slider, 100 qty | Correct price (printed ₹160; suggested ₹170) | Same +₹20 pattern |
| F5 (9) | Paper printing, 50–100 sheet tier (4 GSM rows) | Correct prices | 50 / 135 / 145 / 135 sit above the smaller tier; loader warns on all four |
| F6 (10) | Textured visiting card, double side, 2,500 | Correct price (printed ₹5.5) | Cheaper than single side, equal to the 5,000 price; loader warning |

## Pricing logic to confirm (F12–F21, rows 16–25)

| Flag | Product | Decision needed |
|---|---|---|
| F12 | Monocartons p. 18 size order | Larger boxes priced below smaller ones (3×3×3 < 3×3×2.5, …) |
| F13 | Raised-foil cards 600 GSM double side | The ₹0.5 double-side premium |
| F14 | Spot UV 600 GSM double side | Same premium; 600 GSM equals 400 GSM at 5,000 |
| F15 | Sticker sheets, 201–500 tier (Vinyl, Transparent, Vinyl+Lam) | The ~42 % step down |
| F16 | Frosted mailer bags 10×14, 12×16, 14×18 at 1,000 | No discount from 500 (loader warns on all three) |
| F17 | Courier bags at 500 | 10×14 (₹20) cheaper than 8×10 (₹21) |
| F18 | Corrugated 3×3×2 single-side SBS at 1,000 | ₹23 after ₹33 (suggested ₹28) |
| F19 | Large carry bags | Priced by height, not size? |
| F20 | Grosgrain ribbon | Roll length 90 m vs MOQ note 180 m; 0.75 in price; no 1.5 in |
| F21 | Cotton cloth labels | Same four prices as cotton ribbons: copy-paste? |

## Clarifications (F22–F27, rows 26–31) and config assumptions

| Item | Decision needed | Evidence / current assumption |
|---|---|---|
| F22 | Outdoor tier boundaries ("100 ft & less / 100–300 / 300 & more", and sq ft) | Master tab assumes 1 / 101 / 301 sq ft |
| F23 | Paper-printing tier boundaries overlap | Master tab assumes 10 / 31 / 51 / 101 / 201 / 501 |
| F24 + D8 | Add-on basis: butter-paper multicolour ₹1,000, custom cut ₹500, golden ₹500, cloth-label stitching ₹800, sample costs | Assumed **per order** (`config/products.yaml` lines 25–28, 31) |
| F25 | Pricing unit on box, bag and page-15 pages | Assumed per piece |
| F26 | Vinyl+Lam = Vinyl Eco at 100–300 sq ft; flat ID-card holder; rigid 8×10×2.5 TB = 10×10×3 TB | "Probably intentional"; ID-card holder triggers a loader warning |
| F27 | Catalogue spelling and copy errors | Text only; no price effect |
| Mailer-bag sizes | Fix `6 × 8 in in in`-style repeated units in the sheet | The loader cleans them (CLAUDE.md "L1 item count is 233") |
| HSN codes | An HSN code for each of the 27 products | Every `hsn_code` in `config/products.yaml` is `""` (CLAUDE.md: never guess one); GST invoices print a blank HSN and the cart warns |
| D3 | Custom-size surcharge | `custom_surcharge_pct: 0` (line 11) |
| D4 | GST rate per category / HSN (confirm with the CA) | 18 % everywhere (line 8) |
| D5 | Meaning of the "Invoice" (no-GST) billing type on the calculator | Hidden: `show_invoice_billing: false` (line 13) |
| D9 | Cloth labels per roll (catalogue: 2,000–2,500) | 2,000, shown as approx. (lines 98, 111) |
