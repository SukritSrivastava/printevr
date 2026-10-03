"""The payment summary under the items on every Non-GST invoice (config/invoice.yaml payment_summary).

Owner's mock-up, 2026-10-03: a PAYMENT TERMS box (total, advance, balance before dispatch when
split) and, once something is received, a RECIEVABLES box with one line per payment and the
amount still pending (total minus everything received). Filled from the invoice, never typed.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.invoice import terms
from app.invoice.money import compute
from app.invoice.paginate import Box, Dot
from app.invoice.render import compose, render, render_document

from .invoice_helpers import cfg, chars, lines_by_baseline, open_pdf, sogat_doc

MOCKUP_PAYMENTS = [  # entered out of order on purpose
    {"amount": "56000", "date": "2026-09-20", "mode": "upi"},
    {"amount": "30000", "date": "2026-09-10", "mode": "cash"},
]
GST_TAXES = [{"name": "CGST", "rate": "9", "amount": "13320.00"}, {"name": "UGST", "rate": "9", "amount": "13320.00"},
             {"name": "IGST", "rate": "0", "amount": "0.00"}]


def plain(lines) -> list[str]:
    return [terms.plain(line) for line in lines]


def page_lines(data: bytes) -> list[list[str]]:
    with open_pdf(data) as pdf:
        return [["".join(c["text"] for c in line) for line in lines_by_baseline(chars(page))] for page in pdf.pages]


def test_terms_with_a_split():
    m = compute([Decimal("148000")], (), Decimal(80))
    assert plain(terms.summary_terms(cfg().payment_summary, m, Decimal(80))) == [
        "Total Amount:- Rs. 148000/-",
        "80% amount :-  118400/- (Advanced Payment)",
        "20% Amount:- Rs. 29600/- (Before Dispatching the Order)",
    ]


def test_terms_paid_in_full_upfront_has_no_balance_line():
    m = compute([Decimal("148000")], (), Decimal(100))
    assert plain(terms.summary_terms(cfg().payment_summary, m, Decimal(100))) == [
        "Total Amount:- Rs. 148000/-",
        "100% amount :-  148000/- (Advanced Payment)",
    ]


def test_bold_parts_follow_the_mockup():
    m = compute([Decimal("148000")], (), Decimal(80))
    lines = terms.summary_terms(cfg().payment_summary, m, Decimal(80))
    assert [all(bold for _, bold in line) for line in lines] == [True, True, False]


def entries(payments):
    return [terms.PaymentEntry(Decimal(p["amount"]), date.fromisoformat(p["date"]), p["mode"])
            for p in payments]


def test_receivables_list_payments_by_date_and_pending_is_total_minus_received():
    m = compute([Decimal("148000")], (), Decimal(80), [Decimal("56000"), Decimal("30000")])
    assert plain(terms.summary_receivables(cfg().payment_summary, m, entries(MOCKUP_PAYMENTS))) == [
        "10 SEPTEMBER 2026:- 30000/- (VIA CASH)",
        "20 SEPTEMBER 2026:- 56000/- (VIA UPI)",
        "PENDING AMOUNT (TO BE PAID) :- 62000/- (BEFORE DELIVERY)",  # 148000 - 30000 - 56000
    ]


def test_receivables_paid_in_full_and_other_modes():
    m = compute([Decimal("1000")], (), Decimal(100), [Decimal("400"), Decimal("600")])
    paid = entries([{"amount": "400", "date": "2026-10-01", "mode": "bank_transfer"},
                    {"amount": "600", "date": "2026-10-02", "mode": "cheque"}])
    assert plain(terms.summary_receivables(cfg().payment_summary, m, paid)) == [
        "1 OCTOBER 2026:- 400/- (VIA BANK TRANSFER)",
        "2 OCTOBER 2026:- 600/- (VIA CHEQUE)",
        "PENDING AMOUNT (TO BE PAID) :- 0/- (PAID IN FULL)",
    ]


def test_no_receivables_box_before_any_payment():
    m = compute([Decimal("148000")], (), Decimal(80))
    assert terms.summary_receivables(cfg().payment_summary, m, []) == []
    composed = compose(sogat_doc(payments=[], advance_pct="80"), cfg())
    assert sum(isinstance(op, Box) for page in composed.pages for op in page) == 1
    text = " ".join(t for page in page_lines(render(sogat_doc(payments=[], advance_pct="80"), cfg())) for t in page)
    assert "PAYMENT TERMS" in text and "RECIEVABLES" not in text


def test_mockup_invoice_prints_both_boxes_on_one_page():
    doc = sogat_doc(payments=MOCKUP_PAYMENTS, advance_pct="80")
    composed = compose(doc, cfg())
    assert len(composed.pages) == 1
    ops = composed.pages[0]
    boxes = sorted((op for op in ops if isinstance(op, Box)), key=lambda b: b.top)
    assert len(boxes) == 2 and boxes[1].top > boxes[0].bottom  # RECIEVABLES under PAYMENT TERMS
    totals_y = min(op.y for op in ops if getattr(op, "text", "") == "TOTAL:")
    assert boxes[1].bottom < totals_y  # both above the totals
    # Bullets: 3 terms + 2 payments; the pending line has none.
    assert sum(isinstance(op, Dot) and boxes[0].top < op.cy < boxes[1].bottom for op in ops) == 5
    lines = page_lines(render(doc, cfg()))[0]
    for expected in ("PAYMENT TERMS (WITHOUT GST BILLING)", "Total Amount:- Rs. 148000/-",
                     "80% amount :-  118400/- (Advanced Payment)", "20% Amount:- Rs. 29600/- (Before Dispatching the Order)",
                     "RECIEVABLES", "10 SEPTEMBER 2026:- 30000/- (VIA CASH)", "20 SEPTEMBER 2026:- 56000/- (VIA UPI)",
                     "PENDING AMOUNT (TO BE PAID) :- 62000/- (BEFORE DELIVERY)"):
        assert any(" ".join(t.split()) == " ".join(expected.split()) for t in lines), expected


def test_gst_invoice_keeps_the_bastta_layout_without_the_summary():
    """Owner's decision, 2026-10-03: GST invoices stay in the BASTTA layout; the summary is Non-GST only."""
    doc = sogat_doc(series="gst", taxes=GST_TAXES, gst={"buyer": {"name": "Jairpur Jewellers"}},
                    payments=[{"amount": "100000", "date": "2026-09-10", "mode": "upi"}], advance_pct="100")
    text = " ".join(" ".join(t.split()) for page in page_lines(render_document(doc, cfg())) for t in page)
    assert "For BASTTA" in text and "Buyer Info (Billed to)" in text
    for gone in ("PAYMENT TERMS", "RECIEVABLES", "PENDING AMOUNT"):
        assert gone not in text, gone


