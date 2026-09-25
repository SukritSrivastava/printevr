"""Success criterion 1 / L5: every standard price is quoted exactly as in the sheet."""
from decimal import Decimal

from app.pricing.totals import money


def test_every_tier_row_quotes_the_sheet_price(catalogue, quote):
    checked = 0
    for item in catalogue.items.values():
        for tier in item.tiers:
            result = quote(item_id=item.id, quantity=tier.qty_from)
            assert result["status"] == "success", (item.id, tier.qty_from, result)
            pricing = result["data"]["pricing"]
            assert pricing["unit_price"] == format(money(tier.price), "f"), (item.id, tier.qty_from)
            assert pricing["tier_applied"]["qty_from"] == tier.qty_from
            checked += 1
    assert checked == 950


def test_catalogue_prices_match_raw_sheet_rows(catalogue, sheet):
    rows = [r for r in sheet[0] if r.tier_label.lower() != "sample cost"]
    by_row = {t.row: t for i in catalogue.items.values() for t in i.tiers}
    assert len(rows) == len(by_row) == 950
    for r in rows:
        assert by_row[r.row].price == Decimal(str(r.price)), r.row
