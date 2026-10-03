"""print_payment_details: false (config/invoice.yaml).

The owner's decision of 2026-10-03. The GST (BASTTA) invoice drops the Payment Terms field, the
bank details and the late-payment term. The Non-GST invoice drops the footer's two payment notes
and, with the payment summary removed (the shipped config prints it: test_payment_summary.py),
the payment-terms box too. Everything else stays where the golden tests (run with the reference's
box, test_invoice_golden.py) put it.
"""
import dataclasses
import json

import pytest

from app.invoice import layout as L
from app.invoice.paginate import Box
from app.invoice.render import compose, render, render_document

from .invoice_helpers import FIXTURES, chars, find_run, full_cfg, lines_by_baseline, open_pdf, sogat_doc, sogat_raw
from .invoice_helpers import cfg as yaml_cfg


def cfg():
    """The shipped config without its payment summary: no payment details at all."""
    return dataclasses.replace(yaml_cfg(), payment_summary=None)


REFERENCE = json.loads((FIXTURES / "layout_reference.json").read_text(encoding="utf-8"))
PAYMENT_WORDS = ("PAYMENT", "Payment", "payment", "Recieved", "Received", "Pending", "pending", "Advance", "ADVANCE",
                 "UPI", "Late payment", "Dispatching", "PAID IN FULL")
REMOVED_NOTES = {cfg().footer["advance_note"], cfg().footer["late_note"]}
PAYMENTS = [
    {"amount": "30000", "date": "2026-09-10", "mode": "cash"},
    {"amount": "56000", "date": "2026-09-20", "mode": "upi"},
]


def page_text(data: bytes) -> list[str]:
    with open_pdf(data) as pdf:
        return ["".join(c["text"] for c in line) for page in pdf.pages for line in lines_by_baseline(chars(page))]


def test_the_default_config_prints_the_summary_not_the_reference_box():
    assert yaml_cfg().print_payment_details is False and yaml_cfg().payment_summary is not None
    assert cfg().payment_summary is None
    assert full_cfg().print_payment_details is True and full_cfg().payment_summary is None


@pytest.mark.parametrize("payments", [[], PAYMENTS[:1], PAYMENTS], ids=["unpaid", "one payment", "two payments"])
def test_non_gst_invoice_has_no_payment_details(payments):
    data = render(sogat_doc(payments=payments), cfg())
    joined = " ".join(page_text(data))
    for word in PAYMENT_WORDS:
        assert word not in joined, word
    composed = compose(sogat_doc(payments=payments), cfg())
    assert not any(isinstance(op, Box) for page in composed.pages for op in page)  # no payment box
    with open_pdf(data) as pdf:
        assert len(pdf.pages[0].images) == 2  # the band and the logo: no QR code either


def test_print_unpaid_and_print_paid_look_the_same():
    """Nothing printed depends on payments any more, so both buttons give the same page."""
    unpaid = render(sogat_doc(payments=[]), cfg())
    assert render(sogat_doc(payments=PAYMENTS), cfg()) == unpaid
    paid = [{"amount": "148000", "date": "2026-09-20", "mode": "bank_transfer"}]
    assert render(sogat_doc(payments=paid), cfg()) == unpaid


def test_everything_else_stays_where_the_reference_has_it():
    """G2 without the payment details: every fixed run except the two payment notes."""
    with open_pdf(render(sogat_doc(), cfg())) as pdf:
        cs = chars(pdf.pages[0])
    checked, missing = 0, []
    for run in REFERENCE["text"]:
        if run["text"] == "INVOICE" or 280.0 <= run["baseline"] <= 690.0 or run["text"] in REMOVED_NOTES:
            continue
        checked += 1
        if find_run(cs, run["text"], run["font"], run["size"], run["x0"], run["baseline"]) is None:
            missing.append(run)
    assert checked > 30 and missing == []
    for note in REMOVED_NOTES:
        assert note not in " ".join("".join(c["text"] for c in line) for line in lines_by_baseline(cs))


