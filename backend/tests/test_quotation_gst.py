"""Quotation, Non-GST invoice and GST invoice (BASTTA): slabs, checks, numbering and printing."""
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.invoice import gst
from app.invoice.models import InvoiceDocument
from app.invoice.money import compute
from app.invoice.render import render, render_document
from app.invoice.store import GstInvoiceRow, InvoiceRow, QuotationRow

from .invoice_helpers import cfg, chars, lines_by_baseline, open_pdf, sogat_doc, sogat_raw
from .test_invoice_api import app, auth, client, invoice_body, k1_line, token, unsaved, unsaved_app  # noqa: F401

D = Decimal


def quotation_body(lines, **changes):
    body = invoice_body(lines, **changes)
    body.update(document_type="quotation", bill_type=None, print_mode=None)
    body.update(changes)
    return body


def gst_body(lines, slab, **changes):
    body = invoice_body(lines, bill_type="gst", gst_slab=slab)
    body["gst"] = {
        "buyer": {"name": "Jairpur Jewellers", "address": "SCO 12, Sector 17, Chandigarh", "phone": "94172 81136",
                  "gstin": "04ABCDE1234F1Z5"},
        "consignee_same": True,
        "payment_terms": "Advance",
        "transport": "Self",
        "station": "Chandigarh",
    }
    body.update(changes)
    return body


def pdf_lines(data: bytes) -> list[str]:
    """Each baseline's text, read character by character (stacked labels stay apart)."""
    with open_pdf(data) as pdf:
        return ["".join(c["text"] for c in line) for page in pdf.pages for line in lines_by_baseline(chars(page))]


def pdf_text(data: bytes) -> str:
    with open_pdf(data) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


def slab(key):
    return gst.find_slab(cfg().gst_slabs, key)


# ---------------------------------------------------------------- slabs and tax maths


def test_slabs_in_order_with_groups():
    c = cfg()
    assert [(s.key, s.label) for s in c.gst_slabs] == [
        ("intra_5", "2.5% CGST + 2.5% SGST/UTGST (5%)"),
        ("intra_12", "6% CGST + 6% SGST/UTGST (12%)"),
        ("intra_18", "9% CGST + 9% SGST/UTGST (18%)"),
        ("inter_5", "5% IGST"),
        ("inter_12", "12% IGST"),
        ("inter_18", "18% IGST"),
    ]
    groups = gst.public_slabs(list(c.gst_slab_groups), c.gst_slabs)
    assert [g["label"] for g in groups] == ["Intra-state (CGST + SGST/UTGST, IGST 0%)", "Inter-state (IGST)"]
    # the second intra-state component prints as UGST, as on the template
    assert [c.name for c in slab("intra_18").components] == ["CGST", "UGST", "IGST"]


# slab -> (CGST, UGST, IGST, after-tax total) for taxable 10,000.00 and 100.05 (Step 8)
TABLE = {
    "intra_5": (("250.00", "250.00", "0.00", "10500.00"), ("2.50", "2.50", "0.00", "105.05")),
    "intra_12": (("600.00", "600.00", "0.00", "11200.00"), ("6.00", "6.00", "0.00", "112.05")),
    "intra_18": (("900.00", "900.00", "0.00", "11800.00"), ("9.00", "9.00", "0.00", "118.05")),
    "inter_5": (("0.00", "0.00", "500.00", "10500.00"), ("0.00", "0.00", "5.00", "105.05")),
    "inter_12": (("0.00", "0.00", "1200.00", "11200.00"), ("0.00", "0.00", "12.01", "112.06")),
    "inter_18": (("0.00", "0.00", "1800.00", "11800.00"), ("0.00", "0.00", "18.01", "118.06")),
}


