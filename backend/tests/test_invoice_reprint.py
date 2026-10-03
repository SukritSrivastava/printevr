"""A re-opened invoice prints exactly like the first print (reported QR inconsistency, 2026-10-03).

No invoice template draws a QR code: the only one was the quotation's UPI QR, removed in
09be032. A reprint renders from the stored record, never from state that only existed when the
invoice was made, so it matches the first print byte for byte until a payment is recorded; the
payment summary (config/invoice.yaml payment_summary) then lists it under RECIEVABLES.
"""
from .invoice_helpers import open_pdf
from .test_invoice_api import app, auth, client, invoice_body, k1_line, token  # noqa: F401
from .test_quotation_gst import gst_body


def images(data: bytes) -> list[int]:
    with open_pdf(data) as pdf:
        return [len(page.images) for page in pdf.pages]


def test_non_gst_unpaid_reprint_is_identical(client, auth):  # noqa: F811
    first = client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    assert first.status_code == 201
    bill_no = first.headers["x-bill-no"]
    again = client.get(f"/api/invoices/{bill_no}/pdf", headers=auth)
    third = client.get(f"/api/invoices/{bill_no}/pdf", headers=auth)
    assert again.status_code == third.status_code == 200
    assert first.content == again.content == third.content
    # Band, logo and UPI QR, on the first print and on every reprint.
    assert images(first.content) == images(again.content) == [3]


def text_of(data: bytes) -> str:
    with open_pdf(data) as pdf:
        return "\n".join(page.extract_text() for page in pdf.pages)


def test_reprint_after_recording_a_payment_shows_it(client, auth):  # noqa: F811
    first = client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    bill_no = first.headers["x-bill-no"]
    assert "RECIEVABLES" not in text_of(first.content)
    paid = client.post(f"/api/invoices/{bill_no}/payments", json={"amount": "1000", "date": "2026-10-01", "mode": "cash"}, headers=auth)
    assert paid.status_code == 200 and paid.headers["x-invoice-status"] == "part_paid"
    # The payment PDF and every later reprint are the same, and list the payment.
    assert paid.content == client.get(f"/api/invoices/{bill_no}/pdf", headers=auth).content
    text = text_of(paid.content)
    assert "1 OCTOBER 2026:- 1000/- (VIA CASH)" in text
    assert "PENDING AMOUNT (TO BE PAID) :- 25250/- (BEFORE DELIVERY)" in text  # 26250 - 1000


def test_print_paid_and_unpaid_differ_only_by_the_receivables(client, auth):  # noqa: F811
    unpaid = client.post("/api/invoices", json=invoice_body([k1_line(client)], bill_no=500), headers=auth)
    paid = client.post(
        "/api/invoices",
        json=invoice_body([k1_line(client)], print_mode="paid", bill_no=500 + 1,
                          payments=[{"amount": "26250", "date": "2026-10-01", "mode": "upi"}]),
        headers=auth,
    )
    assert unpaid.status_code == paid.status_code == 201
    ta, tb = text_of(unpaid.content), text_of(paid.content)
    assert "RECIEVABLES" not in ta and "RECIEVABLES" in tb
    assert "PENDING AMOUNT (TO BE PAID) :- 0/- (PAID IN FULL)" in tb
    assert "Received Amount:- Rs. 0/-" in ta and "Amount Pending:- Rs. 26250/-" in ta
    assert "Received Amount:- Rs. 26250/-" in tb and "Amount Pending:- Rs. 0/-" in tb
    # Apart from the bill number, the received/pending amounts and the RECIEVABLES box, the pages say the same.
    receivables = tb[tb.index("RECIEVABLES"):tb.index("PAID IN FULL)") + len("PAID IN FULL)")]
    tb = tb.replace(receivables + "\n", "")
    tb = tb.replace("Received Amount:- Rs. 26250/-", "Received Amount:- Rs. 0/-")
    tb = tb.replace("Amount Pending:- Rs. 0/-", "Amount Pending:- Rs. 26250/-")
    assert ta.replace("500", "501") == tb


def test_gst_reprint_is_identical(client, auth):  # noqa: F811
    first = client.post("/api/invoices", json=gst_body([k1_line(client)], "intra_18"), headers=auth)
    assert first.status_code == 201
    again = client.get(f"/api/invoices/{first.headers['x-bill-no']}/pdf?series=gst", headers=auth)
    assert again.content == first.content and images(again.content) == images(first.content)
