"""T1-T15 and L6 (FR-2, FR-3, FR-5, FR-6)."""
import copy
from decimal import Decimal

import pytest

from app.pricing.tiers import BelowMinimum, better_option, resolve_tier, tier_range
from app.quote import QuoteError

from .conftest import RIGID_TB, codes

VC_300_GM_DOUBLE = "vc_standard/300-gsm/gloss-matte/double-side"


def data(result):
    assert result["status"] == "success", result
    return result["data"]


def money_line(d):
    t = d["totals"]
    return t["subtotal"], t["gst_amount"], t["grand_total"]


def test_t1_350_boxes(quote):
    d = data(quote(item_id=RIGID_TB, quantity=350))
    assert d["pricing"]["tier_applied"] == {"qty_from": 250, "label": "250 qty", "range": "250-499"}
    assert d["pricing"]["unit_price"] == "75.00"
    assert d["totals"] == {
        "subtotal": "26250.00",
        "billing_type": "gst",
        "gst_rate_percent": "18",
        "gst_amount": "4725.00",
        "grand_total": "30975.00",
    }
    assert d["pricing"]["next_tier"] == {"qty_from": 500, "units_to_next": 150, "unit_price": "55.00"}


def test_t2_exactly_500(quote):
    d = data(quote(item_id=RIGID_TB, quantity=500))
    assert d["pricing"]["unit_price"] == "55.00"
    assert money_line(d) == ("27500.00", "4950.00", "32450.00")


def test_t3_below_minimum_billed_at_minimum(quote):
    r = quote(item_id=RIGID_TB, quantity=60)
    d = data(r)
    assert d["quantity"]["requested"] == 60 and d["quantity"]["billed"] == 100
    assert d["pricing"]["unit_price"] == "105.00"
    assert d["totals"]["subtotal"] == "10500.00"
    assert "MOQ_APPLIED" in codes(r)


def test_t4_above_top_tier(quote):
    d = data(quote(item_id=RIGID_TB, quantity=5000))
    assert d["pricing"]["tier_applied"]["qty_from"] == 2000
    assert d["pricing"]["unit_price"] == "40.00"
    assert money_line(d) == ("200000.00", "36000.00", "236000.00")
    assert d["pricing"]["next_tier"] is None


def test_t5_cheaper_to_order_more(quote):
    d = data(quote(item_id=RIGID_TB, quantity=450))
    assert d["pricing"]["unit_price"] == "75.00"
    assert d["totals"]["subtotal"] == "33750.00"
    assert d["pricing"]["better_option"] == {"qty": 500, "subtotal": "27500.00", "saving": "6250.00"}


def test_t6_sticker_sheets_40(quote):
    d = data(quote(item_id="sticker_sheets/paper", quantity=40))
    assert d["pricing"]["tier_applied"]["range"] == "31-50"
    assert d["pricing"]["unit_price"] == "110.00"
    assert money_line(d) == ("4400.00", "792.00", "5192.00")


def test_t7_above_max_qty_is_manual_quote(quote):
    r = quote(item_id="sticker_sheets/paper", quantity=1200)
    assert r["status"] == "manual_quote" and r["reason"] == "MANUAL_QUOTE"


def test_t8_visiting_cards(quote):
    d = data(quote(item_id=VC_300_GM_DOUBLE, quantity=1200))
    assert d["pricing"]["tier_applied"]["qty_from"] == 1000
    assert d["pricing"]["unit_price"] == "5.00"
    assert money_line(d) == ("6000.00", "1080.00", "7080.00")


def test_t9_round_edges_per_card(quote):
    d = data(quote(item_id=VC_300_GM_DOUBLE, quantity=1200, addons=["round_edges"]))
    assert d["addons"] == [{"id": "round_edges", "name": "Round edges", "price": "1.00", "basis": "per_unit"}]
    assert money_line(d) == ("7200.00", "1296.00", "8496.00")


def test_t10_ribbon_rolls(quote):
    d = data(quote(item_id="ribbon_single_colour/1.0-in/180-m", quantity=3))
    assert d["pricing"]["unit_price"] == "2399.00"
    assert d["pricing"]["micro_unit_price"] == "13.33" and d["pricing"]["micro_uom"] == "per metre"
    assert d["quantity"]["micro"] == {"amount": 540, "unit": "m", "approx": False}
    assert money_line(d) == ("7197.00", "1295.46", "8492.46")


def test_t11_micro_prices(quote):
    grosgrain = data(quote(item_id="ribbon_grosgrain/0.5-in/90-m", quantity=1))
    assert grosgrain["pricing"]["micro_unit_price"] == "34.43"
    silk = data(quote(item_id="labels_silk/0.5-in/180-m", quantity=1))
    assert silk["pricing"]["micro_unit_price"] == "1.55"
    assert silk["pricing"]["micro_uom"] == "per label" and silk["pricing"]["micro_approx"] is True


