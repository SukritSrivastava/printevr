"""BRD-cart-invoice 11.3 (K1-K6): invoice line drafts from the calculator's golden cases."""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.invoice.from_quote import quote_with_drafts, standard_size
from app.invoice.money import line_subtotal
from app.main import create_app
from app.models import CalculateRequest

from .conftest import RIGID_TB
from .invoice_helpers import cfg

VC_300_GM_DOUBLE = "vc_standard/300-gsm/gloss-matte/double-side"


@pytest.fixture
def drafts(catalogue):
    def _drafts(**body):
        result = quote_with_drafts(catalogue, CalculateRequest(**body), cfg().unit_plurals)
        return result, result["data"].get("invoice_lines")

    return _drafts


def subtotal(line) -> Decimal:
    return line_subtotal(Decimal(str(line["quantity"])), Decimal(line["unit_price"]))


def test_k1_rigid_box(drafts):
    _, lines = drafts(item_id=RIGID_TB, quantity=350)
    assert len(lines) == 1
    line = lines[0]
    assert line["title"] == "Customised rigid box printing"
    assert line["specs"] == [
        {"label": "Size", "value": "3*3*2 in (LxWxH)", "emphasis": True},
        {"label": "Box type", "value": "Top-Bottom", "emphasis": False},
    ]
    assert line["quantity"] == 350 and line["unit_label"] == "boxes"
    assert line["unit_price"] == line["catalogue_unit_price"] == "75.00"
    assert line["middle"] == {"kind": "none"} and line["customisations"] == []
    assert subtotal(line) == Decimal("26250.00")


def test_k2_minimum_order_billed(drafts):
    _, lines = drafts(item_id=RIGID_TB, quantity=60)
    assert lines[0]["quantity"] == 100
    assert "MOQ_APPLIED" in [w["code"] for w in lines[0]["warnings"]]


def test_k3_per_unit_addon_in_price(drafts):
    _, lines = drafts(item_id=VC_300_GM_DOUBLE, quantity=1200, addons=["round_edges"])
    assert len(lines) == 1
    assert lines[0]["unit_price"] == "6.00"
    assert {"label": "Add-on", "value": "Round edges", "emphasis": False} in lines[0]["specs"]
    assert lines[0]["unit_label"] == "cards"


def test_k4_per_order_addon_is_own_line(drafts):
    result, lines = drafts(item_id="butter_paper/29x9-in", quantity=1500, addons=["multicolour"])
    assert len(lines) == 2
    main, addon = lines
    assert (main["quantity"], main["unit_price"], subtotal(main)) == (1500, "5.50", Decimal("8250.00"))
    assert addon["title"] == "Multicolour print (add-on)"
    assert addon["specs"] == [{"label": "For", "value": main["title"], "emphasis": False}]
    assert (addon["quantity"], addon["unit_label"], addon["source"]) == (1, "order", "addon")
    assert subtotal(addon) == Decimal("1000.00")
    assert subtotal(main) + subtotal(addon) == Decimal(result["data"]["totals"]["subtotal"]) == Decimal("9250.00")


def test_k5_custom_size(drafts):
    body = dict(
        product_id="rigid_boxes",
        options={"option_1": "Top-Bottom"},
        custom_dimensions={"length": "3.50", "width": 3.5, "height": 2, "unit": "in"},
        quantity=300,
    )
    _, lines = drafts(**body)
    line = lines[0]
    assert line["specs"][0] == {"label": "Size", "value": "3.5*3.5*2 in (LxWxH)", "emphasis": True}
    assert line["specs"][1] == {"label": "Box type", "value": "Top-Bottom", "emphasis": False}
    assert line["unit_price"] == "88.50" and subtotal(line) == Decimal("26550.00")
    assert "CUSTOM_ESTIMATE" in [w["code"] for w in line["warnings"]]


def test_k6_manual_quote_has_no_lines(drafts):
    result, lines = drafts(
        product_id="rigid_boxes",
        options={"option_1": "Top-Bottom"},
        custom_dimensions={"length": 20, "width": 20, "height": 5},
        quantity=500,
    )
    assert result["status"] == "manual_quote" and lines is None


def test_standard_size_formats():
    assert standard_size("7 × 9 × 3 in (H × L × S)", "bag") == "7*9*3 in (HxLxS)"
    assert standard_size("29 × 9 in", "flat") == "29*9 in (LxW)"
    assert standard_size("2.5 × 1.5 in", "none") == "2.5*1.5 in"
    assert standard_size("300 GSM", "none") == "300 GSM"


def test_outdoor_size_from_ui_dimensions(drafts, catalogue):
    item = catalogue.products["outdoor_branding"].items[0]
    _, lines = drafts(item_id=item.id, quantity=60, outdoor={"width": 6, "height": 5, "pieces": 2})
    assert lines[0]["specs"][0] == {"label": "Size", "value": "6*5 ft, 2 pcs", "emphasis": True}
    assert lines[0]["specs"][1]["label"] == "Material"
    assert lines[0]["unit_label"] == "sq ft"


def test_every_product_has_an_invoice_title(catalogue):
    assert len(catalogue.products) == 27
    for p in catalogue.products.values():
        assert p.invoice_title and p.invoice_title.startswith("Customised ") and p.invoice_title.endswith(" printing")


def test_calculate_endpoint_adds_invoice_lines_only():
    client = TestClient(create_app())
    r = client.post("/api/calculate", json={"item_id": RIGID_TB, "quantity": 350})
    body = r.json()
    assert r.status_code == 200
    assert body["data"]["totals"]["subtotal"] == "26250.00"  # existing fields unchanged
    assert body["data"]["invoice_lines"][0]["unit_price"] == "75.00"
