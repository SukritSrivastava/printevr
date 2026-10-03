"""Custom invoice: a normal invoice whose line rates staff may override (`is_custom`).

The calculated rate (`catalogue_unit_price`) and the billed rate (`unit_price`) are both stored
per line with `price_edited`; the invoice stores `is_custom`. Nothing about it is printed, a
reprint renders the stored rates (never re-priced), and it shares the normal number series.
"""
import dataclasses
from decimal import Decimal

from app.invoice.render import document_money
from app.invoice.service import document
from app.loader import build_catalogue

from .invoice_helpers import cfg, open_pdf
from .test_invoice_api import app, auth, client, invoice_body, k1_line, token  # noqa: F401
from .test_quotation_gst import gst_body, pdf_lines, pdf_text

D = Decimal


def custom(body: dict) -> dict:
    return {**body, "is_custom": True}


def stored(app, bill_no: int, series: str = "non_gst"):  # noqa: F811
    store = app.state.invoices["store"]
    with store.session() as s:
        return document(store.get(s, bill_no, series), series)


def test_overriding_one_rate_updates_amount_total_gst_and_split(app, client, auth):  # noqa: F811
    # 350 rigid boxes: calculated 75 -> 26,250.00. Override to 70 -> 24,500.00.
    lines = [k1_line(client, unit_price="70.00"), k1_line(client)]
    r = client.post("/api/invoices", json=custom(gst_body(lines, "intra_18")), headers=auth)
    assert r.status_code == 201, r.text
    detail = client.get(f"/api/invoices/{r.headers['x-bill-no']}?series=gst", headers=auth).json()
    assert detail["is_custom"] is True
    first, second = detail["lines"]
    assert (first["catalogue_unit_price"], first["unit_price"], first["price_edited"]) == ("75.00", "70.00", True)
    assert (second["catalogue_unit_price"], second["unit_price"], second["price_edited"]) == ("75.00", "75.00", False)
    # total 24,500 + 26,250 = 50,750; CGST and UGST 9% each = 4,567.50; payable 59,885.00
    assert detail["total"] == "50750.00" and detail["gst_amount"] == "9135.00" and detail["payable"] == "59885.00"
    text = pdf_text(r.content)
    for expected in ("24,500.00", "26,250.00", "SUB-TOTAL : 50,750.00", "CGST Tax (9%) : 4,567.50", "Total : 59,885.00"):
        assert expected in text, expected
    # The 80 / 20 split is no longer printed, but it is still worked out from the overridden total.
    doc = stored(app, int(r.headers["x-bill-no"]), "gst")
    m = document_money(doc.model_copy(update={"advance_pct": D(80)}), cfg())
    assert (m.advance, m.balance) == (D("47908.00"), D("11977.00"))


def test_non_gst_custom_invoice_prints_like_a_regular_one(client, auth):  # noqa: F811
    regular = client.post("/api/invoices", json=invoice_body([k1_line(client, unit_price="70.00")], bill_no=700), headers=auth)
    custom_inv = client.post("/api/invoices", json=custom(invoice_body([k1_line(client, unit_price="70.00")], bill_no=701)), headers=auth)
    assert regular.status_code == custom_inv.status_code == 201
    a, b = pdf_text(regular.content), pdf_text(custom_inv.content)
    assert a.replace("700", "701") == b  # only the bill number differs
    lines = pdf_lines(custom_inv.content)
    joined = " ".join(lines)
    assert "24500" in joined and "TOTAL: 24500" in pdf_text(custom_inv.content)
    for gone in ("custom invoice", "Custom invoice", "CUSTOM INVOICE", "Calculated", "calculated", "26250"):
        assert gone not in joined, gone
    assert not any(t.split() and t.split()[-1] == "75" for t in lines)  # the calculated rate isn't shown


