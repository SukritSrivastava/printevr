"""Team tab: the employee list (admin passcode) and attendance check-in / check-out.

Runs on SQLite; the Store applies migration 0009 when it opens.
"""
import dataclasses
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from app.main import create_app
from app.settings import get_settings
from app.team import service
from app.team.models import TeamBase

from .test_invoice_api import PASSCODE

ADMIN = "admin-pass-123"
# 03:30 UTC = 09:00 IST on 8 October 2026.
MORNING = datetime(2026, 10, 8, 3, 30, tzinfo=timezone.utc)
EVENING = datetime(2026, 10, 8, 12, 45, tzinfo=timezone.utc)  # 18:15 IST


def _app(tmp_path, **changes):
    db = tmp_path / "team.db"
    base = {
        "staff_passcode": PASSCODE,
        "secret_key": "test-secret",
        "admin_passcode": ADMIN,
        "database_url": f"sqlite:///{db.as_posix()}",
        "rate_limit_per_minute": 0,
    }
    settings = dataclasses.replace(get_settings(), **{**base, **changes})
    return create_app(settings)


@pytest.fixture
def clock(monkeypatch):
    now = {"t": MORNING}
    monkeypatch.setattr(service, "now_utc", lambda: now["t"])
    return now


@pytest.fixture
def app(tmp_path):
    return _app(tmp_path)


@pytest.fixture
def staff(app):
    token = TestClient(app).post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def admin(app, staff):
    r = staff.post("/api/team/admin/login", json={"passcode": ADMIN})
    assert r.status_code == 200, r.text
    return TestClient(app, headers={**staff.headers, "X-Team-Admin": r.json()["token"]})


