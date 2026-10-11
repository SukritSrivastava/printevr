"""Google Sheets export (GET /api/export/{section}): Bearer EXPORT_SECRET only, read-only,
paged, flat rows whose keys match the Apps Script's columns, and no contact details."""
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.audit.models import AuditEntry
from app.export.sections import COLUMNS, SECTIONS
from app.team import service as team_service

from .test_customisations import cart
from .test_invoice_api import invoice_body
from .test_team import ADMIN, PASSCODE, _app

SECRET = "x" * 40
SITE_PASSWORD = "site-pass-123"
MORNING = datetime(2026, 10, 8, 3, 30, tzinfo=timezone.utc)
SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "google-sheets-sync.gs"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("EXPORT_SECRET", SECRET)
    return _app(tmp_path, site_password=SITE_PASSWORD, session_secret="session-secret")


@pytest.fixture
def staff(app):
    c = TestClient(app)
    assert c.post("/api/login", json={"password": SITE_PASSWORD}).status_code == 200
    token = c.post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


@pytest.fixture
def filled(app, staff, monkeypatch):
    """An invoice with a payment (and its design job), a production job, an employee with a
    day's attendance, and the log entries those changes wrote."""
    monkeypatch.setattr(team_service, "now_utc", lambda: MORNING)
    r = staff.post("/api/invoices", json=invoice_body(cart(staff)))
    assert r.status_code == 201, r.text
    r = staff.post("/api/invoices/19/payments", json={"amount": "5000", "date": "2026-10-08", "mode": "cash"})
    assert r.status_code == 200, r.text
    assert staff.post("/api/production/jobs", json={"series": "non_gst", "bill_no": 19}).status_code == 201
    admin_token = staff.post("/api/team/admin/login", json={"passcode": ADMIN}).json()["token"]
    e = staff.post("/api/team/employees", json={"name": "Asha", "role": "designer", "phone": "98765 43210"},
                   headers={"X-Team-Admin": admin_token})
    assert e.status_code == 201, e.text
    assert staff.post("/api/team/attendance/check-in", json={"employee_id": e.json()["id"]}).status_code == 200
    return app


def export(app, section, secret=SECRET, **params):
    headers = {"Authorization": f"Bearer {secret}"} if secret is not None else {}
    return TestClient(app).get(f"/api/export/{section}", params=params, headers=headers)


def all_rows(app, section, **params):
    r = export(app, section, **params)
    assert r.status_code == 200, r.text
    return r.json()["rows"]


# ---------- access ----------

def test_needs_the_secret_and_not_the_site_login(app):
    assert export(app, "invoices", secret=None).status_code == 401
    assert export(app, "invoices", secret="wrong").status_code == 401
    r = TestClient(app).get("/api/export/invoices", headers={"Authorization": SECRET})  # no Bearer
    assert r.status_code == 401
    assert export(app, "invoices").status_code == 200  # no site cookie, no staff token


def test_secret_in_the_url_is_not_accepted(app):
    r = TestClient(app).get("/api/export/invoices", params={"secret": SECRET, "token": SECRET})
    assert r.status_code == 401


def test_off_without_a_strong_secret(app, monkeypatch):
    monkeypatch.setenv("EXPORT_SECRET", "short")
    r = export(app, "invoices", secret="short")
    assert r.status_code == 503 and r.json()["error"]["code"] == "EXPORT_DISABLED"
    assert "EXPORT_SECRET" not in r.text
    monkeypatch.delenv("EXPORT_SECRET")
    assert export(app, "invoices", secret="").status_code == 503


def test_rest_of_the_site_still_needs_the_login(app):
    assert TestClient(app).get("/api/catalog").status_code == 401
    assert TestClient(app).get("/api/export").status_code == 401


def test_unknown_section_and_bad_paging(app):
    assert export(app, "quotations").status_code == 404
    assert export(app, "invoices", pageSize=5000).status_code in (400, 422)
    assert export(app, "invoices", page=0).status_code in (400, 422)
    assert export(app, "invoices", since="2026-10-01T00:00:00Z").status_code == 400


# ---------- rows ----------

def test_every_section_has_its_columns(filled):
    for section in SECTIONS:
        rows = all_rows(filled, section)
        assert rows, section
        for row in rows:
            assert tuple(row) == COLUMNS[section], section


