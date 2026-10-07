"""Customisations typed in the cart: free ones print under CUSTOMISATIONS:- on every document;
charged ones are their own rows under the article (per unit or once per order) and count in
the totals and GST of the quotation, the Non-GST invoice and the GST invoice."""
from app.products import products

from .test_invoice_api import app, auth, client, invoice_body, k1_line, token  # noqa: F401
from .test_quotation_gst import gst_body, pdf_text, quotation_body


def charged(parent, basis="per_unit", price="12.50", title="Gold foil logo on lid (customisation)", **changes):
    return {
        "id": f"c-{basis}",
        "source": "customisation",
        "parent_id": parent["id"],
        "charge_basis": basis,
        "calc_request": None,
        "title": title,
        "specs": [{"label": "For", "value": parent["title"], "emphasis": False}],
        "customisations": [],
        "quantity": parent["quantity"] if basis == "per_unit" else 1,
        "unit_label": parent["unit_label"] if basis == "per_unit" else "order",
        "middle": {"kind": "none"},
        "catalogue_unit_price": None,
        "unit_price": price,
        "warnings": [],
        **changes,
    }


def cart(client):  # noqa: F811
    """350 rigid boxes at 75 with a free customisation, +12.50 per box and +1,500 for the order."""
    parent = k1_line(client, customisations=[{"label": None, "value": "Ribbon pull tab", "emphasis": False}])
    return [parent, charged(parent), charged(parent, "per_order", "1500", title="Custom die (customisation)")]


# 350 x 75 = 26,250 + 350 x 12.50 = 4,375 + 1,500 = 32,125
SUBTOTAL = "32125"


def test_non_gst_invoice_counts_and_prints_customisations(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=invoice_body(cart(client)), headers=auth)
    assert r.status_code == 201, r.text
    text = pdf_text(r.content)
    assert f"SUB TOTAL : {SUBTOTAL}" in text
    for expected in ("CUSTOMISATIONS:-", "RIBBON PULL TAB", "GOLD FOIL LOGO ON LID (CUSTOMISATION)", "CUSTOM DIE (CUSTOMISATION)"):
        assert expected in text, expected
    stored = client.get(f"/api/invoices/{r.headers['x-bill-no']}", headers=auth).json()
    assert stored["total"] == f"{SUBTOTAL}.00"
    assert [l["source"] for l in stored["lines"]] == ["catalogue", "customisation", "customisation"]
    assert stored["lines"][1]["charge_basis"] == "per_unit"
    # A re-download renders from the stored record, the same bytes.
    again = client.get(f"/api/invoices/{r.headers['x-bill-no']}/pdf", headers=auth)
    assert again.status_code == 200 and again.content == r.content


def test_quotation_keeps_customisations_under_their_article(client, auth):  # noqa: F811
    lines = cart(client) + [k1_line(client)]
    text = pdf_text(client.post("/api/invoices", json=quotation_body(lines), headers=auth).content)
    assert "1.CUSTOMISED RIGID BOX PRINTING" in text and "2.CUSTOMISED RIGID BOX PRINTING" in text
    assert "GOLD FOIL LOGO ON LID (CUSTOMISATION)" in text and "2.GOLD FOIL" not in text
    assert "CUSTOMISATIONS:-" in text and "RIBBON PULL TAB" in text


def test_gst_invoice_taxes_customisations(client, auth):  # noqa: F811
    r = client.post("/api/invoices", json=gst_body(cart(client), "inter_18"), headers=auth)
    assert r.status_code == 201, r.text
    text = pdf_text(r.content)
    # 32,125.00 + IGST 18% 5,782.50 = 37,907.50
    for expected in ("SUB-TOTAL : 32,125.00", "IGST Tax (18%) : 5,782.50", "Total : 37,907.50",
                     "CUSTOMISATIONS:-", "RIBBON PULL TAB", "GOLD FOIL LOGO ON LID (CUSTOMISATION)"):
        assert expected in text, expected


def test_customisation_must_follow_its_article(client, auth):  # noqa: F811
    parent, per_unit, _ = cart(client)
    for lines, message in (
        ([per_unit, parent], "must follow the article"),
        ([parent, {**per_unit, "parent_id": "nope"}], "must follow the article"),
        ([parent, {**per_unit, "charge_basis": None}], "per unit or per order"),
        ([parent, {**per_unit, "quantity": 100}], "quantity must be the article's (350)"),
        ([{**parent, "charge_basis": "per_unit"}], "Only customisation lines"),
    ):
        r = client.post("/api/invoices", json=invoice_body(lines), headers=auth)
        assert r.status_code == 422, (message, r.text)
        assert message in r.json()["error"]["message"], r.text


def test_customisation_on_a_custom_item(client, auth):  # noqa: F811
    item = {**charged({"id": "x", "title": "Hand-made hamper", "quantity": 10, "unit_label": "pcs"}),
            "id": "x", "source": "custom", "parent_id": None, "charge_basis": None, "title": "Hand-made hamper",
            "specs": [], "unit_price": "400"}
    extra = charged({"id": "x", "title": "Hand-made hamper", "quantity": 10, "unit_label": "pcs"}, price="25")
    r = client.post("/api/invoices", json=invoice_body([item, extra]), headers=auth)
    assert r.status_code == 201, r.text
    assert "SUB TOTAL : 4250" in pdf_text(r.content)  # 10 x 400 + 10 x 25


def test_production_lists_customisations_under_the_product():
    lines = [{"id": "p", "source": "catalogue", "title": "Rigid box", "quantity": 350, "unit_label": "boxes", "specs": []},
             {"id": "c", "source": "customisation", "parent_id": "p", "title": "Gold foil (customisation)"}]
    [product] = products(lines)
    assert product["title"] == "Rigid box" and product["addons"] == ["Gold foil (customisation)"]
