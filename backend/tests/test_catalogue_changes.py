"""Catalogue changes of 2026-10-03 (config/products.yaml).

- Customised Paper Printing is withdrawn (`active: false`): not offered, quoted or printable on
  a new invoice, while invoices already issued with it still reprint from their stored lines.
- The three mailer bags (courier, frosted, kraft mailer) need at least 300 (`min_qty: 300`,
  `below_min_policy: block`). The sheet's "200 pcs" tier (200-499) keeps its price and now
  covers 300-499. No other product changes.
"""
import copy
import dataclasses
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.invoice.from_quote import quote_with_drafts
from app.invoice.store import Base, InvoiceRow
from app.loader import LoaderError
from app.main import create_app
from app.models import CalculateRequest
from app.settings import get_settings

from .invoice_helpers import cfg, chars, lines_by_baseline, open_pdf

PASSCODE = "print-shop-1234"
BAGS = ("courier_bags", "frosted_bags", "kraft_mailer_bags")
UNTOUCHED = (
    "ribbon_single_colour", "labels_silk", "outdoor_branding", "vc_standard", "vc_raised_foil", "vc_textured",
    "vc_spot_uv", "id_cards", "butter_paper", "sticker_sheets", "carry_bags_small", "carry_bags_medium",
    "carry_bags_large",
)
PAPER_ITEM = "paper_printing/90-120-gsm"


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    db = tmp_path_factory.mktemp("catalogue_changes") / "invoices.db"
    settings = dataclasses.replace(
        get_settings(),
        staff_passcode=PASSCODE,
        secret_key="test-secret",
        database_url=f"sqlite:///{db.as_posix()}",
        rate_limit_per_minute=0,
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    c = TestClient(app)
    store = app.state.invoices["get_store"]()
    Base.metadata.drop_all(store.engine)
    Base.metadata.create_all(store.engine)
    return c


@pytest.fixture(scope="module")
def auth(app):
    token = TestClient(app).post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def calc(client, **body):
    return client.post("/api/calculate", json={"options": {}, "addons": [], "billing_type": "gst", **body})


def catalog_products(client) -> dict[str, dict]:
    return {p["id"]: p for c in client.get("/api/catalog").json()["categories"] for p in c["products"]}


def invoice_body(lines):
    return {
        "invoice_date": "2026-10-03",
        "document_type": "invoice",
        "bill_type": "non_gst",
        "customer": {"business_name": "Test Store", "address": "Sector 17, Chandigarh", "phone": "+91 98765 43210"},
        "lines": lines,
        "print_mode": "unpaid",
    }


def line_for(client, calc_request):
    draft = client.post("/api/calculate", json=calc_request).json()["data"]["invoice_lines"][0]
    return {**draft, "id": str(uuid.uuid4()), "calc_request": calc_request}


# ---------------------------------------------------------------- 300 minimum on the bags


@pytest.mark.parametrize("product_id", BAGS)
def test_bags_need_300_in_the_calculator(catalogue, quote, product_id):
    product = catalogue.products[product_id]
    assert product.below_min_policy == "block"
    for item in product.items:
        assert item.breakpoints[0] == 300
        for qty in (1, 200, 299):
            with pytest.raises(Exception) as exc:
                quote(item_id=item.id, quantity=qty)
            assert exc.value.code == "BELOW_MIN" and exc.value.details == {"minimum": 300}
        ok = quote(item_id=item.id, quantity=300)
        assert ok["status"] == "success"
        assert ok["data"]["quantity"]["billed"] == 300
        assert ok["data"]["pricing"]["tier_applied"]["range"].startswith("300-")
        assert ok["data"]["tier_schedule"]["min_qty"] == 300
        assert ok["data"]["tier_schedule"]["tiers"][0]["qty_from"] == 300


@pytest.mark.parametrize("product_id", BAGS)
def test_bag_prices_are_unchanged(catalogue, sheet, product_id):
    product = catalogue.products[product_id]
    rows = {r.row: r for r in sheet[0] if r.product == product.name}
    for item in product.items:
        for tier in item.tiers:
            assert tier.price == Decimal(str(rows[tier.row].price))
        # The sheet's first tier (200) now starts at 300 with the same price and a matching label.
        first = rows[item.tiers[0].row]
        assert int(first.qty_from) == 200 and item.tiers[0].label == "300 pcs"


def test_custom_size_bags_need_300_too(quote):
    with pytest.raises(Exception) as exc:
        quote(product_id="courier_bags", options={}, custom_dimensions={"length": 7, "width": 9}, quantity=299)
    assert exc.value.code == "BELOW_MIN"
    assert quote(product_id="courier_bags", options={}, custom_dimensions={"length": 7, "width": 9}, quantity=300)["status"] == "success"


@pytest.mark.parametrize("product_id", BAGS)
def test_api_rejects_bags_under_300(client, product_id):
    product = catalog_products(client)[product_id]
    assert product["min_qty"] == 300 and product["below_min_policy"] == "block"
    assert product["breakpoints"][0] == {"qty_from": 300, "label": "300 pcs"}
    item_id = product["items"][0]["id"]
    r = calc(client, item_id=item_id, quantity=299)
    assert r.status_code == 422 and r.json()["error"]["code"] == "BELOW_MIN"
    assert r.json()["error"]["details"] == {"minimum": 300}
    assert calc(client, item_id=item_id, quantity=300).status_code == 200


def test_invoice_with_a_bag_under_300_is_refused(client, auth):
    request = {"item_id": "courier_bags/6x8-in", "quantity": 300, "options": {}, "addons": [], "billing_type": "gst"}
    line = line_for(client, request)
    line["calc_request"] = {**request, "quantity": 250}
    line["quantity"] = 250
    r = client.post("/api/invoices", json=invoice_body([line]), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "LINE_NOT_PRICEABLE"
    assert "Minimum order is 300" in r.json()["error"]["message"]
    ok = client.post("/api/invoices", json=invoice_body([line_for(client, request)]), headers=auth)
    assert ok.status_code == 201, ok.text


def test_min_qty_cannot_swallow_the_next_tier(sheet, rebuild):
    config = copy.deepcopy(sheet[2])
    next(p for p in config["products"] if p["id"] == "courier_bags")["min_qty"] = 500
    with pytest.raises(LoaderError, match="min_qty 500"):
        rebuild(config=config)


def test_other_products_are_untouched(client, catalogue, sheet):
    products = catalog_products(client)
    first_tier = {}
    for r in sheet[0]:
        if r.tier_label.lower() != "sample cost":
            first_tier[r.product] = min(first_tier.get(r.product, 10**9), int(r.qty_from))
    for product_id in UNTOUCHED:
        p = catalogue.products[product_id]
        assert p.active and p.below_min_policy == "bill_at_min", product_id
        assert products[product_id]["min_qty"] == first_tier[p.name], product_id
    # Small / medium / large carry bags keep their 100 minimum, billed at the minimum below it.
    assert products["carry_bags_small"]["min_qty"] == 100


# ---------------------------------------------------------------- Customised Paper Printing withdrawn


def test_paper_printing_is_not_offered(client, catalogue):
    assert catalogue.products["paper_printing"].active is False
    assert "paper_printing" not in catalog_products(client)
    names = [p["name"] for c in client.get("/api/catalog").json()["categories"] for p in c["products"]]
    assert not any("Paper Printing" in n for n in names)


def test_paper_printing_cannot_be_quoted(client):
    r = calc(client, item_id=PAPER_ITEM, quantity=100)
    assert r.status_code == 422 and r.json()["error"]["code"] == "PRODUCT_WITHDRAWN"


def _paper_line(sheet, rebuild):
    """A paper printing line as the cart made it before the product was withdrawn."""
    config = copy.deepcopy(sheet[2])
    next(p for p in config["products"] if p["id"] == "paper_printing")["active"] = True
    request = CalculateRequest(item_id=PAPER_ITEM, quantity=100)
    result = quote_with_drafts(rebuild(config=config), request, cfg().unit_plurals)
    draft = result["data"]["invoice_lines"][0]
    return {**draft, "id": str(uuid.uuid4()), "calc_request": request.model_dump(mode="json")}


def test_paper_printing_cannot_go_on_a_new_invoice(client, auth, sheet, rebuild):
    r = client.post("/api/invoices", json=invoice_body([_paper_line(sheet, rebuild)]), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "LINE_NOT_PRICEABLE"
    assert "no longer offered" in r.json()["error"]["message"]


def test_old_invoice_with_paper_printing_still_reprints(app, client, auth, sheet, rebuild):
    line = _paper_line(sheet, rebuild)
    now = datetime.now(timezone.utc)
    with app.state.invoices["get_store"]().session() as s:
        s.add(
            InvoiceRow(
                bill_no=77, invoice_date=now.date(), billing_type="without_gst", business_name="Old Customer",
                customer={"business_name": "Old Customer", "address": "Sector 22, Chandigarh", "phone": "9876543210"},
                lines=[line], payments=[], total=Decimal("3500.00"), gst_amount=Decimal("0.00"), payable=Decimal("3500.00"),
                received=Decimal("0.00"), status="unpaid", version=1, created_at=now, updated_at=now,
            )
        )
        s.commit()
    r = client.get("/api/invoices/77/pdf", headers=auth)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    with open_pdf(r.content) as pdf:
        text = ["".join(c["text"] for c in l) for l in lines_by_baseline(chars(pdf.pages[0]))]
    assert any("PAPER PRINTING" in t for t in text)
    assert client.get("/api/invoices/77", headers=auth).json()["lines"][0]["title"] == line["title"]