def test_invoice_row_has_numbers_and_iso_dates(filled):
    r = export(filled, "invoices")
    assert '"payable":' in r.text and '"payable":"' not in r.text  # a number, not text
    (row,) = r.json()["rows"]
    assert row["type"] == "Non-GST" and row["bill_no"] == 19 and row["invoice_date"] == "2026-09-29"
    assert row["received"] == 5000 and row["pending"] == row["payable"] - 5000
    assert row["status"] == "Part-paid" and row["payment_count"] == 1 and row["payment_modes"] == "CASH"
    assert row["last_payment_date"] == "2026-10-08"
    assert datetime.fromisoformat(row["created_at"]).tzinfo is not None
    assert r.json()["nextPage"] is None


def test_invoice_items_add_up_to_the_invoice(filled):
    (invoice,) = all_rows(filled, "invoices")
    items = all_rows(filled, "invoice-items")
    assert [i["line_no"] for i in items] == list(range(1, invoice["line_count"] + 1))
    assert round(sum(i["line_amount"] for i in items), 2) == invoice["total"]
    assert {i["kind"] for i in items} >= {"Product"}
    for i in items:
        if i["kind"] != "Product":
            assert i["parent_line_no"] is not None


def test_designer_and_production_rows_are_per_product(filled):
    designs = all_rows(filled, "designer-jobs")
    production = all_rows(filled, "production")
    products = [i for i in all_rows(filled, "invoice-items") if i["kind"] in ("Product", "Custom")]
    assert [d["line_no"] for d in designs] == [p["line_no"] for p in products]
    assert all(d["status"] == "Work assigned" and d["pending"] is True and d["designer"] for d in designs)
    assert [p["line_no"] for p in production] == [p["line_no"] for p in products]
    assert all(p["stage"] == "Sampling" and p["stages_done"] == 0 and p["complete"] is False for p in production)


def test_attendance_employees_and_logs(filled):
    (day,) = all_rows(filled, "attendance")
    assert day["work_date"] == "2026-10-08" and day["employee"] == "Asha" and day["role"] == "Designer"
    assert day["still_in"] is True and day["check_out"] is None and day["hours"] is None
    (emp,) = all_rows(filled, "employees")
    assert emp["name"] == "Asha" and emp["active"] is True
    logs = all_rows(filled, "logs")
    assert [l["id"] for l in logs] == sorted(l["id"] for l in logs)
    assert any(l["category"] == "Invoices & payments" for l in logs)


def test_no_contact_details_or_secrets(filled):
    text = "".join(export(filled, s).text for s in SECTIONS)
    for secret_or_contact in ("95010", "Mohali", "Ramjot", "98765", PASSCODE, ADMIN, SECRET, "testclient"):
        assert secret_or_contact not in text


# ---------- paging and since ----------

def test_pages_cover_every_row_once(filled):
    whole = all_rows(filled, "invoice-items")
    got, page = [], 1
    while page:
        body = export(filled, "invoice-items", page=page, pageSize=2).json()
        assert len(body["rows"]) <= 2
        got += body["rows"]
        page = body["nextPage"]
    assert got == whole


def test_logs_since(filled):
    logs = all_rows(filled, "logs")
    cut = logs[1]["at"]
    later = all_rows(filled, "logs", since=cut)
    assert later == [l for l in logs if l["at"] > cut]
    assert all_rows(filled, "logs", since="2999-01-01T00:00:00+00:00") == []


def test_export_writes_nothing(filled):
    with filled.state.invoices["store"].session() as s:
        before = s.scalar(select(func.count()).select_from(AuditEntry))
    for section in SECTIONS:
        export(filled, section)
    export(filled, "invoices", secret="wrong")
    with filled.state.invoices["store"].session() as s:
        assert s.scalar(select(func.count()).select_from(AuditEntry)) == before


# ---------- the Apps Script ----------

def test_script_columns_match_the_api():
    source = SCRIPT.read_text(encoding="utf-8")
    blocks = re.findall(r"key: '([\w-]+)', tab: '[^']+',(?: append: true,)? columns: \[(.*?)\n    \],", source, re.S)
    found = {key: tuple(re.findall(r"\['(\w+)', '", body)) for key, body in blocks}
    assert found == COLUMNS


def test_script_never_puts_the_secret_in_the_url():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Authorization: 'Bearer ' + config.secret" in source
    assert not re.search(r"url \+?=.*secret", source)
