# Printevr Pricing Calculator

Internal quoting tool. The spec is `docs/BRD-v2.1.pdf` (BRD v2.1); read the relevant section before changing behaviour.

## Rules
- Money is `Decimal` everywhere in the backend. Never float, never hardcoded prices.
- Business numbers (GST, surcharge, rounding step, add-ons, policies, yields) come from `config/products.yaml` or the sheet, never from code.
- Don't edit files in `data/`. Prices change only in the spreadsheet.
- Functions under `backend/app/pricing/` take plain data and return plain data: no file reads, no HTTP.
- The browser never receives tier prices; `/api/catalog` sends breakpoints only.
- Run `cd backend && python -m pytest` and `cd frontend && npm test` before calling a change done. All BRD section 11 tests must pass.

## Known deviations from the BRD text
- **L1 item count is 233, not 284.** The sheet stores mailer-bag sizes as `6 × 8 in`, `6 × 8 in in`, `6 × 8 in in in`…, which would make every tier its own item. The loader collapses repeated unit words, which is also what makes L4's count of 11 come out right.
- Item ids keep decimal points (`rigid_boxes/3.5x5.5x4-in/top-bottom`) rather than turning them into hyphens.
- The API starts even if the sheet fails to load: `/api/health` shows the reason and pricing routes return `DATA_NOT_LOADED` (503) until a fixed sheet is reloaded.
