"""BRD-cart-invoice 11.4 (A1-A11): invoice API, staff auth and storage."""
import dataclasses
import threading
import uuid

import pytest
from fastapi.testclient import TestClient

from app.invoice.store import Base, InvoiceEvent, InvoiceRow
from app.main import create_app
from app.settings import get_settings

from .conftest import RIGID_TB

PASSCODE = "print-shop-1234"
SLAB_KEYS = [["intra_5", "intra_12", "intra_18"], ["inter_5", "inter_12", "inter_18"]]


def slab_keys(groups: list[dict]) -> list[list[str]]:
    return [[s["key"] for s in g["slabs"]] for g in groups]


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    db = tmp_path_factory.mktemp("invoices") / "invoices.db"
    settings = dataclasses.replace(
        get_settings(),
        staff_passcode=PASSCODE,
        secret_key="test-secret",
        database_url=f"sqlite:///{db.as_posix()}",
        cors_origins=["http://localhost:5173"],
    )
    return create_app(settings)


@pytest.fixture
def client(app):
    c = TestClient(app)
    c.get("/api/health")
    store = app.state.invoices["store"]
    if store is not None:
        Base.metadata.drop_all(store.engine)
        Base.metadata.create_all(store.engine)
    return c


@pytest.fixture(scope="module")
def token(app):
    r = TestClient(app).post("/api/staff/login", json={"passcode": PASSCODE})
    assert r.status_code == 200, r.text
    return r.json()["token"]


@pytest.fixture
def auth(token):
    return {"Authorization": f"Bearer {token}"}


def rows(app):
    with app.state.invoices["store"].session() as s:
        return list(s.query(InvoiceRow).order_by(InvoiceRow.bill_no)), list(s.query(InvoiceEvent).order_by(InvoiceEvent.id))


def k1_line(client, **changes):
    calc_request = {"item_id": RIGID_TB, "quantity": 350, "options": {}, "addons": [], "billing_type": "gst"}
    draft = client.post("/api/calculate", json=calc_request).json()["data"]["invoice_lines"][0]
    return {**draft, "id": str(uuid.uuid4()), "calc_request": calc_request, **changes}


def invoice_body(lines, print_mode="unpaid", payments=None, **changes):
    return {
        "bill_no": None,
        "invoice_date": "2026-09-29",
        "document_type": "invoice",
        "bill_type": "non_gst",
        "customer": {"business_name": "Sogat Jutti Store", "contact_person": "Ramjot Chhokar",
                     "address": "Sector 67, Mohali, India, 160062", "phone": "+91 95010 60618"},
        "lines": lines,
        "payments": payments or [],
        "saving_amount": None,
        "print_mode": print_mode,
        **changes,
    }


def test_a1_token_required(client):
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)]))
    assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_REQUIRED"
    r = client.get("/api/invoices", headers={"Authorization": "Bearer 123.abc"})
    assert r.status_code == 401
    r = client.post("/api/invoices", json={"lines": "not even valid"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "AUTH_REQUIRED"


def test_a2_bad_passcode_and_rate_limit(app):
    c = TestClient(app, client=("10.9.9.9", 5000))
    codes = [c.post("/api/staff/login", json={"passcode": "nope"}).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    assert c.post("/api/staff/login", json={"passcode": "nope"}).json()["error"]["code"] == "RATE_LIMITED"


def test_a3_unpaid_invoice(app, client, auth):
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    assert r.status_code == 201, r.text
    assert r.content.startswith(b"%PDF")
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["x-bill-no"] == "19"
    assert r.headers["x-invoice-status"] == "unpaid"
    assert 'filename="Invoice_19_Sogat-Jutti-Store_Unpaid.pdf"' in r.headers["content-disposition"]
    invoices, events = rows(app)
    assert len(invoices) == 1 and [e.event for e in events] == ["created"]
    assert str(invoices[0].total) == "26250.00"
    assert "Sogat" not in str(events[0].detail)


def test_a4_concurrent_creates_get_consecutive_numbers(client, auth):
    body = invoice_body([k1_line(client)])
    results = []

    def go():
        results.append(client.post("/api/invoices", json=body, headers=auth))

    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(r.status_code for r in results) == [201, 201]
    assert sorted(int(r.headers["x-bill-no"]) for r in results) == [19, 20]


def test_a5_bill_no_taken(client, auth):
    assert client.post("/api/invoices", json=invoice_body([k1_line(client)], bill_no=40), headers=auth).status_code == 201
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)], bill_no=40), headers=auth)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "BILL_NO_TAKEN" and r.json()["error"]["details"]["next_bill_no"] == 41
    nxt = client.get("/api/invoices/next-bill-no", headers=auth).json()
    assert nxt["next_bill_no"] == 41 and nxt["next"] == {"quotation": 1, "non_gst": 41, "gst": 1}
    assert slab_keys(nxt["gst_slab_groups"]) == SLAB_KEYS and nxt["advance_pct"] == "80"


