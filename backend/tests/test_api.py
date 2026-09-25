"""M4: every endpoint and every error code in BRD section 7."""
import dataclasses
import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import RIGID_TB

TOKEN = "test-admin-token"


@pytest.fixture
def make_client(settings):
    def _make(**overrides):
        s = dataclasses.replace(settings, admin_token=TOKEN, rate_limit_per_minute=0, **overrides)
        return TestClient(create_app(s))

    return _make


@pytest.fixture
def client(make_client):
    return make_client()


def calc(client, **body):
    return client.post("/api/calculate", json=body)


def err(response):
    return response.json()["error"]["code"]


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["counts"]["tier_rows"] == 950 and body["counts"]["items"] == 233
    assert body["counts"]["open_flags"] == 27


def test_catalog_has_no_prices(client):
    body = client.get("/api/catalog").json()
    assert len(body["categories"]) == 14
    rigid = next(p for c in body["categories"] for p in c["products"] if p["id"] == "rigid_boxes")
    assert len({i["size"] for i in rigid["items"]}) == 20
    assert {i["option_1"] for i in rigid["items"]} == {"Top-Bottom", "Magnetic / Slider"}
    assert rigid["option_labels"] == {"option_1": "Box type"}
    assert rigid["min_qty"] == 100 and rigid["production_time"] == "10-12 days"
    for product in (p for c in body["categories"] for p in c["products"]):
        assert all(set(b) == {"qty_from", "label"} for b in product["breakpoints"])
        for item in product["items"]:
            assert "price" not in item and "tiers" not in item
            assert all(set(b) == {"qty_from", "label"} for b in item["breakpoints"])


def test_calculate_standard(client):
    r = calc(client, item_id=RIGID_TB, quantity=350)
    assert r.status_code == 200
    assert r.json()["data"]["totals"]["grand_total"] == "30975.00"


def test_calculate_custom_matches_brd_example(client):
    r = calc(
        client,
        product_id="rigid_boxes",
        item_id=None,
        options={"option_1": "Top-Bottom"},
        custom_dimensions={"length": 3.5, "width": 3.5, "height": 2, "unit": "in"},
        quantity=300,
        addons=[],
        billing_type="gst",
    )
    body = r.json()
    assert r.status_code == 200 and body["status"] == "success"
    assert body["data"]["pricing"]["unit_price"] == "88.50"
    assert body["data"]["production_time"] == "10-12 days"


def test_manual_quote_codes(client):
    r = calc(client, item_id="sticker_sheets/paper", quantity=1200)
    assert r.status_code == 200 and r.json()["status"] == "manual_quote" and r.json()["reason"] == "MANUAL_QUOTE"
    r = calc(client, product_id="rigid_boxes", options={"option_1": "Top-Bottom"},
             custom_dimensions={"length": 20, "width": 20, "height": 5}, quantity=500)
    assert r.status_code == 200 and r.json()["reason"] == "CUSTOM_OUT_OF_RANGE"


@pytest.mark.parametrize(
    "body",
    [
        {"quantity": 10},  # neither item_id nor custom_dimensions
        {"item_id": RIGID_TB, "custom_dimensions": {"length": 1, "width": 1, "height": 1}, "product_id": "rigid_boxes", "quantity": 10},
        {"item_id": RIGID_TB, "quantity": 0},
        {"item_id": RIGID_TB, "quantity": "abc"},
        {"item_id": RIGID_TB, "quantity": 10, "billing_type": "cash"},
        {"product_id": "rigid_boxes", "options": {"option_1": "Top-Bottom"}, "custom_dimensions": {"length": 61, "width": 1, "height": 1}, "quantity": 10},
        {"product_id": "rigid_boxes", "options": {"option_1": "Top-Bottom"}, "custom_dimensions": {"length": 0, "width": 1, "height": 1}, "quantity": 10},
        {"product_id": "rigid_boxes", "options": {"option_1": "Top-Bottom"}, "custom_dimensions": {"length": 1.234, "width": 1, "height": 1}, "quantity": 10},
        {"product_id": "rigid_boxes", "options": {"option_1": "Top-Bottom"}, "custom_dimensions": {"length": 1, "width": 1}, "quantity": 10},
    ],
)
def test_validation_error(client, body):
    r = calc(client, **body)
    assert r.status_code == 422 and err(r) == "VALIDATION_ERROR", r.json()
    assert set(r.json()["error"]) == {"code", "message", "details"}


