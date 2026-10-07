"""Activity log: every successful change is recorded with who (staff / admin), what and when;
failed requests, reads and quotes are not; secrets never are; only the admin can read it."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.audit.describe import describe, redact
from app.audit.models import AuditBase
from app.team import service as team_service

from .test_customisations import cart
from .test_invoice_api import invoice_body, k1_line
from .test_team import ADMIN, PASSCODE, _app

MORNING = datetime(2026, 10, 8, 3, 30, tzinfo=timezone.utc)


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.fixture
def staff(app):
    token = TestClient(app).post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    return TestClient(app, headers={"Authorization": f"Bearer {token}", "User-Agent": "test-phone"})


@pytest.fixture
def admin(app, staff):
    token = staff.post("/api/team/admin/login", json={"passcode": ADMIN}).json()["token"]
    return TestClient(app, headers={**staff.headers, "X-Team-Admin": token})


def logs(admin, **params):
    r = admin.get("/api/team/logs", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_changes_are_logged_with_who_what_and_details(admin, staff, monkeypatch):
    monkeypatch.setattr(team_service, "now_utc", lambda: MORNING)
    e = admin.post("/api/team/employees", json={"name": "Asha", "role": "designer"}).json()
    staff.post("/api/team/attendance/check-in", json={"employee_id": e["id"]})
    admin.put(f"/api/team/attendance/{e['id']}/2026-10-07", json={"check_in": "09:00", "check_out": "18:00", "note": "late entry"})
    r = staff.post("/api/invoices", json=invoice_body(cart(staff)))
    assert r.status_code == 201, r.text
    staff.post("/api/invoices/19/payments", json={"amount": "5000", "date": "2026-10-08", "mode": "cash"})

    body = logs(admin)
    summaries = [x["summary"] for x in body["entries"]]
    assert summaries == [
        "Recorded a payment of ₹5,000 (cash) on Invoice #19, dated 2026-10-08",
        "Created Invoice #19 for Sogat Jutti Store: 3 lines, ₹32,125 before tax (unpaid)",
        "Set Asha's attendance on 2026-10-07: in 09:00, out 18:00 (note: late entry)",
        "Checked in Asha",
        "Added employee Asha (designer)",
        "Unlocked admin with the admin passcode",
        "Signed in with the staff passcode",
    ]
    by = {x["summary"].split(" ")[0]: x for x in body["entries"]}
    assert by["Checked"]["actor_role"] == "staff" and by["Set"]["actor_role"] == "admin"
    assert by["Checked"]["user_agent"] == "test-phone" and by["Checked"]["category"] == "attendance"
    invoice = by["Created"]["details"]
    assert invoice["customer"] == "Sogat Jutti Store" and invoice["items_total_before_tax"] == "32125.00"
    assert [l["kind"] for l in invoice["lines"]] == ["catalogue", "customisation", "customisation"]
    assert invoice["lines"][0]["customisations"] == ["Ribbon pull tab"]


def test_failures_reads_and_quotes_are_not_logged(admin, staff):
    staff.get("/api/team/employees")
    staff.post("/api/calculate", json={"item_id": "rigid_boxes/3x3x2-in/top-bottom", "quantity": 100})
    staff.post("/api/team/employees", json={"name": "X", "role": "sales"})  # 403: not admin
    staff.post("/api/team/attendance/check-out", json={"employee_id": 999})  # 404
    assert [x["summary"] for x in logs(admin)["entries"]] == [
        "Unlocked admin with the admin passcode",
        "Signed in with the staff passcode",
    ]


def test_secrets_never_reach_the_log(admin):
    entries = logs(admin)["entries"]
    text = str(entries)
    assert PASSCODE not in text and ADMIN not in text
    assert redact({"passcode": "x", "nested": {"admin_token": "y"}, "ok": "z"}) == {
        "passcode": "•••", "nested": {"admin_token": "•••"}, "ok": "z"
    }


def test_only_the_admin_reads_the_log(staff):
    r = staff.get("/api/team/logs")
    assert r.status_code == 403 and r.json()["error"]["code"] == "ADMIN_REQUIRED"


def test_filters_and_paging(admin, staff):
    for name in ("Asha", "Bilal", "Chitra"):
        admin.post("/api/team/employees", json={"name": name, "role": "sales"})
    assert logs(admin, category="employees")["total"] == 3
    assert [x["summary"] for x in logs(admin, q="bilal")["entries"]] == ["Added employee Bilal (sales)"]
    page = logs(admin, limit=2, offset=1)
    assert page["total"] == 5 and [x["summary"] for x in page["entries"]] == [
        "Added employee Bilal (sales)", "Added employee Asha (sales)"
    ]
    today = datetime.now(timezone.utc).date().isoformat()
    assert logs(admin, to="2000-01-01")["total"] == 0
    assert logs(admin, **{"from": "2000-01-01"})["total"] == 5 and today


def test_descriptions_of_other_changes():
    assert describe("PATCH", "/api/jobs/4", {}, {"status": 5, "vendor_name": "Sharma"}, {})[1] == \
        "Updated design job #4: status → Final design, vendor name → Sharma"
    category, summary, _ = describe("PATCH", "/api/production/jobs/2/products/0/stages/3", {}, {"completed": True}, {})
    assert category == "production" and summary == "Production job #2, product 1, stage 3 Printing: completed → yes"
    assert describe("DELETE", "/api/invoices/7", {"series": "gst"}, None, {})[1] == "Deleted GST invoice #7"
    assert describe("POST", "/api/something/new", {}, {"a": 1}, {})[:2] == ("other", "POST /api/something/new")


def test_migration_matches_the_model(staff):
    staff.get("/api/team/employees")
    insp = inspect(staff.app.state.invoices["store"].engine)
    for table in AuditBase.metadata.sorted_tables:
        assert {c["name"]: c["nullable"] for c in insp.get_columns(table.name)} == {c.name: c.nullable for c in table.columns}


def test_a_log_failure_never_fails_the_change(admin, monkeypatch):
    from app.audit import service as audit_service

    def boom(*a, **k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(audit_service, "record", boom)
    assert admin.post("/api/team/employees", json={"name": "Dev", "role": "sales"}).status_code == 201


def test_quote_lines_survive_the_middleware(staff):
    # The middleware reads the body before the route does; the route must still see it.
    r = staff.post("/api/invoices", json=invoice_body([k1_line(staff)]))
    assert r.status_code == 201, r.text