def add(admin, name="Asha Verma", role="designer", **extra):
    r = admin.post("/api/team/employees", json={"name": name, "role": role, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def code(r):
    return r.json()["error"]["code"]


# ---------- access ----------

def test_team_routes_need_the_staff_passcode(app):
    assert TestClient(app).get("/api/team/employees").status_code == 401


def test_changing_employees_needs_the_admin_passcode(staff):
    r = staff.post("/api/team/employees", json={"name": "Asha", "role": "sales"})
    assert r.status_code == 403 and code(r) == "ADMIN_REQUIRED"
    assert staff.get("/api/team/employees").status_code == 200  # viewing is fine


def test_wrong_admin_passcode(staff):
    r = staff.post("/api/team/admin/login", json={"passcode": "nope"})
    assert r.status_code == 401 and code(r) == "BAD_PASSCODE"
    bogus = staff.post("/api/team/employees", json={"name": "A", "role": "sales"}, headers={"X-Team-Admin": "1.abc"})
    assert bogus.status_code == 403


def test_without_an_admin_passcode_nobody_can_change_employees(tmp_path):
    app = _app(tmp_path, admin_passcode=None)
    token = TestClient(app).post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    c = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    r = c.post("/api/team/admin/login", json={"passcode": "anything"})
    assert r.status_code == 503 and code(r) == "ADMIN_NOT_CONFIGURED"
    assert "ADMIN_PASSCODE" not in r.text  # no environment variable names in public answers
    assert c.get("/api/team/settings").json()["admin_configured"] is False


def test_settings_lists_roles_and_who_is_admin(staff, admin):
    body = staff.get("/api/team/settings").json()
    assert {"value": "designer", "label": "Designer"} in body["roles"]
    assert body["is_admin"] is False and body["admin_configured"] is True
    assert admin.get("/api/team/settings").json()["is_admin"] is True


# ---------- employees ----------

def test_add_edit_remove_restore(admin, staff):
    e = add(admin, name="  Asha   Verma ", role="designer", phone="+91 98765 43210", email="asha@printevr.in",
            joined_on="2026-04-01")
    assert e == {"id": e["id"], "name": "Asha Verma", "role": "designer", "phone": "+91 98765 43210",
                 "email": "asha@printevr.in", "joined_on": "2026-04-01", "active": True}
    r = admin.patch(f"/api/team/employees/{e['id']}", json={"role": "production", "phone": ""})
    assert r.json()["role"] == "production" and r.json()["phone"] is None and r.json()["email"] == "asha@printevr.in"

    assert admin.delete(f"/api/team/employees/{e['id']}").json()["active"] is False
    assert staff.get("/api/team/employees").json()["employees"] == []
    removed = staff.get("/api/team/employees?include_removed=true").json()["employees"]
    assert [x["name"] for x in removed] == ["Asha Verma"]

    assert admin.post(f"/api/team/employees/{e['id']}/restore").json()["active"] is True
    assert [x["id"] for x in staff.get("/api/team/employees").json()["employees"]] == [e["id"]]


def test_names_are_unique_ignoring_case(admin):
    first = add(admin, name="Ravi")
    r = admin.post("/api/team/employees", json={"name": "RAVI", "role": "sales"})
    assert r.status_code == 409 and code(r) == "NAME_TAKEN"
    admin.delete(f"/api/team/employees/{first['id']}")
    r = admin.post("/api/team/employees", json={"name": "ravi", "role": "sales"})
    assert r.status_code == 409 and "restore" in r.json()["error"]["message"]


@pytest.mark.parametrize(
    "body, field",
    [
        ({"name": "   ", "role": "sales"}, "name"),
        ({"name": "X", "role": "sales", "phone": "call me"}, "phone"),
        ({"name": "X", "role": "sales", "email": "not-an-email"}, "email"),
    ],
)
def test_employee_validation(admin, body, field):
    r = admin.post("/api/team/employees", json=body)
    assert r.status_code == 422 and r.json()["error"]["details"]["field"] == field


def test_unknown_role_is_refused(admin):
    assert admin.post("/api/team/employees", json={"name": "X", "role": "ceo"}).status_code == 422


def test_editing_a_missing_employee(admin):
    assert admin.patch("/api/team/employees/999", json={"role": "sales"}).status_code == 404


# ---------- attendance ----------

def test_check_in_and_out(admin, staff, clock):
    e = add(admin)
    r = staff.post("/api/team/attendance/check-in", json={"employee_id": e["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["record"] == {"work_date": "2026-10-08", "check_in": "2026-10-08T03:30:00+00:00",
                                  "check_out": None, "minutes": None, "note": None, "edited_by_admin": False}
    again = staff.post("/api/team/attendance/check-in", json={"employee_id": e["id"]})
    assert again.status_code == 409 and code(again) == "ALREADY_CHECKED_IN"

    clock["t"] = EVENING
    out = staff.post("/api/team/attendance/check-out", json={"employee_id": e["id"]}).json()["record"]
    assert out["check_out"] == "2026-10-08T12:45:00+00:00" and out["minutes"] == 555
    twice = staff.post("/api/team/attendance/check-out", json={"employee_id": e["id"]})
    assert code(twice) == "ALREADY_CHECKED_OUT"

    day = staff.get("/api/team/attendance?date=2026-10-08").json()
    assert day["today"] == "2026-10-08"
    assert day["counts"] == {"employees": 1, "present": 1, "checked_in_now": 0}
    assert day["rows"][0]["record"]["minutes"] == 555


def test_check_out_needs_a_check_in(admin, staff, clock):
    e = add(admin)
    r = staff.post("/api/team/attendance/check-out", json={"employee_id": e["id"]})
    assert r.status_code == 409 and code(r) == "NOT_CHECKED_IN"


def test_the_day_is_the_ist_day(admin, staff, clock):
    e = add(admin)
    clock["t"] = datetime(2026, 10, 8, 19, 0, tzinfo=timezone.utc)  # 00:30 IST on the 9th
    r = staff.post("/api/team/attendance/check-in", json={"employee_id": e["id"]})
    assert r.json()["record"]["work_date"] == "2026-10-09"


def test_removed_employees_cannot_check_in_but_keep_history(admin, staff, clock):
    e = add(admin)
    staff.post("/api/team/attendance/check-in", json={"employee_id": e["id"]})
    admin.delete(f"/api/team/employees/{e['id']}")
    r = staff.post("/api/team/attendance/check-in", json={"employee_id": e["id"]})
    assert code(r) in ("EMPLOYEE_REMOVED", "ALREADY_CHECKED_IN")
    rows = staff.get("/api/team/attendance?date=2026-10-08").json()["rows"]
    assert [(x["employee"]["name"], x["employee"]["active"]) for x in rows] == [("Asha Verma", False)]


def test_admin_sets_and_deletes_a_day(admin, staff, clock):
    e = add(admin)
    url = f"/api/team/attendance/{e['id']}/2026-10-07"
    body = {"check_in": "09:15", "check_out": "17:45", "note": "forgot to check in"}
    assert staff.put(url, json=body).status_code == 403
    rec = admin.put(url, json=body).json()["record"]
    assert rec["check_in"] == "2026-10-07T03:45:00+00:00" and rec["minutes"] == 510 and rec["edited_by_admin"] is True
    bad = admin.put(url, json={"check_in": "18:00", "check_out": "09:00"})
    assert bad.status_code == 422 and bad.json()["error"]["details"]["field"] == "check_out"
    future = admin.put(f"/api/team/attendance/{e['id']}/2026-10-09", json={"check_in": "09:00"})
    assert future.status_code == 422
    assert admin.delete(url).json() == {"status": "deleted"}
    assert admin.delete(url).status_code == 404


def test_month_summary(admin, staff, clock):
    a, b = add(admin, name="Asha"), add(admin, name="Bilal", role="production")
    admin.put(f"/api/team/attendance/{a['id']}/2026-10-01", json={"check_in": "09:00", "check_out": "18:00"})
    admin.put(f"/api/team/attendance/{a['id']}/2026-10-02", json={"check_in": "09:00"})  # never checked out
    staff.post("/api/team/attendance/check-in", json={"employee_id": a["id"]})  # today, still in
    body = staff.get("/api/team/attendance/summary?month=2026-10").json()
    assert body["first"] == "2026-10-01" and body["last"] == "2026-10-31"
    rows = {r["employee"]["name"]: r for r in body["rows"]}
    assert (rows["Asha"]["days_present"], rows["Asha"]["minutes"], rows["Asha"]["open_days"]) == (3, 540, 1)
    assert sorted(rows["Asha"]["days"]) == ["2026-10-01", "2026-10-02", "2026-10-08"]
    assert rows["Bilal"]["days_present"] == 0 and rows["Bilal"]["days"] == {}
    assert staff.get("/api/team/attendance/summary?month=2026-13").status_code == 422


def test_without_a_database(tmp_path):
    app = _app(tmp_path, database_url=None)
    token = TestClient(app).post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    r = TestClient(app, headers={"Authorization": f"Bearer {token}"}).get("/api/team/employees")
    assert r.status_code == 503 and code(r) == "STORAGE_DISABLED"


def test_migration_matches_the_models(staff):
    staff.get("/api/team/employees")  # opens the store, which applies the migrations
    engine = staff.app.state.invoices["store"].engine
    insp = inspect(engine)
    for table in TeamBase.metadata.sorted_tables:
        in_db = {c["name"]: c["nullable"] for c in insp.get_columns(table.name)}
        assert in_db == {c.name: c.nullable for c in table.columns}, table.name
    unique = {tuple(i["column_names"]) for i in insp.get_indexes("attendance") if i["unique"]}
    assert ("employee_id", "work_date") in unique
