"""A re-opened invoice prints exactly like the first print (reported QR inconsistency, 2026-10-03).

No invoice template draws a QR code: the only one was the quotation's UPI QR, removed in
09be032, and invoices carry no payment details at all (print_payment_details: false). What a
first print and a reprint show must therefore match byte for byte: a reprint renders from the
stored record, never from state that only existed when the invoice was made.
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
    # Band and logo only, on the first print and on every reprint: no QR code appears or disappears.
    assert images(first.content) == images(again.content) == [2]


def test_reprint_after_recording_a_payment_is_unchanged(client, auth):  # noqa: F811
    first = client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    bill_no = first.headers["x-bill-no"]
    paid = client.post(f"/api/invoices/{bill_no}/payments", json={"amount": "1000", "date": "2026-10-01", "mode": "cash"}, headers=auth)
    assert paid.status_code == 200 and paid.headers["x-invoice-status"] == "part_paid"
    assert paid.content == first.content == client.get(f"/api/invoices/{bill_no}/pdf", headers=auth).content


def test_print_paid_and_unpaid_match(client, auth):  # noqa: F811
    unpaid = client.post("/api/invoices", json=invoice_body([k1_line(client)], bill_no=500), headers=auth)
    paid = client.post(
        "/api/invoices",
        json=invoice_body([k1_line(client)], print_mode="paid", bill_no=500 + 1,
                          payments=[{"amount": "26250", "date": "2026-10-01", "mode": "upi"}]),
        headers=auth,
    )
    assert unpaid.status_code == paid.status_code == 201
    # Only the bill number differs between the two, so the pages differ in that text alone.
    with open_pdf(unpaid.content) as a, open_pdf(paid.content) as b:
        ta, tb = a.pages[0].extract_text(), b.pages[0].extract_text()
    assert ta.replace("500", "501") == tb


def test_gst_reprint_is_identical(client, auth):  # noqa: F811
    first = client.post("/api/invoices", json=gst_body([k1_line(client)], "intra_18"), headers=auth)
    assert first.status_code == 201
    again = client.get(f"/api/invoices/{first.headers['x-bill-no']}/pdf?series=gst", headers=auth)
    assert again.content == first.content and images(again.content) == images(first.content)
