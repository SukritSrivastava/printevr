"""BRD-cart-invoice 6.5 (P1-P8) and 11.2 (F1-F3): money rules, formats and payment-terms lines."""
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.invoice import config as invoice_config
from app.invoice import fmt, terms
from app.invoice.money import Overpaid, compute, line_subtotal
from app.settings import get_settings

FIXTURE = Path(__file__).parent / "fixtures" / "invoice" / "sogat_jutti_bill18.json"
D = Decimal


@pytest.fixture(scope="module")
def cfg():
    return invoice_config.load(get_settings().invoice_config_file)


@pytest.fixture(scope="module")
def sogat():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def sogat_subtotals(fixture):
    return [line_subtotal(D(str(l["quantity"])), D(l["unit_price"])) for l in fixture["lines"]]


def run(cfg, subtotals, billing="without_gst", payments=()):
    entries = [terms.PaymentEntry(D(a), date.fromisoformat(d)) for a, d in payments]
    # With GST billing is legacy now: the old 18% option, as saved on old invoices.
    components = next(o for o in cfg.legacy_gst_options if o.key == "gst_18").components if billing == "with_gst" else ()
    m = compute(subtotals, components, cfg.advance_pct, [p.amount for p in entries])
    return m, terms.lines(cfg.payment_terms, m, cfg.advance_pct, entries)


def texts(lines):
    return [terms.plain(line) for line in lines]


def test_p1_sogat_jutti_part_payment(cfg, sogat):
    m, lines = run(cfg, sogat_subtotals(sogat), payments=[("30000", "2026-09-09")])
    exp = sogat["expected"]
    assert (m.total, m.payable, m.advance, m.balance) == (D(exp["total"]), D(exp["payable"]), D("118400"), D("29600"))
    assert (m.applied, m.pending, m.status) == (D("30000"), D("88400"), "part_paid")
    assert texts(lines) == exp["payment_lines"]
    # Bold runs exactly as marked in 6.4
    assert [[t for t, b in line if b] for line in lines] == [
        ["Total Amount:- Rs. 148000/-"],
        ["80% amount pending (before printing & after sample & final confirmation):-  118400/-"],
        [],
        ["88400/-"],
        [],
    ]


def test_p2_unpaid_shows_lines_1_2_5a(cfg, sogat):
    m, lines = run(cfg, sogat_subtotals(sogat))
    assert m.status == "unpaid"
    assert texts(lines) == [
        "Total Amount:- Rs. 148000/-",
        "80% amount pending (before printing & after sample & final confirmation):-  118400/-",
        "20% Amount:- Rs. 29600/- (Before Dispatching the Order)",
    ]


def test_p3_paid_in_full(cfg, sogat):
    """Paid in full drops the 80% / 20% breakdown and shows the whole amount as received."""
    m, lines = run(cfg, sogat_subtotals(sogat), payments=[("148000", "2026-09-09")])
    assert m.status == "paid"
    assert texts(lines) == [
        "Total Amount:- Rs. 148000/-",
        "Received Amount (100%):- Rs. 148000/- (9 September 2026)",
        "Amount Pending:- Rs. 0/-",
        "Payment Status:- PAID IN FULL",
    ]
    assert [[t for t, b in line if b] for line in lines] == [
        ["Total Amount:- Rs. 148000/-"],
        [],
        ["Rs. 0/-"],
        ["Payment Status:- PAID IN FULL"],
    ]


def test_p3b_paid_in_full_in_parts_and_with_gst(cfg, sogat):
    # Two payments that add up to the total: the date is the one that completed it.
    _, lines = run(cfg, sogat_subtotals(sogat), payments=[("48000", "2026-09-12"), ("100000", "2026-09-09")])
    assert texts(lines)[1] == "Received Amount (100%):- Rs. 148000/- (12 September 2026)"
    m, lines = run(cfg, sogat_subtotals(sogat), billing="with_gst", payments=[("174640", "2026-10-01")])
    assert m.status == "paid"
    assert texts(lines) == [
        "Total Amount:- Rs. 174640/-",
        "Received Amount (100%):- Rs. 174640/- (1 October 2026)",
        "Amount Pending:- Rs. 0/-",
        "Payment Status:- PAID IN FULL",
    ]


def test_p4_payment_above_advance(cfg, sogat):
    m, lines = run(cfg, sogat_subtotals(sogat), payments=[("130000", "2026-09-09")])
    t = texts(lines)
    assert m.status == "part_paid" and m.pending == 0
    assert t[3] == "Amount Pending (out of 80%) :- 118400/-  (-)  118400/-  =  0/-"
    assert t[4] == "20% Amount:- Rs. 29600/-  (-)  11600/-  =  18000/- (Before Dispatching the Order)"
    assert len(t) == 5


def test_p5_two_payments_in_date_order(cfg, sogat):
    _, lines = run(cfg, sogat_subtotals(sogat), payments=[("20000", "2026-09-12"), ("30000", "2026-09-09")])
    t = texts(lines)
    assert t[2] == "Recieved Amount:- Rs. 30000/- (9 September 2026)"
    assert t[3] == "Recieved Amount:- Rs. 20000/- (12 September 2026)"
    assert t[4] == "Amount Pending (out of 80%) :- 118400/-  (-)  50000/-  =  68400/-"


def test_p6_with_gst(cfg, sogat):
    m, lines = run(cfg, sogat_subtotals(sogat), billing="with_gst")
    assert (m.gst, m.payable, m.advance, m.balance) == (D("26640"), D("174640"), D("139712"), D("34928"))
    assert terms.title(cfg.payment_terms, "with_gst") == "PAYMENT TERMS     (WITH GST BILLING)"
    assert terms.title(cfg.payment_terms, "without_gst") == "PAYMENT TERMS     (WITHOUT GST BILLING)"
    assert texts(lines)[0] == "Total Amount:- Rs. 174640/-"


def test_p7_overpaid_is_refused(cfg, sogat):
    with pytest.raises(Overpaid):
        run(cfg, sogat_subtotals(sogat), payments=[("150000", "2026-09-09")])


def test_p8_paise(cfg):
    m, lines = run(cfg, [line_subtotal(D(1), D("88.50"))])
    assert (m.total, m.advance, m.balance) == (D("88.50"), D("70.80"), D("17.70"))
    assert texts(lines)[0] == "Total Amount:- Rs. 88.50/-"


def test_f1_amount_formats():
    assert fmt.amount(148000) == "148000"
    assert fmt.amount(Decimal("88.5")) == "88.50"
    assert fmt.unit_price(8) == "08"
    assert fmt.unit_price(140) == "140"
    assert fmt.unit_price(Decimal("5.5")) == "5.50"
    assert fmt.quantity(1000) == "1000"


def test_f2_dates():
    assert fmt.invoice_date(date(2026, 9, 14)) == "14 SEP , 2026"
    assert fmt.invoice_date(date(2026, 9, 9)) == "9 SEP , 2026"
    assert fmt.payment_date(date(2026, 9, 9)) == "9 September 2026"


def test_f3_filename(cfg):
    name = fmt.filename(cfg.filename, 18, "Sogat Jutti Store!", cfg.status_labels["part_paid"])
    assert name == "Invoice_18_Sogat-Jutti-Store.pdf"  # no payment status in the name (config)
    name = fmt.filename("Invoice_{bill_no}_{business}_{status}.pdf", 18, "Sogat Jutti Store!", cfg.status_labels["part_paid"])
    assert name == "Invoice_18_Sogat-Jutti-Store_Part-paid.pdf"