def test_a6_prices_changed_and_manual_edit(app, client, auth):
    stale = k1_line(client, catalogue_unit_price="70.00", unit_price="70.00")
    r = client.post("/api/invoices", json=invoice_body([stale]), headers=auth)
    assert r.status_code == 409
    err = r.json()["error"]
    assert err["code"] == "PRICES_CHANGED"
    assert err["details"]["lines"] == [{"id": stale["id"], "quantity": 350, "catalogue_unit_price": "75.00", "warnings": err["details"]["lines"][0]["warnings"]}]
    assert rows(app)[0] == []

    edited = k1_line(client, unit_price="70.00")
    r = client.post("/api/invoices", json=invoice_body([edited]), headers=auth)
    assert r.status_code == 201
    stored = rows(app)[0][0]
    assert stored.lines[0]["price_edited"] is True and str(stored.total) == "24500.00"


def test_a7_print_mode_checks(client, auth):
    line = k1_line(client)
    r = client.post("/api/invoices", json=invoice_body([line], print_mode="paid"), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"
    pay = [{"amount": "1000", "date": "2026-09-29", "mode": "upi", "note": None}]
    r = client.post("/api/invoices", json=invoice_body([line], payments=pay), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "VALIDATION_ERROR"


def test_p7_overpaid_saves_nothing(app, client, auth):
    pay = [{"amount": "30000", "date": "2026-09-29", "mode": "upi", "note": None}]
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)], print_mode="paid", payments=pay), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "OVERPAID"
    assert rows(app)[0] == []


def test_a8_record_payments(app, client, auth):
    assert client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth).status_code == 201
    r = client.post("/api/invoices/19/payments", json={"amount": "10000", "date": "2026-09-30", "mode": "cash"}, headers=auth)
    assert r.status_code == 200 and r.content.startswith(b"%PDF")
    assert r.headers["x-bill-no"] == "19" and r.headers["x-invoice-status"] == "part_paid"
    detail = client.get("/api/invoices/19", headers=auth).json()
    assert detail["version"] == 2 and detail["received"] == "10000.00" and detail["status"] == "part_paid"
    _, events = rows(app)
    assert [e.event for e in events] == ["created", "payment_added"]

    r = client.post("/api/invoices/19/payments", json={"amount": "16250", "date": "2026-10-01", "mode": "upi"}, headers=auth)
    assert r.headers["x-invoice-status"] == "paid"
    assert "Paid.pdf" in r.headers["content-disposition"]
    r = client.post("/api/invoices/19/payments", json={"amount": "1", "date": "2026-10-01", "mode": "upi"}, headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "ALREADY_PAID"
    assert client.post("/api/invoices/99/payments", json={"amount": "1", "date": "2026-10-01"}, headers=auth).status_code == 404


def test_a9_download_is_identical(client, auth):
    assert client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth).status_code == 201
    a = client.get("/api/invoices/19/pdf", headers=auth)
    b = client.get("/api/invoices/19/pdf", headers=auth)
    assert a.status_code == 200 and a.content == b.content


def test_delete_invoice(app, client, auth):
    for _ in range(2):
        assert client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth).status_code == 201
    assert client.delete("/api/invoices/19").status_code == 401
    r = client.delete("/api/invoices/19", headers=auth)
    assert r.status_code == 200 and r.json() == {"deleted": 19, "series": "non_gst"}
    assert [i["bill_no"] for i in client.get("/api/invoices", headers=auth).json()["invoices"]] == [20]
    assert client.get("/api/invoices/19", headers=auth).status_code == 404
    assert client.delete("/api/invoices/19", headers=auth).json()["error"]["code"] == "NOT_FOUND"
    invoices, events = rows(app)
    assert [i.bill_no for i in invoices] == [20]
    assert {e.bill_no for e in events} == {20}  # nothing about 19 is left