@pytest.mark.parametrize("key", TABLE)
@pytest.mark.parametrize("taxable, column", [("10000.00", 0), ("100.05", 1)])
def test_tax_table(key, taxable, column):
    cgst, ugst, igst, total = TABLE[key][column]
    m = compute([D(taxable)], slab(key).components, D(80))
    assert [str(t.amount) for t in m.taxes] == [cgst, ugst, igst]
    assert all(isinstance(t.amount, Decimal) for t in m.taxes)
    assert m.total == D(taxable)  # taxable value = the pre-tax subtotal
    assert str(m.payable) == total  # (After Tax) Sub-total = Total


def test_non_applicable_components_are_exactly_zero():
    m = compute([D("12345.67")], slab("inter_18").components, D(80))
    assert m.taxes[0].amount == D("0.00") and m.taxes[1].amount == D("0.00")
    assert str(m.taxes[0].amount) == "0.00"


# ---------------------------------------------------------------- request checks (400)


@pytest.mark.parametrize("bad", [None, "", "gst_18", "intra_99"])
def test_gst_invoice_needs_a_known_slab(client, auth, bad):  # noqa: F811
    r = client.post("/api/invoices", json=gst_body([k1_line(client)], bad), headers=auth)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "INVALID_GST_SLAB" and err["details"]["field"] == "gst_slab"
    assert "slab" in err["message"].lower()


@pytest.mark.parametrize("kind", ["quotation", "non_gst"])
def test_slab_on_anything_but_a_gst_invoice_is_refused(client, auth, kind):  # noqa: F811
    line = k1_line(client)
    body = quotation_body([line], gst_slab="intra_18") if kind == "quotation" else invoice_body([line], gst_slab="intra_18")
    r = client.post("/api/invoices", json=body, headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_GST_SLAB"
    assert "only applies to a GST invoice" in r.json()["error"]["message"]


def test_slab_checks_also_apply_without_storage(unsaved):  # noqa: F811
    c, auth_ = unsaved
    r = c.post("/api/invoices", json=gst_body([k1_line(c)], None, bill_no=3), headers=auth_)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_GST_SLAB"


def test_invoice_needs_bill_type_and_print_mode(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)], bill_type=None), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "bill_type"
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)], print_mode=None), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "print_mode"


