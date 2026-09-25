"""Decimal money maths, GST and rounding (FR-5, FR-7)."""
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

PAISA = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(PAISA, rounding=ROUND_HALF_UP)


def round_up_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return money(value)
    return money((value / step).to_integral_value(rounding=ROUND_CEILING) * step)


def micro_price(unit_price: Decimal, yield_factor: int) -> Decimal | None:
    if yield_factor <= 1:
        return None
    return money(unit_price / Decimal(yield_factor))


def subtotal(unit_price: Decimal, per_unit_addons: Decimal, billed_qty: Decimal, per_order_addons: Decimal) -> Decimal:
    return money((unit_price + per_unit_addons) * billed_qty + per_order_addons)


@dataclass(frozen=True)
class Totals:
    subtotal: Decimal
    billing_type: str
    gst_rate: Decimal
    gst_amount: Decimal
    grand_total: Decimal


def totals(sub: Decimal, gst_rate: Decimal, billing_type: str) -> Totals:
    gst = money(sub * gst_rate) if billing_type == "gst" else Decimal("0.00")
    return Totals(subtotal=sub, billing_type=billing_type, gst_rate=gst_rate, gst_amount=gst, grand_total=money(sub + gst))