def test_totals_sub_total_pill_and_saving_stay():
    data = render(sogat_doc(saving_amount="2500"), cfg())
    with open_pdf(data) as pdf:
        cs = chars(pdf.pages[0])
    assert find_run(cs, "TOTAL:", L.BOLD_PS, 12.70, 434.48, 703.89, y_tol=0.05)
    assert find_run(cs, "148000", L.REGULAR_PS, 12.70, 490.65, 703.80, y_tol=0.05)
    sub = [l for l in lines_by_baseline(cs) if abs(l[0]["baseline"] - 733.72) < 0.3 and l[0]["size"] < 15]
    assert "".join(c["text"] for c in sub[0]) == "148000"  # SUB TOTAL = TOTAL without GST
    text = page_text(data)
    assert "SUB TOTAL :" in "".join(text)
    # Savings, bottom left, from the amount staff typed in (it was never calculated).
    assert find_run(cs, "TOTAL", L.REGULAR_PS, L.SAVING_SIZE, L.SAVING_X, L.SAVING_LINES_Y[0], y_tol=0.1)
    assert "TOTAL SAVING YOU DID FROM GETTING" in text and "YOUR PRINTING DONE FROM PRINTEVR IS" in text
    ax, ay, afont, asize = L.SAVING_AMOUNT
    assert find_run(cs, "2500", L.BOLD_PS, asize, ax, ay, y_tol=0.1) and "APPROX" in text


def test_legacy_with_gst_sub_total_is_gst_inclusive():
    taxes = [{"name": "GST", "rate": "18", "amount": "26640.00"}]
    data = render(sogat_doc(billing_type="with_gst", gst_option="gst_18", taxes=taxes, payments=[]), cfg())
    with open_pdf(data) as pdf:
        cs = chars(pdf.pages[0])
    sub = [l for l in lines_by_baseline(cs) if abs(l[0]["baseline"] - 733.72) < 0.3 and l[0]["size"] < 15]
    assert "".join(c["text"] for c in sub[0]) == "174640"
    assert "PAYMENT TERMS" not in " ".join(page_text(data))


def _many_lines(n):
    base = sogat_raw()["lines"][1]
    return [dict(base, title=f"Customised test article {i + 1} printing") for i in range(n)]


@pytest.mark.parametrize("n", range(1, 9))
def test_leaving_the_box_off_never_adds_a_page(n):
    doc = sogat_doc(lines=_many_lines(n), payments=[{"amount": "1000", "date": "2026-09-10"}])
    assert len(compose(doc, cfg()).pages) <= len(compose(doc, full_cfg()).pages)


def test_long_invoice_puts_the_totals_on_the_last_page_only():
    doc = sogat_doc(lines=_many_lines(12))
    pages = compose(doc, cfg()).pages
    assert len(pages) > 1
    with open_pdf(render(doc, cfg())) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            joined = "".join("".join(c["text"] for c in l) for l in lines_by_baseline(chars(page)))
            assert ("SUB TOTAL :" in joined) == (number == len(pages))


def _gst_doc(payments=()):
    return sogat_doc(
        series="gst", taxes=[{"name": "CGST", "rate": "9", "amount": "13320.00"}, {"name": "UGST", "rate": "9", "amount": "13320.00"},
                             {"name": "IGST", "rate": "0", "amount": "0.00"}],
        gst={"buyer": {"name": "Jairpur Jewellers", "address": "SCO 12, Sector 17"}, "payment_terms": "Advance",
             "transport": "Self", "station": "Chandigarh"},
        payments=list(payments),
    )


@pytest.mark.parametrize("payments", [[], PAYMENTS])
def test_gst_invoice_has_no_payment_details(payments):
    data = render_document(_gst_doc(payments), cfg())
    joined = " ".join(page_text(data))
    # Bank details print anyway (gst_invoice.print_bank_details, test_payment_summary.py).
    for gone in ("Payment Terms", "Interest", "bill not paid"):
        assert gone not in joined, gone
    no_bank = dataclasses.replace(cfg(), gst_invoice={**cfg().gst_invoice, "print_bank_details": False})
    joined_no_bank = " ".join(page_text(render_document(_gst_doc(payments), no_bank)))
    for gone in ("ICICI", "Account No", "IFSC", "COMPANY NAME"):
        assert gone not in joined_no_bank, gone
    for kept in ("TERMS & CONDITIONS :", "1. Goods once sold will not be returned/ Exchanged.",
                 "2. Our responsibility ceases after the goods are removed", "3. All disputes subject to Chandigarh Jurisdiction.",
                 "Transport : Self", "Station:- Chandigarh", "For BASTTA", "Total :"):
        assert kept in joined, kept
    # With the details on, the template's bank block, payment field and late-payment term come back.
    full = " ".join(page_text(render_document(_gst_doc(payments), full_cfg())))
    for back in ("Payment Terms: Advance", "ICICI BANK", "2. Interest will be charged @36% p.a. if bill not paid within"):
        assert back in full, back