def test_quotation_has_no_payment_state(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=quotation_body([k1_line(client)], print_mode="unpaid"), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "print_mode"


def test_quotation_needs_only_lines(client, auth):  # noqa: F811
    body = quotation_body([k1_line(client)], customer={})
    r = client.post("/api/invoices", json=body, headers=auth)
    assert r.status_code == 201, r.text
    assert r.headers["x-document-series"] == "quotation" and r.headers["x-invoice-status"] == "issued"
    assert 'filename="Quotation_1_Customer.pdf"' in r.headers["content-disposition"]


def test_non_gst_invoice_still_needs_ship_to(client, auth):  # noqa: F811
    body = invoice_body([k1_line(client)], customer={"business_name": "Shop"})
    r = client.post("/api/invoices", json=body, headers=auth)
    assert r.status_code == 422 and set(r.json()["error"]["details"]["fields"]) == {"address", "phone"}


def test_gst_invoice_needs_buyer_name_and_valid_gstin(client, auth):  # noqa: F811
    body = gst_body([k1_line(client)], "intra_18")
    body["gst"]["buyer"]["name"] = " "
    r = client.post("/api/invoices", json=body, headers=auth)
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "gst.buyer.name"
    body = gst_body([k1_line(client)], "intra_18")
    body["gst"]["buyer"]["gstin"] = "4ABC"
    assert client.post("/api/invoices", json=body, headers=auth).status_code == 422


# ---------------------------------------------------------------- printing


def test_gst_invoice_prints_all_three_tax_rows(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=gst_body([k1_line(client)], "inter_18"), headers=auth)
    assert r.status_code == 201, r.text
    text = pdf_text(r.content)
    # 350 boxes x 75 = 26,250.00; IGST 18% = 4,725.00
    for expected in ("SUB-TOTAL : 26,250.00", "CGST Tax (0%) : 0.00", "UGST Tax (0%) : 0.00",
                     "IGST Tax (18%) : 4,725.00", "(After Tax) Sub-total : 30,975.00", "Total : 30,975.00"):
        assert expected in text, expected
    for expected in ("ORIGINAL COPY", "INVOICE NO. 1", "Goods once sold", "For BASTTA",
                     "Certified that the particulars given above are true & correct", "Buyer Info (Billed to)",
                     "Consignee Info (Shipped to)", "Payment Terms: Advance", "Transport : Self", "Station:- Chandigarh",
                     "GSTIN :- 04ABCDE1234F1Z5", "HSN CODE"):
        assert expected in text, expected
    for typo in ("orignal", "N0.", "Good once"):
        assert typo not in text


def test_gst_invoice_intra_slab_rows(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=gst_body([k1_line(client)], "intra_18"), headers=auth)
    text = pdf_text(r.content)
    for expected in ("CGST Tax (9%) : 2,362.50", "UGST Tax (9%) : 2,362.50", "IGST Tax (0%) : 0.00", "Total : 30,975.00"):
        assert expected in text, expected
    detail = client.get("/api/invoices/1?series=gst", headers=auth).json()
    assert detail["gst"] == {"option": "intra_18", "taxes": [
        {"name": "CGST", "rate": "9", "amount": "2362.50"},
        {"name": "UGST", "rate": "9", "amount": "2362.50"},
        {"name": "IGST", "rate": "0", "amount": "0.00"},
    ]}
    assert detail["details"]["buyer"]["gstin"] == "04ABCDE1234F1Z5" and detail["details"]["transport"] == "Self"
    assert detail["payable"] == "30975.00" and detail["gst_slab"] == "intra_18"


def test_gst_invoice_hsn_and_consignee(client, auth):  # noqa: F811
    line = k1_line(client, hsn_code="4819")
    body = gst_body([line], "intra_5")
    body["gst"].update(consignee_same=False, consignee={"name": "Warehouse Two", "address": "Phase 8, Mohali"},
                       vehicle_no="CH01AB1234", po_date="2026-09-28")
    text = pdf_text(client.post("/api/invoices", json=body, headers=auth).content)
    assert "4819" in text and "WAREHOUSE TWO" in text and "Vehicle no. : CH01AB1234" in text
    assert "P.O Date :- 28/09/2026" in text


def test_empty_hsn_still_prints(client, auth):  # noqa: F811
    """No product has an HSN code yet (config/products.yaml): the column prints blank, nothing blocks."""
    r = client.post("/api/invoices", json=gst_body([k1_line(client, hsn_code="")], "intra_18"), headers=auth)
    assert r.status_code == 201 and r.content.startswith(b"%PDF")
    r = client.post("/api/invoices", json=gst_body([k1_line(client)], "intra_18"), headers=auth)  # hsn from config
    assert r.status_code == 201
    stored = client.get("/api/invoices/2?series=gst", headers=auth).json()["lines"][0]
    assert stored["hsn_code"] == ""


def totals_lines(text: str) -> list[str]:
    return [t for t in text.splitlines() if t.startswith(("TOTAL:", "SUB TOTAL"))]


def test_quotation_and_non_gst_totals_match_and_have_no_tax(client, auth):  # noqa: F811
    lines = [k1_line(client)]
    inv = client.post("/api/invoices", json=invoice_body(lines, saving_amount="500"), headers=auth)
    quo = client.post("/api/invoices", json=quotation_body(lines, saving_amount="500"), headers=auth)
    inv_text, quo_text = pdf_text(inv.content), pdf_text(quo.content)
    assert totals_lines(inv_text) == totals_lines(quo_text) == ["TOTAL: 26250", "SUB TOTAL : 26250"]
    for text in (inv_text, quo_text):
        assert "CGST" not in text and "IGST" not in text and "GST @" not in text
    assert "QUOTATION" in quo_text and "Quote No : 1" in quo_text
    header = " ".join(pdf_lines(quo.content))
    for label in ("ITEM", "QUANTITY", "MARKET", "DISCOUNTED", "PRICE", "SUBTOTAL"):
        assert label in header, label
    assert "Here are my UPI details" in quo_text and "PAYMENT TERMS" not in quo_text
    assert "PAYMENT TERMS     (WITHOUT GST BILLING)" in pdf_lines(inv.content)
    listed = client.get("/api/invoices/19", headers=auth).json()
    assert listed["total"] == listed["payable"] == "26250.00" and listed["gst"] is None


def test_quotation_rows_number_articles_and_group_addons(client, auth):  # noqa: F811
    calc = {"item_id": "butter_paper/29x9-in", "quantity": 1500, "addons": ["multicolour"]}
    drafts = client.post("/api/calculate", json=calc).json()["data"]["invoice_lines"]
    parent = {**drafts[0], "id": "p1", "calc_request": calc}
    addon = {**drafts[1], "id": "a1", "parent_id": "p1"}
    text = pdf_text(client.post("/api/invoices", json=quotation_body([parent, addon, k1_line(client)]), headers=auth).content)
    assert "1.CUSTOMISED BUTTER PAPER PRINTING" in text and "2.CUSTOMISED" in text
    assert "MULTICOLOUR PRINT (ADD-ON)" in text and "1.MULTICOLOUR" not in text


# ---------------------------------------------------------------- numbering


def post(client, auth, body):  # noqa: F811
    r = client.post("/api/invoices", json=body, headers=auth)
    assert r.status_code == 201, r.text
    return int(r.headers["x-bill-no"]), r.headers["x-document-series"]


def test_series_number_independently_and_reprints_keep_numbers(client, auth):  # noqa: F811
    line = lambda: k1_line(client)  # noqa: E731
    got = [
        post(client, auth, quotation_body([line()])),
        post(client, auth, invoice_body([line()])),
        post(client, auth, gst_body([line()], "intra_18")),
        post(client, auth, quotation_body([line()])),
        post(client, auth, gst_body([line()], "inter_5")),
        post(client, auth, invoice_body([line()])),
    ]
    assert got == [(1, "quotation"), (19, "non_gst"), (1, "gst"), (2, "quotation"), (2, "gst"), (20, "non_gst")]
    assert client.get("/api/invoices/next-bill-no", headers=auth).json()["next"] == {"quotation": 3, "non_gst": 21, "gst": 3}
    for series, number in (("quotation", 2), ("gst", 1), ("non_gst", 19)):
        first = client.get(f"/api/invoices/{number}/pdf?series={series}", headers=auth)
        again = client.get(f"/api/invoices/{number}/pdf?series={series}", headers=auth)
        assert first.status_code == 200 and first.content == again.content
        assert first.headers["x-bill-no"] == str(number) and first.headers["x-document-series"] == series
    # downloading allocates nothing
    assert client.get("/api/invoices/next-bill-no", headers=auth).json()["next"] == {"quotation": 3, "non_gst": 21, "gst": 3}
    assert [i["bill_no"] for i in client.get("/api/invoices?series=gst", headers=auth).json()["invoices"]] == [2, 1]


def test_deleted_numbers_are_never_reused(client, auth):  # noqa: F811
    assert post(client, auth, gst_body([k1_line(client)], "intra_18")) == (1, "gst")
    assert client.delete("/api/invoices/1?series=gst", headers=auth).json() == {"deleted": 1, "series": "gst"}
    assert post(client, auth, gst_body([k1_line(client)], "intra_18")) == (2, "gst")
    assert post(client, auth, invoice_body([k1_line(client)])) == (19, "non_gst")
    client.delete("/api/invoices/19", headers=auth)
    assert post(client, auth, invoice_body([k1_line(client)])) == (20, "non_gst")


def test_gst_payments_and_quotation_has_none(client, auth):  # noqa: F811
    post(client, auth, gst_body([k1_line(client)], "intra_18"))
    r = client.post("/api/invoices/1/payments?series=gst", json={"amount": "30975", "date": "2026-10-01"}, headers=auth)
    assert r.status_code == 200 and r.headers["x-invoice-status"] == "paid"
    assert "GST_Invoice_1_Jairpur-Jewellers_Paid.pdf" in r.headers["content-disposition"]
    post(client, auth, quotation_body([k1_line(client)]))
    r = client.post("/api/invoices/1/payments?series=quotation", json={"amount": "1", "date": "2026-10-01"}, headers=auth)
    assert r.status_code == 422


# ---------------------------------------------------------------- old records


LEGACY = {
    "gst_5": [{"name": "GST", "rate": "5", "amount": "7400.00"}],
    "gst_12": [{"name": "GST", "rate": "12", "amount": "17760.00"}],
    "gst_18": [{"name": "GST", "rate": "18", "amount": "26640.00"}],
    "cgst_sgst_9_9": [{"name": "CGST", "rate": "9", "amount": "13320.00"}, {"name": "SGST/UTGST", "rate": "9", "amount": "13320.00"}],
}


def legacy_row(app, key, salesperson=None):  # noqa: F811
    raw = {k: v for k, v in sogat_raw().items() if k not in ("expected", "_comment")}
    now = datetime.now(timezone.utc)
    taxes = LEGACY.get(key)
    gst_amount = sum((D(t["amount"]) for t in taxes), D(0)) if taxes else D(0)
    row = InvoiceRow(
        bill_no=raw["bill_no"], invoice_date=date.fromisoformat(raw["invoice_date"]),
        billing_type="with_gst" if key else "without_gst", business_name=raw["customer"]["business_name"],
        customer=raw["customer"], lines=raw["lines"], payments=[], saving_amount=raw.get("saving_amount"),
        total=D("148000"), gst_amount=gst_amount, gst={"option": key, "taxes": taxes} if key else None,
        salesperson=salesperson, payable=D("148000") + gst_amount, received=D(0), status="unpaid", version=1,
        created_at=now, updated_at=now,
    )
    with app.state.invoices["store"].session() as s:
        s.add(row)
        s.commit()
    return raw


@pytest.mark.parametrize("key", list(LEGACY))
def test_old_records_with_legacy_keys_reprint_unchanged(app, client, auth, key):  # noqa: F811
    raw = legacy_row(app, key)
    expected = render(sogat_doc(billing_type="with_gst", gst_option=key, taxes=LEGACY[key], payments=[]), cfg())
    r = client.get(f"/api/invoices/{raw['bill_no']}/pdf", headers=auth)
    assert r.status_code == 200 and r.content == expected
    text = pdf_text(r.content)
    for tax in LEGACY[key]:
        assert f"{tax['name']} @ {tax['rate']}%:" in text
    assert [o.key for o in cfg().legacy_gst_options] == list(LEGACY)  # mapping kept for reading only
    assert key not in [s.key for s in cfg().gst_slabs]


def test_no_document_prints_the_salesperson(app, client, auth):  # noqa: F811
    raw = legacy_row(app, None, salesperson="Mr. Old Salesperson")
    old = client.get(f"/api/invoices/{raw['bill_no']}/pdf", headers=auth)
    new = [
        client.post("/api/invoices", json=b, headers=auth).content
        for b in (quotation_body([k1_line(client)]), invoice_body([k1_line(client)], salesperson="Mr. X"),
                  gst_body([k1_line(client)], "intra_18", salesperson="Mr. X"))
    ]
    for pdf in (old.content, *new):
        text = pdf_text(pdf)
        assert "Salesperson" not in text and "Mr. Old" not in text and "Mr. X" not in text
    # the stored name stays in the database, untouched
    with app.state.invoices["store"].session() as s:
        assert s.get(InvoiceRow, 1).salesperson == "Mr. Old Salesperson"


def test_render_documents_directly():
    """The three templates from one document model; each is one A4 page for a short cart."""
    base = {k: v for k, v in sogat_raw().items() if k not in ("expected", "_comment")}
    base["lines"] = [{**line, "customisations": []} for line in base["lines"]]  # BASTTA's table is short
    for series, extra in (
        ("quotation", {}),
        ("non_gst", {}),
        ("gst", {"gst": {"buyer": {"name": "Sogat"}}, "taxes": LEGACY["cgst_sgst_9_9"]}),
    ):
        doc = InvoiceDocument.model_validate({**base, "series": series, **extra})
        with open_pdf(render_document(doc, cfg())) as pdf:
            assert len(pdf.pages) == 1
            assert (float(pdf.pages[0].width), float(pdf.pages[0].height)) == (595.5, 842.25)


def test_long_gst_invoice_paginates_with_totals_on_the_last_page():
    base = {k: v for k, v in sogat_raw().items() if k not in ("expected", "_comment")}
    line = base["lines"][1]
    lines = [{**line, "id": str(uuid.uuid4()), "title": f"Customised test article {i + 1} printing"} for i in range(16)]
    doc = InvoiceDocument.model_validate({**base, "series": "gst", "lines": lines, "gst": {"buyer": {"name": "Sogat"}},
                                          "taxes": LEGACY["cgst_sgst_9_9"]})
    with open_pdf(render_document(doc, cfg())) as pdf:
        texts = [page.extract_text() for page in pdf.pages]
    assert len(texts) > 1
    assert all("Total :" not in t for t in texts[:-1]) and "Total :" in texts[-1]
    assert "INVOICE NO. 18 (continued)" in texts[1]
    for i in range(16):
        assert sum(f"CUSTOMISED TEST ARTICLE {i + 1} PRINTING" in t for t in texts) == 1


# ---------------------------------------------------------------- pay in full, or a chosen split


def test_invoice_defaults_to_payment_in_full(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    lines = pdf_lines(r.content)
    assert any(t.startswith("100% amount pending") and t.endswith("26250/-") for t in lines)
    assert not any("20% Amount" in t or "80%" in t for t in lines)  # no split unless chosen
    assert client.get("/api/invoices/19", headers=auth).json()["advance_pct"] == "100"


def test_split_is_chosen_per_invoice_and_kept_for_payments(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)], advance_pct="70"), headers=auth)
    lines = pdf_lines(r.content)
    assert any(t.startswith("70% amount pending") and t.endswith("18375/-") for t in lines)
    assert any(t.startswith("30% Amount:- Rs. 7875/-") for t in lines)
    r = client.post("/api/invoices/19/payments", json={"amount": "1000", "date": "2026-10-01"}, headers=auth)
    assert any(t.startswith("Amount Pending (out of 70%)") for t in pdf_lines(r.content))
    assert client.get("/api/invoices/19", headers=auth).json()["advance_pct"] == "70"