def test_save_reload_reprint_keeps_overridden_prices(app, client, auth):  # noqa: F811
    first = client.post("/api/invoices", json=custom(invoice_body([k1_line(client, unit_price="70.00")])), headers=auth)
    bill_no = first.headers["x-bill-no"]
    again = client.get(f"/api/invoices/{bill_no}/pdf", headers=auth)
    assert again.content == first.content
    detail = client.get(f"/api/invoices/{bill_no}", headers=auth).json()
    assert detail["lines"][0]["unit_price"] == "70.00" and detail["total"] == "24500.00" and detail["is_custom"] is True
    # A recorded payment still reprints the same prices (and still no payment details or QR).
    paid = client.post(f"/api/invoices/{bill_no}/payments", json={"amount": "5000", "date": "2026-10-02"}, headers=auth)
    assert paid.status_code == 200 and paid.content == first.content
    assert client.get(f"/api/invoices/{bill_no}", headers=auth).json()["received"] == "5000.00"
    with open_pdf(paid.content) as pdf:
        assert len(pdf.pages[0].images) == 2


def test_catalogue_price_changes_never_touch_saved_invoices(app, client, auth, sheet):  # noqa: F811
    first = client.post("/api/invoices", json=custom(invoice_body([k1_line(client, unit_price="70.00"), k1_line(client)])), headers=auth)
    bill_no = first.headers["x-bill-no"]
    data = app.state.store
    original = data.catalogue
    rows = [dataclasses.replace(r, price=r.price * 2) if r.product == "Rigid Boxes" else r for r in sheet[0]]
    data.catalogue = build_catalogue(rows, sheet[1], sheet[2])
    try:
        assert client.post("/api/calculate", json={"item_id": "rigid_boxes/3x3x2-in/top-bottom", "quantity": 350}).json()["data"]["pricing"]["unit_price"] == "150.00"
        assert client.get(f"/api/invoices/{bill_no}/pdf", headers=auth).content == first.content
        lines = client.get(f"/api/invoices/{bill_no}", headers=auth).json()["lines"]
        assert [(l["catalogue_unit_price"], l["unit_price"]) for l in lines] == [("75.00", "70.00"), ("75.00", "75.00")]
    finally:
        data.catalogue = original


def test_custom_invoice_still_checks_products_quantities_and_calculated_prices(client, auth):  # noqa: F811
    # A stale calculated rate is still caught (PRICES_CHANGED), whatever the override.
    stale = k1_line(client, unit_price="70.00", catalogue_unit_price="80.00")
    r = client.post("/api/invoices", json=custom(invoice_body([stale])), headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PRICES_CHANGED"
    # Catalogue minimums still apply: the bags need 300 on a custom invoice too.
    request = {"item_id": "courier_bags/6x8-in", "quantity": 250, "options": {}, "addons": [], "billing_type": "gst"}
    bag = {**k1_line(client), "calc_request": request, "quantity": 250, "unit_price": "1.00"}
    r = client.post("/api/invoices", json=custom(invoice_body([bag])), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "LINE_NOT_PRICEABLE"


def test_rate_must_not_be_negative_and_zero_only_on_a_custom_invoice(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=custom(invoice_body([k1_line(client, unit_price="-1.00")])), headers=auth)
    assert r.status_code == 422
    r = client.post("/api/invoices", json=invoice_body([k1_line(client, unit_price="0.00")]), headers=auth)
    assert r.status_code == 422 and "above 0" in r.json()["error"]["message"]
    ok = client.post("/api/invoices", json=custom(invoice_body([k1_line(client, unit_price="0.00"), k1_line(client)])), headers=auth)
    assert ok.status_code == 201, ok.text
    assert client.get(f"/api/invoices/{ok.headers['x-bill-no']}", headers=auth).json()["total"] == "26250.00"


def test_regular_and_custom_invoices_share_one_number_series(client, auth):  # noqa: F811
    numbers = []
    for is_custom in (False, True, False, True, True):
        body = invoice_body([k1_line(client, unit_price="70.00" if is_custom else "75.00")], is_custom=is_custom)
        r = client.post("/api/invoices", json=body, headers=auth)
        assert r.status_code == 201, r.text
        numbers.append(int(r.headers["x-bill-no"]))
    assert numbers == [19, 20, 21, 22, 23]
    listed = client.get("/api/invoices", headers=auth).json()["invoices"]
    assert [(row["bill_no"], row["is_custom"]) for row in listed] == [(23, True), (22, True), (21, False), (20, True), (19, False)]