def test_a10_invoicing_disabled_without_passcode():
    app = create_app(dataclasses.replace(get_settings(), staff_passcode=None))
    c = TestClient(app)
    for method, path in (("get", "/api/invoices"), ("post", "/api/invoices"), ("get", "/api/invoices/next-bill-no")):
        r = getattr(c, method)(path)
        assert r.status_code == 503 and r.json()["error"]["code"] == "INVOICING_DISABLED"
    assert c.post("/api/staff/login", json={"passcode": "x"}).status_code == 503
    assert c.post("/api/calculate", json={"item_id": RIGID_TB, "quantity": 350}).status_code == 200


def test_a11_cors_exposes_download_headers(client, auth):
    client.post("/api/invoices", json=invoice_body([k1_line(client)]), headers=auth)
    r = client.get("/api/invoices/19/pdf", headers={**auth, "Origin": "http://localhost:5173"})
    exposed = {h.strip().lower() for h in r.headers["access-control-expose-headers"].split(",")}
    assert {"content-disposition", "x-bill-no", "x-invoice-status"} <= exposed
    pre = client.options(
        "/api/invoices",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "authorization,content-type"},
    )
    assert pre.status_code == 200 and "authorization" in pre.headers["access-control-allow-headers"].lower()


def test_list_search_and_addon_lines(client, auth):
    calc = {"item_id": "butter_paper/29x9-in", "quantity": 1500, "addons": ["multicolour"]}
    drafts = client.post("/api/calculate", json=calc).json()["data"]["invoice_lines"]
    parent = {**drafts[0], "id": "p1", "calc_request": calc}
    addon = {**drafts[1], "id": "a1", "parent_id": "p1"}
    custom = {"id": "c1", "source": "custom", "title": "Custom stickers", "quantity": 100, "unit_label": "pcs",
              "unit_price": "2.50", "catalogue_unit_price": None, "specs": [], "customisations": [], "middle": {"kind": "none"}}
    r = client.post("/api/invoices", json=invoice_body([parent, addon, custom]), headers=auth)
    assert r.status_code == 201, r.text
    client.post("/api/invoices", json=invoice_body([custom], customer={"business_name": "Other Shop", "address": "Chandigarh", "phone": "9876543210"}), headers=auth)
    listing = client.get("/api/invoices?q=sogat", headers=auth).json()
    assert listing["total"] == 1 and listing["invoices"][0]["payable"] == "9500.00"
    assert client.get("/api/invoices?q=20", headers=auth).json()["invoices"][0]["business_name"] == "Other Shop"
    assert [i["bill_no"] for i in client.get("/api/invoices", headers=auth).json()["invoices"]] == [20, 19]

    # an add-on whose price moved is caught against its parent's fresh quote
    stale_addon = {**addon, "catalogue_unit_price": "900.00"}
    r = client.post("/api/invoices", json=invoice_body([parent, stale_addon]), headers=auth)
    assert r.status_code == 409 and r.json()["error"]["details"]["lines"][0]["id"] == "a1"


