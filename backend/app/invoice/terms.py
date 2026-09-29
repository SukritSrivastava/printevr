"""Payment-terms lines (BRD-cart-invoice 6.4) as runs of (text, bold). Pure."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from . import fmt
from .money import Money

Run = tuple[str, bool]


@dataclass(frozen=True)
class PaymentEntry:
    amount: Decimal
    date: date


def runs(template: str, **values) -> list[Run]:
    """Fill a template and split it on ** markers: '**a** b' -> [('a', True), (' b', False)]."""
    text = template.format(**values)
    parts = text.split("**")
    return [(part, i % 2 == 1) for i, part in enumerate(parts) if part]


def plain(line: list[Run]) -> str:
    return "".join(text for text, _ in line)


def pct(value: Decimal) -> str:
    d = Decimal(value)
    return str(int(d)) if d == d.to_integral_value() else format(d.normalize(), "f")


def title(templates: dict, billing_type: str) -> str:
    return templates["title"].format(billing_label=templates["billing_labels"][billing_type])


def lines(templates: dict, m: Money, advance_pct: Decimal, payments: list[PaymentEntry]) -> list[list[Run]]:
    a = fmt.amount
    common = {
        "advance_pct": pct(advance_pct),
        "balance_pct": pct(Decimal(100) - Decimal(advance_pct)),
        "payable": a(m.payable),
        "advance": a(m.advance),
        "balance": a(m.balance),
    }
    out = [runs(templates["total"], **common), runs(templates["advance"], **common)]
    if m.received > 0:
        for p in sorted(payments, key=lambda p: p.date):
            out.append(runs(templates["received"], **common, amount=a(p.amount), date=fmt.payment_date(p.date)))
        out.append(runs(templates["pending"], **common, applied=a(m.applied), pending=a(m.pending)))
    if m.excess > 0:
        out.append(
            runs(templates["balance_after_excess"], **common, excess=a(m.excess), balance_due=a(m.balance_due))
        )
    else:
        out.append(runs(templates["balance"], **common))
    if m.status == "paid":
        out.append(runs(templates["paid_in_full"], **common))
    return out
