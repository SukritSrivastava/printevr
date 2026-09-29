"""Number, date and file-name formats for the invoice PDF (BRD-cart-invoice 6.3). Pure.

The PDF uses Printevr's plain style (148000, 88.50); the web UI keeps its en-IN format.
"""
import re
from datetime import date
from decimal import Decimal

from .money import money

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _whole(value: Decimal) -> bool:
    return value == value.to_integral_value()


def amount(value) -> str:
    """Whole rupees as digits only; otherwise two decimals. 148000 · 88.50"""
    d = money(Decimal(str(value)))
    return str(int(d)) if _whole(d) else format(d, "f")


def unit_price(value, pad_single_digit: bool = True) -> str:
    """Like amount(), but a whole amount below 10 gets a leading zero: 08 · 140 · 5.50"""
    d = money(Decimal(str(value)))
    if _whole(d):
        n = int(d)
        return f"{n:02d}" if pad_single_digit and 0 <= n < 10 else str(n)
    return format(d, "f")


def quantity(value) -> str:
    """Integer digits, no separators. Square feet can carry decimals (12.5)."""
    d = Decimal(str(value))
    return str(int(d)) if _whole(d) else format(d.normalize(), "f")


def invoice_date(d: date) -> str:
    """14 SEP , 2026"""
    return f"{d.day} {MONTHS[d.month - 1][:3].upper()} , {d.year}"


def payment_date(d: date) -> str:
    """9 September 2026"""
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def caps(text: str | None) -> str:
    return (text or "").upper()


def filename(template: str, bill_no: int, business_name: str, status_label: str) -> str:
    """Invoice_18_Sogat-Jutti-Store_Part-paid.pdf: only letters, digits and hyphens in the business part."""
    business = re.sub(r"[^A-Za-z0-9]+", "-", business_name).strip("-") or "Customer"
    return template.format(bill_no=bill_no, business=business, status=status_label)