def test_manual_quote_line_is_refused(client, auth):
    calc = {"product_id": "rigid_boxes", "options": {"option_1": "Top-Bottom"},
            "custom_dimensions": {"length": 20, "width": 20, "height": 5}, "quantity": 500}
    line = {**k1_line(client), "calc_request": calc}
    r = client.post("/api/invoices", json=invoice_body([line]), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["code"] == "LINE_NOT_PRICEABLE"


# ---------------------------------------------------------------- no database (Vercel without DATABASE_URL)


@pytest.fixture(scope="module")
def unsaved_app():
    return create_app(
        dataclasses.replace(get_settings(), staff_passcode=PASSCODE, secret_key="test-secret", database_url=None)
    )


@pytest.fixture
def unsaved(unsaved_app):
    c = TestClient(unsaved_app)
    token = c.post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    return c, {"Authorization": f"Bearer {token}"}


def test_settings_endpoint(app, unsaved_app):
    got = TestClient(app).get("/api/invoice-settings").json()
    assert {k: got[k] for k in ("enabled", "storage", "staff_passcode", "advance_pct", "seller_state_code")} == {
        "enabled": True, "storage": True, "staff_passcode": True, "advance_pct": "80", "seller_state_code": "04"}
    assert slab_keys(got["gst_slab_groups"]) == SLAB_KEYS
    assert got["gst_field_defaults"] == {"payment_terms": "Advance", "transport": "Self", "station": "Chandigarh"}
    assert got["print_payment_details"] is False  # GST invoices hide their Payment Terms input
    assert got["print_payment_summary"] is True  # Non-GST invoices print the advance: the cart offers the split
    assert len(got["hsn_codes"]) == 27 and set(got["hsn_codes"].values()) == {""}  # blank until filled in
    assert "gst_options" not in got
    assert TestClient(unsaved_app).get("/api/invoice-settings").json()["storage"] is False
    off = create_app(dataclasses.replace(get_settings(), staff_passcode=None, site_password=None))
    assert TestClient(off).get("/api/invoice-settings").json()["enabled"] is False


def test_site_password_alone_covers_invoicing():
    """No STAFF_PASSCODE: the site session is the only password; no staff token is asked for."""
    app = create_app(dataclasses.replace(
        get_settings(), site_password="ghost-test", session_secret="s", staff_passcode=None, secret_key=None, database_url=None))
    c = TestClient(app)
    c.get("/api/health")
    body = invoice_body([], bill_no=19)
    assert c.post("/api/invoices", json=body).status_code == 401  # no site session yet
    assert c.post("/api/login", json={"password": "ghost-test"}).status_code == 200
    settings = c.get("/api/invoice-settings").json()
    assert (settings["enabled"], settings["staff_passcode"]) == (True, False)
    r = c.post("/api/invoices", json={**body, "lines": [k1_line(c)]})
    assert r.status_code == 201 and r.content.startswith(b"%PDF")
    assert c.post("/api/staff/login", json={"passcode": "x"}).json()["error"]["code"] == "NO_STAFF_PASSCODE"


def test_unsaved_invoice_downloads_without_storing(unsaved):
    c, auth = unsaved
    r = c.post("/api/invoices", json=invoice_body([k1_line(c)], bill_no=19), headers=auth)
    assert r.status_code == 201 and r.content.startswith(b"%PDF")
    assert r.headers["x-bill-no"] == "19" and r.headers["x-invoice-status"] == "unpaid"
    assert 'filename="Invoice_19_Sogat-Jutti-Store_Unpaid.pdf"' in r.headers["content-disposition"]
    # the same bill number can be printed again (e.g. after a payment): nothing is stored
    pay = [{"amount": "10000", "date": "2026-09-30", "mode": "upi", "note": None}]
    r = c.post("/api/invoices", json=invoice_body([k1_line(c)], bill_no=19, print_mode="paid", payments=pay), headers=auth)
    assert r.status_code == 201 and r.headers["x-invoice-status"] == "part_paid"


def test_unsaved_invoice_needs_bill_no_and_keeps_all_checks(unsaved):
    c, auth = unsaved
    r = c.post("/api/invoices", json=invoice_body([k1_line(c)]), headers=auth)
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == "bill_no"
    stale = k1_line(c, catalogue_unit_price="70.00", unit_price="70.00")
    r = c.post("/api/invoices", json=invoice_body([stale], bill_no=19), headers=auth)
    assert r.status_code == 409 and r.json()["error"]["code"] == "PRICES_CHANGED"
    pay = [{"amount": "99999", "date": "2026-09-30", "mode": "upi", "note": None}]
    r = c.post("/api/invoices", json=invoice_body([k1_line(c)], bill_no=19, print_mode="paid", payments=pay), headers=auth)
    assert r.json()["error"]["code"] == "OVERPAID"
    assert c.post("/api/invoices", json=invoice_body([k1_line(c)], bill_no=19)).status_code == 401


def test_unsaved_server_has_no_invoice_list(unsaved):
    c, auth = unsaved
    for path in ("/api/invoices", "/api/invoices/19", "/api/invoices/19/pdf", "/api/invoices/next-bill-no"):
        r = c.get(path, headers=auth)
        assert r.status_code == 503 and r.json()["error"]["code"] == "STORAGE_DISABLED", path
