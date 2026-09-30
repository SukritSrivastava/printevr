"""Selectable GST on With GST invoices (config/invoice.yaml gst_options)."""
from decimal import Decimal

import pytest

from app.invoice import gst
from app.invoice import layout as L
from app.invoice.money import compute
from app.invoice.render import render

from .invoice_helpers import cfg, chars, lines_by_baseline, open_pdf, sogat_doc
from .test_invoice_api import app, auth, client, invoice_body, k1_line, rows, token, unsaved, unsaved_app  # noqa: F401

D = Decimal


def option(key):
    return gst.find(cfg().gst_options, key)


def taxes(taxable, key):
    m = compute([D(taxable)], option(key).components, cfg().advance_pct)
    return [(t.name, t.rate, t.amount) for t in m.taxes], m.gst, m.payable


def pdf_lines(data: bytes) -> list[tuple[float, str]]:
    with open_pdf(data) as pdf:
        cs = chars(pdf.pages[-1])
    return [(round(l[0]["baseline"], 2), "".join(c["text"] for c in l)) for l in lines_by_baseline(cs)]


# ---------------------------------------------------------------- options


def test_options_in_order():
    assert [(o.key, o.label) for o in cfg().gst_options] == [
        ("gst_5", "5% GST"),
        ("gst_12", "12% GST"),
        ("gst_18", "18% GST"),
        ("cgst_sgst_9_9", "9% CGST + 9% SGST/UTGST"),
    ]
    assert option("cgst_sgst_9_9").components == (gst.GstComponent("CGST", D(9)), gst.GstComponent("SGST/UTGST", D(9)))


@pytest.mark.parametrize("key", [None, "", "gst_99", "GST_18"])
def test_unknown_or_missing_key(key):
    with pytest.raises(gst.InvalidGstOption):
        option(key)


# ---------------------------------------------------------------- calculation


@pytest.mark.parametrize(
    "key, expected, total",
    [
        ("gst_5", [("GST", D(5), D("500.00"))], D("10500.00")),
        ("gst_12", [("GST", D(12), D("1200.00"))], D("11200.00")),
        ("gst_18", [("GST", D(18), D("1800.00"))], D("11800.00")),
        ("cgst_sgst_9_9", [("CGST", D(9), D("900.00")), ("SGST/UTGST", D(9), D("900.00"))], D("11800.00")),
    ],
)
def test_taxable_10000(key, expected, total):
    rows_, _, payable = taxes("10000.00", key)
    assert rows_ == expected
    assert payable == total


def test_each_component_is_rounded_on_its_own():
    rows_, g, payable = taxes("100.05", "gst_18")
    assert rows_ == [("GST", D(18), D("18.01"))]  # 18.009
    assert (g, payable) == (D("18.01"), D("118.06"))

    rows_, g, payable = taxes("100.05", "cgst_sgst_9_9")
    assert rows_ == [("CGST", D(9), D("9.00")), ("SGST/UTGST", D(9), D("9.00"))]  # 9.0045 each
    assert (g, payable) == (D("18.00"), D("118.05"))  # a paisa less than 18%: expected


@pytest.mark.parametrize("key", ["gst_5", "gst_12", "gst_18", "cgst_sgst_9_9"])
def test_zero_taxable(key):
    rows_, g, payable = taxes("0", key)
    assert [amount for _, _, amount in rows_] == [D("0.00")] * len(option(key).components)
    assert (g, payable) == (D("0.00"), D("0.00"))


def test_no_components_is_without_gst():
    m = compute([D("10000")], (), cfg().advance_pct)
    assert (m.taxes, m.gst, m.payable) == ((), D("0.00"), D("10000.00"))


def test_amounts_are_decimal():
    rows_, g, payable = taxes("100.05", "gst_12")
    assert all(isinstance(a, Decimal) for _, _, a in rows_) and isinstance(g, Decimal) and isinstance(payable, Decimal)


# ---------------------------------------------------------------- PDF rows