def test_old_invoices_without_a_choice_keep_their_80_20_split(app, client, auth):  # noqa: F811
    raw = legacy_row(app, None)
    lines = pdf_lines(client.get(f"/api/invoices/{raw['bill_no']}/pdf", headers=auth).content)
    assert any(t.startswith("80% amount pending") for t in lines)
    assert any(t.startswith("20% Amount:-") for t in lines)


def test_quotation_has_no_advance(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=quotation_body([k1_line(client)], advance_pct="80"), headers=auth)
    assert r.status_code == 201
    assert client.get("/api/invoices/1?series=quotation", headers=auth).json()["advance_pct"] is None


@pytest.mark.parametrize("bad", ["0", "100.5", "-5", "abc"])
def test_advance_pct_must_be_a_percent(client, auth, bad):  # noqa: F811
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)], advance_pct=bad), headers=auth)
    assert r.status_code == 422


def test_quotation_prints_upi_details_without_a_qr_code(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=quotation_body([k1_line(client)]), headers=auth)
    with open_pdf(r.content) as pdf:
        images = pdf.pages[0].images
    assert len(images) == 2  # the band and the Printevr logo only
    assert all(i["top"] < 160 for i in images)  # nothing down by the UPI block
    assert "Here are my UPI details" in pdf_text(r.content)