def test_unknown_item(client):
    assert err(calc(client, item_id="rigid_boxes/99x99x99-in/top-bottom", quantity=10)) == "UNKNOWN_ITEM"
    r = calc(client, product_id="nope", custom_dimensions={"length": 1, "width": 1, "height": 1}, quantity=10)
    assert r.status_code == 404 and err(r) == "UNKNOWN_ITEM"
    r = calc(client, product_id="rigid_boxes", options={"option_1": "Velvet"},
             custom_dimensions={"length": 4, "width": 4, "height": 2}, quantity=10)
    assert r.status_code == 404 and err(r) == "UNKNOWN_ITEM"


def test_custom_not_supported(client):
    r = calc(client, product_id="vc_standard", custom_dimensions={"length": 3, "width": 2}, quantity=500)
    assert r.status_code == 422 and err(r) == "CUSTOM_NOT_SUPPORTED"


def _policy_client(make_client, tmp_path, settings, **defaults):
    config = settings.config_file.read_text(encoding="utf-8")
    for key, value in defaults.items():
        config = config.replace(f"  {key}: ", f"  {key}: {value}  # was ", 1)
    path = tmp_path / "products.yaml"
    path.write_text(config, encoding="utf-8")
    return make_client(config_file=path)


def test_below_min_blocked(make_client, tmp_path, settings):
    client = _policy_client(make_client, tmp_path, settings, below_min_policy="block")
    r = calc(client, item_id=RIGID_TB, quantity=60)
    assert r.status_code == 422 and err(r) == "BELOW_MIN"


def test_price_blocked(make_client, tmp_path, settings):
    client = _policy_client(make_client, tmp_path, settings, flagged_price_policy="block")
    r = calc(client, item_id="rigid_boxes/8x10x2.5-in/magnetic-slider", quantity=1200)
    assert r.status_code == 422 and err(r) == "PRICE_BLOCKED"


def test_data_not_loaded(make_client, tmp_path):
    client = make_client(data_file=tmp_path / "missing.xlsx")
    assert client.get("/api/health").json()["status"] == "error"
    r = calc(client, item_id=RIGID_TB, quantity=10)
    assert r.status_code == 503 and err(r) == "DATA_NOT_LOADED"
    assert client.get("/api/catalog").status_code == 503


def test_rate_limit(settings):
    client = TestClient(create_app(dataclasses.replace(settings, rate_limit_per_minute=3)))
    statuses = [calc(client, item_id=RIGID_TB, quantity=100).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]


def test_reload_needs_token(client):
    assert client.post("/api/admin/reload").status_code == 401
    assert client.post("/api/admin/reload", headers={"X-Admin-Token": "wrong"}).status_code == 401
    r = client.post("/api/admin/reload", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200 and r.json()["items"] == 233


def test_reload_disabled_without_token(settings):
    client = TestClient(create_app(dataclasses.replace(settings, admin_token=None)))
    assert client.post("/api/admin/reload", headers={"X-Admin-Token": "x"}).status_code == 403


def test_failed_reload_keeps_last_good_data(make_client, tmp_path, settings):
    data = tmp_path / "prices.xlsx"
    shutil.copy(settings.data_file, data)
    client = make_client(data_file=data)
    data.write_bytes(b"not a workbook")
    r = client.post("/api/admin/reload", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 422 and err(r) == "RELOAD_FAILED"
    assert calc(client, item_id=RIGID_TB, quantity=350).json()["data"]["totals"]["subtotal"] == "26250.00"


def test_cors_is_limited_to_frontend_origin(client, settings):
    allowed = settings.cors_origins[0]
    r = client.options("/api/calculate", headers={"Origin": allowed, "Access-Control-Request-Method": "POST"})
    assert r.headers.get("access-control-allow-origin") == allowed
    r = client.options("/api/calculate", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers


def test_rate_limit_keys_on_forwarded_ip_behind_a_proxy(settings):
    s = dataclasses.replace(settings, rate_limit_per_minute=1, trust_proxy_headers=True)
    client = TestClient(create_app(s))
    first = client.post("/api/calculate", json={"item_id": RIGID_TB, "quantity": 100}, headers={"x-real-ip": "1.1.1.1"})
    other = client.post("/api/calculate", json={"item_id": RIGID_TB, "quantity": 100}, headers={"x-real-ip": "2.2.2.2"})
    again = client.post("/api/calculate", json={"item_id": RIGID_TB, "quantity": 100}, headers={"x-real-ip": "1.1.1.1"})
    assert (first.status_code, other.status_code, again.status_code) == (200, 200, 429)


def test_forwarded_ip_ignored_unless_trusted(settings):
    client = TestClient(create_app(dataclasses.replace(settings, rate_limit_per_minute=1)))
    statuses = [
        client.post("/api/calculate", json={"item_id": RIGID_TB, "quantity": 100}, headers={"x-real-ip": ip}).status_code
        for ip in ("1.1.1.1", "2.2.2.2")
    ]
    assert statuses == [200, 429]