def test_pdf_one_row_per_component():
    doc = sogat_doc(billing_type="with_gst", gst_option="cgst_sgst_9_9", payments=[],
                    taxes=[{"name": "CGST", "rate": "9", "amount": "13320.00"},
                           {"name": "SGST/UTGST", "rate": "9", "amount": "13320.00"}])
    lines = pdf_lines(render(doc, cfg()))
    at = {b: t for b, t in lines}
    # TOTAL moves up two lines; the rows stack in order, the last on the old TOTAL line (703.89).
    assert any(abs(b - (703.89 - 2 * L.GST_LIFT)) < 0.2 and t.startswith("TOTAL:") and t.endswith("148000") for b, t in lines)
    assert any(abs(b - 687.89) < 0.2 and t == "CGST @ 9%:13320" for b, t in at.items())
    assert any(abs(b - 703.89) < 0.2 and t == "SGST/UTGST @ 9%:13320" for b, t in at.items())
    assert "174640" in at.values()  # SUB TOTAL pill
    assert any(t.endswith("Note:-  18%  gst has been added to the total") for t in at.values())


@pytest.mark.parametrize("key, row, note", [("gst_5", "GST @ 5%:7400", "5%"), ("gst_12", "GST @ 12%:17760", "12%")])
def test_pdf_single_rate(key, row, note):
    doc = sogat_doc(billing_type="with_gst", gst_option=key, payments=[],
                    taxes=[{"name": "GST", "rate": key.split("_")[1], "amount": row.split(":")[1]}])
    texts = [t for _, t in pdf_lines(render(doc, cfg()))]
    assert row in texts
    assert any(t.endswith(f"Note:-  {note}  gst has been added to the total") for t in texts)


def test_legacy_with_gst_invoice_reprints_at_18():
    """A With GST invoice saved before the selector has no tax rows: it was charged 18%."""
    texts = [t for _, t in pdf_lines(render(sogat_doc(billing_type="with_gst", payments=[]), cfg()))]
    assert "GST @ 18%:26640" in texts


# ---------------------------------------------------------------- API


def with_gst(client, key=..., **changes):
    body = invoice_body([k1_line(client)], billing_type="with_gst", **changes)
    if key is not ...:
        body["gst_option"] = key
    return body


@pytest.mark.parametrize("key", [..., None, "gst_99"])
def test_api_rejects_missing_or_invalid_key(client, auth, key):
    r = client.post("/api/invoices", json=with_gst(client, key), headers=auth)
    assert r.status_code == 400, r.text
    err = r.json()["error"]
    assert err["code"] == "INVALID_GST_OPTION" and err["details"]["field"] == "gst_option"
    assert "gst_18" in err["details"]["allowed"]


def test_api_rejects_invalid_key_without_storage(unsaved):
    c, auth = unsaved
    r = c.post("/api/invoices", json=with_gst(c, "gst_99", bill_no=19), headers=auth)
    assert r.status_code == 400 and r.json()["error"]["code"] == "INVALID_GST_OPTION"


def test_api_without_gst_needs_no_key(client, auth):
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    assert r.status_code == 201


def test_api_stores_option_and_rows_and_reprints_them(app, client, auth):
    # k1_line: 350 × 75 = 26250.00
    r = client.post("/api/invoices", json=with_gst(client, "cgst_sgst_9_9"), headers=auth)
    assert r.status_code == 201, r.text
    [row], _ = rows(app)
    assert row.gst == {"option": "cgst_sgst_9_9", "taxes": [
        {"name": "CGST", "rate": "9", "amount": "2362.50"},
        {"name": "SGST/UTGST", "rate": "9", "amount": "2362.50"}]}
    assert (str(row.gst_amount), str(row.payable)) == ("4725.00", "30975.00")
    printed = [t for _, t in pdf_lines(r.content)]
    assert "CGST @ 9%:2362.50" in printed and "SGST/UTGST @ 9%:2362.50" in printed

    # Reprint and a later payment render the stored rows, not today's config.
    assert client.get("/api/invoices/19/pdf", headers=auth).content == r.content
    pay = {"amount": "1000", "date": "2026-09-30", "mode": "upi"}
    r2 = client.post("/api/invoices/19/payments", json=pay, headers=auth)
    assert r2.status_code in (200, 201), r2.text
    assert "SGST/UTGST @ 9%:2362.50" in [t for _, t in pdf_lines(r2.content)]
    assert client.get("/api/invoices/19", headers=auth).json()["gst"]["option"] == "cgst_sgst_9_9"


@pytest.mark.parametrize("mode", ["unpaid", "paid"])
def test_api_print_unpaid_and_paid(client, auth, mode):
    payments = [{"amount": "1000", "date": "2026-09-30", "mode": "upi", "note": None}] if mode == "paid" else None
    r = client.post("/api/invoices", json=with_gst(client, "gst_18", print_mode=mode, payments=payments), headers=auth)
    assert r.status_code == 201, r.text
    assert "GST @ 18%:4725" in [t for _, t in pdf_lines(r.content)]
