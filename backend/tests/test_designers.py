"""Designer Assignment through the API: rotation, idempotency, jobs, statuses, vendors, workload.

Every test runs on SQLite, and again on Postgres when TEST_DATABASE_URL is set.
"""
import dataclasses
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.designers.models import SEED_DESIGNERS, DesignBase
from app.invoice.store import Base
from app.main import create_app
from app.settings import get_settings

from .pg import TEST_DATABASE_URL, migrate, temp_schema
from .test_invoice_api import PASSCODE, invoice_body, k1_line
from .test_quotation_gst import gst_body, pdf_text, quotation_body

BACKENDS = ["sqlite", pytest.param("postgres", marks=pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL not set"))]


def _app(url: str):
    return create_app(
        dataclasses.replace(get_settings(), staff_passcode=PASSCODE, secret_key="test-secret", database_url=url)
    )


@pytest.fixture(scope="module", params=BACKENDS)
def app(request, tmp_path_factory):
    if request.param == "sqlite":
        db = tmp_path_factory.mktemp("designers") / "d.db"
        yield _app(f"sqlite:///{db.as_posix()}")
    else:
        with temp_schema() as url:
            migrate.migrate(url, out=lambda _: None)
            yield _app(url)


def reset(store) -> None:
    Base.metadata.drop_all(store.engine)
    Base.metadata.create_all(store.engine)
    if store.is_sqlite:
        DesignBase.metadata.drop_all(store.engine)
        store._designers_ready = False
        return
    with store.engine.begin() as conn:
        conn.execute(text("TRUNCATE job_status_history, design_jobs, designers RESTART IDENTITY CASCADE"))
        conn.execute(text("UPDATE rotation_state SET last_order = 0, seq = 0"))
        for name, order in SEED_DESIGNERS:
            conn.execute(text("INSERT INTO designers (name, active, rotation_order) VALUES (:n, TRUE, :o)"), {"n": name, "o": order})


@pytest.fixture(scope="module")
def auth(app):
    r = TestClient(app).post("/api/staff/login", json={"passcode": PASSCODE})
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture
def client(app, auth):
    c = TestClient(app, headers=auth)
    c.get("/api/health")
    c.get("/api/designers")  # makes the store
    reset(app.state.invoices["store"])
    return c


def print_invoice(client, **changes):
    r = client.post("/api/invoices", json=invoice_body([k1_line(client)], **changes))
    assert r.status_code == 201, r.text
    return r


def designer_of(r) -> str:
    return unquote(r.headers["x-designer"])


def designer_id(client, name: str) -> int:
    return next(d["id"] for d in client.get("/api/designers").json()["designers"] if d["name"] == name)


def next_name(client) -> str | None:
    d = client.get("/api/rotation/next").json()["designer"]
    return d["name"] if d else None


# ---------- acceptance 1, 3, 4 ----------

def test_four_invoices_alternate(client):
    assert next_name(client) == "Namit"
    names = [designer_of(print_invoice(client)) for _ in range(4)]
    assert names == ["Namit", "Ajendra", "Namit", "Ajendra"]
    jobs = client.get("/api/jobs").json()["jobs"]
    assert [j["designer_name"] for j in jobs] == ["Ajendra", "Namit", "Ajendra", "Namit"]  # newest first
    assert [j["bill_no"] for j in jobs] == [22, 21, 20, 19]
    assert all(j["status"] == 1 and j["status_label"] == "Work assigned" for j in jobs)
    assert next_name(client) == "Namit"


def test_reprint_and_payment_keep_the_job_and_rotation(client):
    first = print_invoice(client)  # unpaid
    job_id = first.headers["x-job-id"]
    bill = first.headers["x-bill-no"]
    assert next_name(client) == "Ajendra"
    for _ in range(2):
        r = client.get(f"/api/invoices/{bill}/pdf")
        assert r.status_code == 200 and r.headers["x-job-id"] == job_id and designer_of(r) == "Namit"
    # Unpaid -> paid on the same invoice: Record payment.
    r = client.post(f"/api/invoices/{bill}/payments", json={"amount": "26250", "date": "2026-10-03", "mode": "upi"})
    assert r.status_code == 200 and r.headers["x-invoice-status"] == "paid"
    assert r.headers["x-job-id"] == job_id
    assert client.get("/api/jobs").json()["total"] == 1
    assert next_name(client) == "Ajendra"


def test_printed_paid_is_a_new_invoice_and_a_new_job(client):
    a = print_invoice(client)
    b = print_invoice(client, print_mode="paid", payments=[{"amount": "26250", "date": "2026-10-03", "mode": "cash"}])
    assert a.headers["x-bill-no"] != b.headers["x-bill-no"]
    assert (designer_of(a), designer_of(b)) == ("Namit", "Ajendra")


def test_inactive_designers_are_skipped(client):
    ajendra = designer_id(client, "Ajendra")
    assert client.patch(f"/api/designers/{ajendra}", json={"active": False}).json()["active"] is False
    assert [designer_of(print_invoice(client)) for _ in range(3)] == ["Namit"] * 3
    client.patch(f"/api/designers/{ajendra}", json={"active": True})
    assert next_name(client) == "Ajendra"
    assert [designer_of(print_invoice(client)) for _ in range(3)] == ["Ajendra", "Namit", "Ajendra"]


def test_nobody_active_leaves_the_job_unassigned(client):
    for name in ("Namit", "Ajendra"):
        client.patch(f"/api/designers/{designer_id(client, name)}", json={"active": False})
    assert next_name(client) is None
    r = print_invoice(client)
    assert r.headers["x-designer"] == ""
    job = client.get("/api/jobs").json()["jobs"][0]
    assert job["designer_id"] is None
    client.patch(f"/api/designers/{designer_id(client, 'Ajendra')}", json={"active": True})
    client.patch(f"/api/designers/{designer_id(client, 'Namit')}", json={"active": True})
    assert designer_of(print_invoice(client)) == "Namit"  # the rotation didn't move


def test_new_designer_joins_the_end_of_the_rotation(client):
    r = client.post("/api/designers", json={"name": "  Riya  "})
    assert r.status_code == 201 and r.json() == {"id": 3, "name": "Riya", "active": True, "rotation_order": 3}
    assert [designer_of(print_invoice(client)) for _ in range(4)] == ["Namit", "Ajendra", "Riya", "Namit"]


def test_designer_names_are_checked(client):
    assert client.post("/api/designers", json={"name": "namit"}).json()["error"]["code"] == "NAME_TAKEN"
    assert client.post("/api/designers", json={"name": "   "}).status_code == 422
    assert client.post("/api/designers", json={"name": "x" * 41}).status_code == 422
    ajendra = designer_id(client, "Ajendra")
    assert client.patch(f"/api/designers/{ajendra}", json={"name": "Namit"}).status_code == 409
    r = client.patch(f"/api/designers/{ajendra}", json={"name": "Ajendra K"})
    assert r.status_code == 200 and r.json()["name"] == "Ajendra K"
    assert client.patch("/api/designers/999", json={"active": False}).status_code == 404


# ---------- which documents make jobs ----------

def test_quotations_make_no_job_and_gst_invoices_do(client):
    r = client.post("/api/invoices", json=quotation_body([k1_line(client)]))
    assert r.status_code == 201 and "x-job-id" not in r.headers
    r = client.post("/api/invoices", json=gst_body([k1_line(client)], "intra_18"))
    assert r.status_code == 201 and designer_of(r) == "Namit"
    jobs = client.get("/api/jobs").json()["jobs"]
    assert [(j["series"], j["customer_name"]) for j in jobs] == [("gst", "Jairpur Jewellers")]


def test_designer_never_appears_on_the_invoice(client):
    r = print_invoice(client)
    assert designer_of(r) == "Namit"
    text = pdf_text(r.content)
    assert "SOGAT JUTTI STORE" in text
    assert "namit" not in text.lower() and "ajendra" not in text.lower()


def test_job_records_the_invoice(client):
    print_invoice(client)
    job = client.get("/api/jobs").json()["jobs"][0]
    assert job["customer_name"] == "Sogat Jutti Store"
    assert job["invoice_total"] == "26250.00"
    assert "×350" in job["items_summary"]
    assert job["assigned_at"].endswith("+00:00")
    assert job["vendor_name"] is None and job["pending"] is True


def test_deleting_an_invoice_deletes_its_job_but_not_the_rotation(client):
    bill = print_invoice(client).headers["x-bill-no"]
    assert client.delete(f"/api/invoices/{bill}").status_code == 200
    assert client.get("/api/jobs").json()["total"] == 0
    assert next_name(client) == "Ajendra"


# ---------- statuses and history ----------

def test_status_changes_are_logged_including_going_back(client):
    print_invoice(client)
    job_id = client.get("/api/jobs").json()["jobs"][0]["id"]
    for status in (2, 4, 3):
        r = client.patch(f"/api/jobs/{job_id}", json={"status": status})
        assert r.status_code == 200 and r.json()["status"] == status
    client.patch(f"/api/jobs/{job_id}", json={"status": 3})  # no change: not logged
    h = client.get(f"/api/jobs/{job_id}/history").json()["history"]
    assert [(x["old_status"], x["new_status"]) for x in h] == [(None, 1), (1, 2), (2, 4), (4, 3)]
    assert all(x["changed_at"] for x in h)


@pytest.mark.parametrize("bad", [0, 5, "2", None, 2.5])
def test_status_must_be_1_to_4(client, bad):
    print_invoice(client)
    job_id = client.get("/api/jobs").json()["jobs"][0]["id"]
    r = client.patch(f"/api/jobs/{job_id}", json={"status": bad})
    assert r.status_code == 422, r.text
    assert client.get("/api/jobs").json()["jobs"][0]["status"] == 1


def test_unknown_job_and_fields(client):
    assert client.patch("/api/jobs/999", json={"status": 2}).status_code == 404
    assert client.get("/api/jobs/999/history").status_code == 404
    print_invoice(client)
    job_id = client.get("/api/jobs").json()["jobs"][0]["id"]
    assert client.patch(f"/api/jobs/{job_id}", json={"designer_id": 2}).status_code == 422


# ---------- vendor ----------

def test_vendor_is_trimmed_limited_and_suggested(client):
    for _ in range(3):
        print_invoice(client)
    ids = [j["id"] for j in client.get("/api/jobs").json()["jobs"]]
    r = client.patch(f"/api/jobs/{ids[0]}", json={"vendor_name": "  Sharma   Printers "})
    assert r.json()["vendor_name"] == "Sharma Printers"
    client.patch(f"/api/jobs/{ids[1]}", json={"vendor_name": "Sharma Printers"})
    client.patch(f"/api/jobs/{ids[2]}", json={"vendor_name": "Akal Packaging"})
    assert client.get("/api/vendors").json()["vendors"] == ["Sharma Printers", "Akal Packaging"]
    assert client.get("/api/vendors", params={"q": "akal"}).json()["vendors"] == ["Akal Packaging"]
    assert client.patch(f"/api/jobs/{ids[0]}", json={"vendor_name": "x" * 81}).status_code == 422
    assert client.patch(f"/api/jobs/{ids[0]}", json={"vendor_name": "   "}).json()["vendor_name"] is None
    # A vendor change isn't a status change.
    assert len(client.get(f"/api/jobs/{ids[0]}/history").json()["history"]) == 1


# ---------- board filters and workload ----------

def test_filters(client):
    for _ in range(4):
        print_invoice(client)
    gst = client.post("/api/invoices", json=gst_body([k1_line(client)], "intra_18"))
    assert designer_of(gst) == "Namit"
    jobs = client.get("/api/jobs").json()["jobs"]
    client.patch(f"/api/jobs/{jobs[-1]['id']}", json={"status": 4})  # bill 19 (Namit): done
    namit = designer_id(client, "Namit")

    def bills(**params):
        return [(j["series"], j["bill_no"]) for j in client.get("/api/jobs", params=params).json()["jobs"]]

    assert bills(designer=namit, pending=True) == [("gst", 1), ("non_gst", 21)]
    assert bills(designer=namit) == [("gst", 1), ("non_gst", 21), ("non_gst", 19)]
    assert bills(status=4) == [("non_gst", 19)]
    assert bills(q="jairpur") == [("gst", 1)]
    assert bills(q="#20") == [("non_gst", 20)]
    assert bills(q="1") == [("gst", 1)]
    assert client.get("/api/jobs", params={"status": 9}).status_code == 422


def test_workload(client):
    for _ in range(5):
        print_invoice(client)
    jobs = client.get("/api/jobs").json()["jobs"]  # 23 Namit, 22 Ajendra, 21 Namit, 20 Ajendra, 19 Namit
    client.patch(f"/api/jobs/{jobs[4]['id']}", json={"status": 4})
    client.patch(f"/api/jobs/{jobs[2]['id']}", json={"status": 2})
    w = {d["name"]: d for d in client.get("/api/workload").json()["designers"]}
    assert w["Namit"]["pending"] == 2 and w["Namit"]["by_status"] == {"1": 1, "2": 1, "3": 0, "4": 1}
    assert w["Ajendra"]["pending"] == 2 and w["Ajendra"]["by_status"] == {"1": 2, "2": 0, "3": 0, "4": 0}
    assert w["Namit"]["oldest_pending_at"] == jobs[2]["assigned_at"]  # 19 is done, so 21
    assert [j["bill_no"] for j in w["Namit"]["jobs"]] == [23, 21, 19]  # pending first, newest first


# ---------- access ----------

def test_staff_token_required(app, client):
    bare = TestClient(app)
    for path in ("/api/jobs", "/api/designers", "/api/workload", "/api/rotation/next", "/api/vendors"):
        assert bare.get(path).status_code == 401, path
    assert bare.patch("/api/jobs/1", json={"status": 2}).status_code == 401