def test_legacy_with_gst_invoice_summary_uses_the_amount_with_gst():
    """Old Non-GST "With GST billing" records reprint in the Printevr layout: the summary uses P incl. GST."""
    taxes = [{"name": "GST", "rate": "18", "amount": "26640.00"}]
    doc = sogat_doc(billing_type="with_gst", gst_option="gst_18", taxes=taxes, advance_pct="100",
                    payments=[{"amount": "100000", "date": "2026-09-10", "mode": "upi"}])
    text = " ".join(" ".join(t.split()) for page in page_lines(render(doc, cfg())) for t in page)
    for expected in ("PAYMENT TERMS (WITH GST BILLING)", "Total Amount:- Rs. 174640/-",
                     "PENDING AMOUNT (TO BE PAID) :- 74640/- (BEFORE DELIVERY)"):
        assert expected in text, expected


@pytest.mark.parametrize("payments", [1, 6])
def test_many_payments_never_overlap_the_totals(payments):
    many = [{"amount": "1000", "date": f"2026-09-{d + 1:02d}", "mode": "cash"} for d in range(payments)]
    composed = compose(sogat_doc(payments=many, advance_pct="80"), cfg())
    last = composed.pages[-1]
    boxes = [op for op in last if isinstance(op, Box)]
    totals_y = min(op.y for op in last if getattr(op, "text", "") == "TOTAL:")
    assert len(boxes) == 2 and max(b.bottom for b in boxes) < totals_y
