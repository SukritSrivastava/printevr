"""C1-C6 (FR-4) and success criterion 2."""
from decimal import Decimal

from app.dims import DIM_NAMES
from app.pricing.custom import PoolSize, price_custom

from .conftest import codes


def rigid(quote, l, w, h, qty, box_type="Top-Bottom", unit="in", **kw):
    return quote(
        product_id="rigid_boxes",
        options={"option_1": box_type},
        custom_dimensions={"length": l, "width": w, "height": h, "unit": unit},
        quantity=qty,
        **kw,
    )


def test_c1_interpolation(quote):
    r = rigid(quote, 3.5, 3.5, 2, 300)
    d = r["data"]
    assert d["product"]["description"] == "Top-Bottom, custom 3.5 × 3.5 × 2 in"
    ce = d["pricing"]["custom_estimate"]
    assert ce["metric"] == "52.50" and ce["metric_unit"] == "sq in"
    assert ce["anchors"] == [
        {"size": "3 × 3 × 2 in", "metric": "42.00", "unit_price": "75.00"},
        {"size": "5 × 3 × 2 in", "metric": "62.00", "unit_price": "100.00"},
    ]
    assert ce["raw_unit_price"] == "88.125" and ce["round_step"] == "0.50" and ce["surcharge_pct"] == "0"
    assert d["pricing"]["tier_applied"]["qty_from"] == 250
    assert d["pricing"]["unit_price"] == "88.50"
    assert d["totals"] == {
        "subtotal": "26550.00",
        "billing_type": "gst",
        "gst_rate_percent": "18",
        "gst_amount": "4779.00",
        "grand_total": "31329.00",
    }
    assert d["pricing"]["next_tier"] == {"qty_from": 500, "units_to_next": 200, "unit_price": "68.50"}
    assert d["pricing"]["better_option"] is None
    assert codes(r) == ["CUSTOM_ESTIMATE"]


def test_c2_floor(quote):
    d = rigid(quote, 2, 2, 1, 100)["data"]
    ce = d["pricing"]["custom_estimate"]
    assert ce["metric"] == "16.00" and ce["method"] == "floor"
    assert ce["anchors"][0]["size"] == "3 × 3 × 2 in"
    assert d["pricing"]["unit_price"] == "105.00" and d["totals"]["subtotal"] == "10500.00"


def test_c3_equal_anchor_prices(quote):
    d = rigid(quote, 6.5, 6.5, 2, 450)["data"]
    ce = d["pricing"]["custom_estimate"]
    assert ce["metric"] == "136.50"
    assert [a["size"] for a in ce["anchors"]] == ["7 × 5 × 2 in", "7 × 7 × 2 in"]
    assert d["pricing"]["unit_price"] == "130.00"
    t = d["totals"]
    assert (t["subtotal"], t["gst_amount"], t["grand_total"]) == ("58500.00", "10530.00", "69030.00")


def test_c4_out_of_range(quote):
    r = rigid(quote, 20, 20, 5, 500)
    assert r["status"] == "manual_quote" and r["reason"] == "CUSTOM_OUT_OF_RANGE"
    assert "1200.00" in r["message"] and "768.00" in r["message"]


def test_c5_carry_bag_pools_small_medium_large(quote):
    r = quote(product_id="carry_bags_medium", custom_dimensions={"height": 10, "length": 10, "side": 3}, quantity=600)
    d = r["data"]
    ce = d["pricing"]["custom_estimate"]
    assert ce["metric"] == "290.00"
    assert [(a["size"], a["metric"], a["unit_price"]) for a in ce["anchors"]] == [
        ("9.5 × 8 × 3 in (H × L × S)", "233.00", "36.00"),
        ("11 × 8 × 4 in (H × L × S)", "296.00", "36.00"),
    ]
    assert d["pricing"]["tier_applied"]["qty_from"] == 500
    assert d["pricing"]["unit_price"] == "36.00"
    t = d["totals"]
    assert (t["subtotal"], t["gst_amount"], t["grand_total"]) == ("21600.00", "3888.00", "25488.00")


def test_c6_rotated_standard_box_is_the_standard_item(quote):
    r = rigid(quote, 3, 2, 3, 350)
    d = r["data"]
    assert d["product"]["item_id"] == "rigid_boxes/3x3x2-in/top-bottom"
    assert d["pricing"]["unit_price"] == "75.00" and d["pricing"]["custom_estimate"] is None
    assert "CUSTOM_ESTIMATE" not in codes(r)


def test_bag_dimensions_are_not_rotated(quote):
    # 3 × 10 × 7 is not the standard 10 × 7 × 3 bag: H, L, S are compared exactly.
    r = quote(product_id="carry_bags_small", custom_dimensions={"height": 3, "length": 10, "side": 7}, quantity=500)
    assert r["data"]["pricing"]["custom_estimate"] is not None


def test_centimetres_are_converted(quote):
    d = rigid(quote, 8.89, 8.89, 5.08, 300, unit="cm")["data"]
    assert d["pricing"]["unit_price"] == "88.50"


def test_flagged_anchor_warning_is_inherited(quote):
    # 7 × 5 × 2 Magnetic/Slider at 100 is F4; a custom size just above it uses that price.
    r = rigid(quote, 7.2, 5, 2, 100, box_type="Magnetic / Slider")
    warning = next(w for w in r["data"]["warnings"] if w["code"] == "PRICE_UNDER_REVIEW")
    assert "F4" in warning["flags"]


def test_custom_never_below_smallest_standard_price(catalogue, quote):
    """Success criterion 2, for every custom-size product, option and tier."""
    for product in (p for p in catalogue.products.values() if p.supports_custom):
        names = DIM_NAMES[product.custom_dims]
        option_sets = {tuple((k, i.option(k)) for k in product.anchor_match) for i in product.items}
        for option_set in option_sets:
            options = dict(option_set)
            pool = catalogue.anchor_pool(product, options)
            smallest = min(i.metric for i in pool)
            for idx, qty_from in enumerate(pool[0].breakpoints):
                floor = max(i.tiers[idx].price for i in pool if i.metric == smallest)
                for size in (Decimal("0.5"), Decimal("1.25")):
                    r = quote(
                        product_id=product.id,
                        options=options,
                        custom_dimensions={n: size for n in names},
                        quantity=qty_from,
                    )
                    assert Decimal(r["data"]["pricing"]["unit_price"]) >= floor, (product.id, options, qty_from)


def test_rounding_up_and_surcharge():
    pool = [PoolSize("a", Decimal(10), Decimal(10), ()), PoolSize("b", Decimal(20), Decimal(20), ())]
    assert price_custom(pool, Decimal("10.1"), Decimal(0), Decimal("0.50")).unit_price == Decimal("10.50")
    assert price_custom(pool, Decimal(15), Decimal(10), Decimal("0.50")).unit_price == Decimal("16.50")
    assert price_custom(pool, Decimal(15), Decimal(12), Decimal("0.50")).unit_price == Decimal("17.00")
    assert price_custom(pool, Decimal(15), Decimal(0), Decimal("0.50")).unit_price == Decimal("15.00")


def test_duplicate_metric_uses_highest_price():
    pool = [
        PoolSize("a", Decimal(10), Decimal(10), ()),
        PoolSize("a2", Decimal(10), Decimal(12), ("F7",)),
        PoolSize("b", Decimal(20), Decimal(20), ()),
    ]
    cp = price_custom(pool, Decimal(5), Decimal(0), Decimal("0.50"))
    assert cp.unit_price == Decimal("12.00") and cp.flags == ("F7",)
