"""Invoice money rules (BRD-cart-invoice 6.1-6.2). Pure: Decimal in, Decimal out, no I/O."""
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from .gst import GstComponent, TaxAmount, tax_amounts

PAISA = Decimal("0.01")
ZERO = Decimal("0.00")


class Overpaid(Exception):
    def __init__(self, received: Decimal, payable: Decimal):
        super().__init__(f"Received {received} is more than the payable {payable}")
        self.received = received
        self.payable = payable


def money(value: Decimal) -> Decimal:
    return Decimal(value).quantize(PAISA, rounding=ROUND_HALF_UP)


def line_subtotal(quantity: Decimal, unit_price: Decimal) -> Decimal:
    return money(Decimal(quantity) * Decimal(unit_price))


@dataclass(frozen=True)
class Money:
    total: Decimal  # T
    gst: Decimal  # G: sum of the tax rows
    payable: Decimal  # P
    advance: Decimal  # A
    balance: Decimal  # B
    received: Decimal  # R
    applied: Decimal
    pending: Decimal
    excess: Decimal
    balance_due: Decimal
    status: str  # unpaid | part_paid | paid
    taxes: tuple[TaxAmount, ...] = ()  # one per GST component; empty without GST billing


def status_for(received: Decimal, payable: Decimal) -> str:
    if received > payable:
        raise Overpaid(received, payable)
    if received <= 0:
        return "unpaid"
    return "paid" if received == payable else "part_paid"


def compute(
    subtotals: Iterable[Decimal],
    gst_components: Iterable[GstComponent],
    advance_pct: Decimal,
    payments: Iterable[Decimal] = (),
) -> Money:
    """Totals for one invoice. `gst_components` is empty for Without GST billing.

    Raises Overpaid when payments exceed the payable amount.
    """
    total = money(sum((Decimal(s) for s in subtotals), ZERO))
    taxes = tax_amounts(total, gst_components)
    gst = money(sum((t.amount for t in taxes), ZERO))
    payable = money(total + gst)
    advance = money(payable * Decimal(advance_pct) / 100)
    balance = money(payable - advance)
    received = money(sum((Decimal(p) for p in payments), ZERO))
    applied = min(received, advance)
    excess = max(received - advance, ZERO)
    return Money(
        total=total,
        gst=gst,
        payable=payable,
        advance=advance,
        balance=balance,
        received=received,
        applied=applied,
        pending=money(advance - applied),
        excess=money(excess),
        balance_due=money(balance - excess),
        status=status_for(received, payable),
        taxes=taxes,
    )
