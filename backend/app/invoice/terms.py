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
    mode: str = "upi"


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


def summary_terms(s: dict, m: Money, advance_pct: Decimal) -> list[list[Run]]:
    """PAYMENT TERMS box of the payment summary: total, advance, the balance if split, then
    received so far and pending (total minus everything received; 0 received when unpaid)."""
    values = {
        "advance_pct": pct(advance_pct),
        "balance_pct": pct(Decimal(100) - Decimal(advance_pct)),
        "payable": fmt.amount(m.payable),
        "advance": fmt.amount(m.advance),
        "balance": fmt.amount(m.balance),
        "received": fmt.amount(m.received),
        "pending": fmt.amount(max(m.payable - m.received, Decimal(0))),
    }
    out = [runs(s["total"], **values), runs(s["advance"], **values)]
    if m.balance > 0:
        out.append(runs(s["balance"], **values))
    out += [runs(s["terms_received"], **values), runs(s["terms_pending"], **values)]
    return out


def summary_receivables(s: dict, m: Money, payments: list[PaymentEntry]) -> list[list[Run]]:
    """RECIEVABLES box: one bulleted line per payment in date order, then the pending line
    (total minus everything received). Empty when nothing has been received."""
    if not payments:
        return []
    out = [
        runs(s["received"], date=fmt.payment_date(p.date).upper(), amount=fmt.amount(p.amount),
             mode=s["modes"].get(p.mode, p.mode.upper()))
        for p in sorted(payments, key=lambda p: p.date)
    ]
    pending = m.payable - m.received
    out.append(runs(s["paid_in_full"]) if pending <= 0 else runs(s["pending"], pending=fmt.amount(pending)))
    return out


def lines(templates: dict, m: Money, advance_pct: Decimal, payments: list[PaymentEntry]) -> list[list[Run]]:
    a = fmt.amount
    common = {
        "advance_pct": pct(advance_pct),
        "balance_pct": pct(Decimal(100) - Decimal(advance_pct)),
        "payable": a(m.payable),
        "advance": a(m.advance),
        "balance": a(m.balance),
    }
    if m.status == "paid":
        # Paid in full: no 80% / 20% breakdown, just the whole amount received.
        last = max(payments, key=lambda p: p.date)
        return [
            runs(templates["total"], **common),
            runs(templates["paid_received"], **common, amount=a(m.received), date=fmt.payment_date(last.date)),
            runs(templates["paid_pending"], **common, pending=a(m.payable - m.received)),
            runs(templates["paid_in_full"], **common),
        ]
    out = [runs(templates["total"], **common), runs(templates["advance"], **common)]
    if m.received > 0:
        for p in sorted(payments, key=lambda p: p.date):
            out.append(runs(templates["received"], **common, amount=a(p.amount), date=fmt.payment_date(p.date)))
        out.append(runs(templates["pending"], **common, applied=a(m.applied), pending=a(m.pending)))
    if m.balance == 0:
        return out  # paid in full before printing: nothing is left for dispatch
    if m.excess > 0:
        out.append(
            runs(templates["balance_after_excess"], **common, excess=a(m.excess), balance_due=a(m.balance_due))
        )
    else:
        out.append(runs(templates["balance"], **common))
    return out
