"""FR-5 and FR-7: Decimal maths and GST."""
from decimal import Decimal

from app.pricing.totals import micro_price, money, round_up_to_step, subtotal, totals


def test_money_rounds_half_up():
    assert money(Decimal("1.005")) == Decimal("1.01")
    assert money(Decimal("1.004")) == Decimal("1.00")


def test_micro_price():
    assert micro_price(Decimal(2399), 180) == Decimal("13.33")
    assert micro_price(Decimal(3099), 90) == Decimal("34.43")
    assert micro_price(Decimal(3099), 2000) == Decimal("1.55")
    assert micro_price(Decimal(75), 1) is None


def test_subtotal_and_gst():
    sub = subtotal(Decimal(2399), Decimal(0), Decimal(3), Decimal(0))
    t = totals(sub, Decimal("0.18"), "gst")
    assert (t.subtotal, t.gst_amount, t.grand_total) == (Decimal("7197.00"), Decimal("1295.46"), Decimal("8492.46"))
    t = totals(sub, Decimal("0.18"), "invoice")
    assert (t.gst_amount, t.grand_total) == (Decimal("0.00"), Decimal("7197.00"))


def test_per_unit_and_per_order_addons():
    assert subtotal(Decimal(5), Decimal(1), Decimal(1200), Decimal(0)) == Decimal("7200.00")
    assert subtotal(Decimal("5.5"), Decimal(0), Decimal(1500), Decimal(1000)) == Decimal("9250.00")


def test_round_up_to_step():
    assert round_up_to_step(Decimal("88.125"), Decimal("0.50")) == Decimal("88.50")
    assert round_up_to_step(Decimal("130"), Decimal("0.50")) == Decimal("130.00")
    assert round_up_to_step(Decimal("88.01"), Decimal("0.50")) == Decimal("88.50")