def test_t12_outdoor_square_feet(quote):
    d = data(quote(item_id="outdoor_branding/flex-printing-star", quantity=10 * 12 * 2))
    assert d["quantity"]["billed"] == 240
    assert d["pricing"]["tier_applied"]["range"] == "101-300"
    assert d["pricing"]["unit_price"] == "35.00"
    assert money_line(d) == ("8400.00", "1512.00", "9912.00")
    assert d["pricing"]["better_option"] is None


def test_outdoor_accepts_fractional_square_feet(quote):
    d = data(quote(item_id="outdoor_branding/flex-printing-star", quantity="7.5"))
    assert d["totals"]["subtotal"] == "337.50"


def test_other_products_need_whole_units(quote):
    with pytest.raises(QuoteError) as exc:
        quote(item_id=RIGID_TB, quantity="10.5")
    assert exc.value.code == "VALIDATION_ERROR"


def test_t13_flagged_price_warns(quote):
    d = data(quote(item_id="rigid_boxes/8x10x2.5-in/magnetic-slider", quantity=1200))
    assert d["pricing"]["unit_price"] == "120.00"
    assert d["totals"]["subtotal"] == "144000.00"
    warning = next(w for w in d["warnings"] if w["code"] == "PRICE_UNDER_REVIEW")
    assert warning["flags"] == ["F1"]


def test_t14_butter_paper_with_per_order_addon(quote):
    d = data(quote(item_id="butter_paper/29x9-in", quantity=1500, addons=["multicolour"]))
    assert d["pricing"]["unit_price"] == "5.50"
    assert money_line(d) == ("9250.00", "1665.00", "10915.00")
    assert d["pricing"]["better_option"] == {"qty": 2000, "subtotal": "9000.00", "saving": "250.00"}


def test_t15_invoice_billing_has_no_gst(quote):
    d = data(quote(item_id=RIGID_TB, quantity=350, billing_type="invoice"))
    assert d["totals"]["gst_amount"] == "0.00"
    assert d["totals"]["grand_total"] == "26250.00"


def test_l6_fixed_flag_no_longer_warns(sheet, rebuild, quote):
    cat = rebuild(flags=dict(sheet[1]) | {"F1": "Fixed"})
    r = quote(cat=cat, item_id="rigid_boxes/8x10x2.5-in/magnetic-slider", quantity=1200)
    assert "PRICE_UNDER_REVIEW" not in codes(r)


def test_flagged_price_policy_block(sheet, rebuild, quote):
    config = copy.deepcopy(sheet[2])
    config["defaults"]["flagged_price_policy"] = "block"
    cat = rebuild(config=config)
    with pytest.raises(QuoteError) as exc:
        quote(cat=cat, item_id="rigid_boxes/8x10x2.5-in/magnetic-slider", quantity=1200)
    assert exc.value.code == "PRICE_BLOCKED"


def test_below_min_policy_block(sheet, rebuild, quote):
    config = copy.deepcopy(sheet[2])
    config["defaults"]["below_min_policy"] = "block"
    cat = rebuild(config=config)
    with pytest.raises(QuoteError) as exc:
        quote(cat=cat, item_id=RIGID_TB, quantity=60)
    assert exc.value.code == "BELOW_MIN" and exc.value.http_status == 422


def test_sample_addon_uses_sheet_price(quote):
    d = data(quote(item_id="sticker_sheets/paper", quantity=40, addons=["sample"]))
    assert d["totals"]["subtotal"] == "4650.00"


def test_unknown_addon_is_rejected(quote):
    with pytest.raises(QuoteError) as exc:
        quote(item_id=RIGID_TB, quantity=100, addons=["round_edges"])
    assert exc.value.code == "VALIDATION_ERROR"


def test_production_time_unknown(quote, catalogue):
    item = catalogue.products["cards_pg15_b"].items[0]
    r = quote(item_id=item.id, quantity=500)
    assert "PRODUCTION_TIME_UNKNOWN" in codes(r)


# -------- pure functions


def test_resolve_tier_rules():
    bp = [100, 250, 500, 1000, 2000]
    assert resolve_tier(bp, Decimal(249), "bill_at_min").index == 0
    assert resolve_tier(bp, Decimal(250), "bill_at_min").index == 1
    assert resolve_tier(bp, Decimal(99999), "bill_at_min").index == 4
    m = resolve_tier(bp, Decimal(1), "bill_at_min")
    assert (m.billed_qty, m.moq_applied) == (100, True)
    with pytest.raises(BelowMinimum):
        resolve_tier(bp, Decimal(99), "block")
    assert tier_range(bp, 0) == "100-249" and tier_range(bp, 4) == "2000+"


def test_better_option_only_when_cheaper():
    assert better_option(Decimal(100), [(500, Decimal(100))]) is None
    best = better_option(Decimal(100), [(500, Decimal(90)), (1000, Decimal(80))])
    assert (best.qty, best.saving) == (1000, 20)
