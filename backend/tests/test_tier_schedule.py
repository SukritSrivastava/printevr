"""BRD-tier-slider-back-nav section 11, API tests A1-A5 (A6 is test_calculate_snapshot.py)."""
from decimal import Decimal

import pytest

from app.pricing import tiers as tierlib
from app.pricing import totals as totlib

from .conftest import RIGID_TB

STICKER_PAPER = "sticker_sheets/paper"
OUTDOOR_STAR = "outdoor_branding/flex-printing-star"


def sched(result):
    return result["data"]["tier_schedule"]


def by_from(schedule):
    return {t["qty_from"]: t for t in schedule["tiers"]}


def test_a1_every_breakpoint_in_order(quote, catalogue):
    s = sched(quote(item_id=RIGID_TB, quantity=350))
    assert [t["qty_from"] for t in s["tiers"]] == catalogue.item(RIGID_TB).breakpoints
    t = by_from(s)
    assert t[250] == {"qty_from": 250, "qty_to": 499, "unit_price": "75.00", "overpay_from": 367}
    assert t[500]["unit_price"] == "55.00"
    assert t[2000]["unit_price"] == "40.00" and t[2000]["qty_to"] is None and t[2000]["overpay_from"] is None
    # qty_to is the next tier's qty_from - 1.
    for a, b in zip(s["tiers"], s["tiers"][1:]):
        assert a["qty_to"] == b["qty_from"] - 1


def test_a1_worked_check(quote):
    """366 x 75 = 27,450 is still cheaper than 500 x 55 = 27,500; 367 x 75 = 27,525 is not."""
    assert quote(item_id=RIGID_TB, quantity=366)["data"]["pricing"]["better_option"] is None
    assert quote(item_id=RIGID_TB, quantity=367)["data"]["pricing"]["better_option"] == {
        "qty": 500,
        "subtotal": "27500.00",
        "saving": "25.00",
    }
    assert quote(item_id=RIGID_TB, quantity=450)["data"]["pricing"]["better_option"]["saving"] == "6250.00"


def test_a2_slider_end_and_minimum(quote):
    s = sched(quote(item_id=RIGID_TB, quantity=350))
    assert s["slider_max"] == 4000 and s["min_qty"] == 100
    assert s["sale_unit"] == "box" and s["below_min_policy"] == "bill_at_min" and s["max_qty"] is None
    assert s["suggest_more"] is True


def test_a3_custom_size_prices_every_tier(quote):
    s = sched(
        quote(
            product_id="rigid_boxes",
            options={"option_1": "Top-Bottom"},
            custom_dimensions={"length": 3.5, "width": 3.5, "height": 2},
            quantity=300,
        )
    )
    t = by_from(s)
    assert t[250]["unit_price"] == "88.50" and t[500]["unit_price"] == "68.50"


def test_a4_max_qty_products_end_at_max_qty(quote):
    for qty in (250, 1200):  # a priced quantity, and a manual quote above max_qty
        s = sched(quote(item_id=STICKER_PAPER, quantity=qty))
        assert s["max_qty"] == 1000 and s["slider_max"] == 1000
        assert s["tiers"][-1]["qty_to"] == 1000


def test_a5_outdoor_has_no_overpay_zone(quote):
    s = sched(quote(item_id=OUTDOOR_STAR, quantity=240))
    assert s["suggest_more"] is False
    assert all(t["overpay_from"] is None for t in s["tiers"])


def test_unit_price_includes_per_unit_addons_and_zone_counts_per_order(quote):
    item = "vc_standard/300-gsm/none/single-side"
    plain = by_from(sched(quote(item_id=item, quantity=600)))
    edged = by_from(sched(quote(item_id=item, quantity=600, addons=["round_edges"])))
    for q, t in plain.items():
        assert Decimal(edged[q]["unit_price"]) == Decimal(t["unit_price"]) + 1


@pytest.mark.parametrize("addons", [[], "all"])
def test_overpay_zone_matches_better_option_for_every_item(quote, catalogue, addons):
    """The zone starts exactly where the receipt starts offering a cheaper higher breakpoint."""
    checked = 0
    for item in catalogue.items.values():
        product = catalogue.products[item.product_id]
        if not product.active:
            continue
        wanted = [a.id for a in product.addons if not a.from_sheet or item.sample_charge is not None] if addons else []
        s = sched(quote(item_id=item.id, quantity=item.breakpoints[0], addons=wanted))
        for t in s["tiers"][:-1]:
            zone = t["overpay_from"]
            edges = [t["qty_from"], t["qty_to"]] + ([zone - 1, zone] if zone else [])
            for q in {e for e in edges if t["qty_from"] <= e <= t["qty_to"]}:
                if product.max_qty is not None and q > product.max_qty:
                    continue
                better = quote(item_id=item.id, quantity=q, addons=wanted)["data"]["pricing"]["better_option"]
                assert (better is not None) == (zone is not None and q >= zone), (item.id, q, zone, better)
                checked += 1
    assert checked > 500


def test_schedule_is_pure_and_handles_rounding_edges():
    per_order = Decimal("500")

    def subtotal_at(u, q):
        return totlib.subtotal(u, Decimal(0), q, per_order)

    spans = tierlib.schedule(
        [100, 250, 500], [Decimal("10.33"), Decimal("7.5"), Decimal("5")], subtotal_at, suggest_more=True, max_qty=None
    )
    best = min(subtotal_at(Decimal("7.5"), Decimal(250)), subtotal_at(Decimal("5"), Decimal(500)))
    edge = spans[0].overpay_from
    assert subtotal_at(Decimal("10.33"), Decimal(edge)) > best >= subtotal_at(Decimal("10.33"), Decimal(edge - 1))
    assert [s.qty_to for s in spans] == [249, 499, None]
    assert tierlib.schedule([1, 10], [Decimal(5), Decimal(4)], subtotal_at, suggest_more=False, max_qty=20)[0].overpay_from is None
    # A zone that would start past the tier's end is no zone.
    assert tierlib.schedule([1, 10], [Decimal(5), Decimal(1)], subtotal_at, suggest_more=True, max_qty=20)[0].overpay_from == 3
    assert tierlib.schedule([1, 10], [Decimal(5), Decimal(5)], subtotal_at, suggest_more=True, max_qty=20)[0].overpay_from is None


def test_slider_multiplier_comes_from_config(rebuild, sheet, quote):
    _, _, config = sheet
    changed = {**config, "defaults": {**config["defaults"], "slider_max_multiplier": 1.5}}
    cat = rebuild(config=changed)
    assert sched(quote(cat, item_id=RIGID_TB, quantity=350))["slider_max"] == 3000
    from app.loader import LoaderError

    with pytest.raises(LoaderError, match="slider_max_multiplier"):
        rebuild(config={**config, "defaults": {**config["defaults"], "slider_max_multiplier": 0.5}})
