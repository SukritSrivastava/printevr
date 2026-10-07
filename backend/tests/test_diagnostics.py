"""Public responses carry no exception text, tracebacks, paths or environment details; the
operator gets them from the log and GET /api/admin/status."""
import asyncio
import dataclasses
import importlib.util
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app

from .conftest import RIGID_TB
from .test_invoice_api import PASSCODE

TOKEN = "test-admin-token"
INTERNALS = ("Traceback", "File \"", ".py", ".xlsx", "missing.xlsx", "C:\\", "/tmp", "SITE_PASSWORD", "STAFF_PASSCODE", "SECRET_KEY", "DATABASE_URL")


def assert_clean(text: str, *extra: str) -> None:
    for needle in INTERNALS + extra:
        assert needle not in text, needle


@pytest.fixture
def broken(settings, tmp_path):
    """The price sheet is missing: the API starts, pricing answers DATA_NOT_LOADED."""
    s = dataclasses.replace(settings, data_file=tmp_path / "missing.xlsx", admin_token=TOKEN, rate_limit_per_minute=0)
    return TestClient(create_app(s)), tmp_path


def test_health_says_only_ok(settings):
    client = TestClient(create_app(dataclasses.replace(settings, rate_limit_per_minute=0)))
    assert client.get("/api/health").json() == {"status": "ok"}


def test_health_and_pricing_hide_why_the_sheet_failed(broken):
    client, tmp_path = broken
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "error"}
    for response in (client.post("/api/calculate", json={"item_id": RIGID_TB, "quantity": 10}), client.get("/api/catalog")):
        assert response.status_code == 503
        body = response.json()["error"]
        assert body["code"] == "DATA_NOT_LOADED" and body["details"] == {}
        assert "server log" in body["message"]
        assert_clean(response.text, str(tmp_path), tmp_path.name)


def test_operator_status_has_the_details(broken):
    client, tmp_path = broken
    assert client.get("/api/admin/status").status_code == 401
    assert client.get("/api/admin/status", headers={"X-Admin-Token": "wrong"}).status_code == 401
    r = client.get("/api/admin/status", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "error" and "missing.xlsx" in body["load_error"]
    assert body["rate_limits"] == {"login": "memory", "calculate": "memory"}
    assert body["invoicing_disabled"] == "neither SITE_PASSWORD nor STAFF_PASSCODE is set"


def test_operator_status_off_without_admin_token(settings):
    client = TestClient(create_app(dataclasses.replace(settings, admin_token=None)))
    r = client.get("/api/admin/status", headers={"X-Admin-Token": "anything"})
    assert r.status_code == 403
    assert_clean(r.text, "ADMIN_TOKEN")


def test_operator_status_reports_storage_and_counts(settings, tmp_path):
    url = f"sqlite:///{(tmp_path / 'i.db').as_posix()}"
    s = dataclasses.replace(settings, admin_token=TOKEN, database_url=url, staff_passcode=PASSCODE, secret_key="s")
    body = TestClient(create_app(s)).get("/api/admin/status", headers={"X-Admin-Token": TOKEN}).json()
    assert body["storage"] == {"configured": True, "ready": True, "pending_migrations": []}
    assert body["counts"]["items"] == 232 and body["invoicing_disabled"] is None


def test_unhandled_errors_answer_an_id_not_the_exception(settings, caplog):
    app = create_app(dataclasses.replace(settings, rate_limit_per_minute=0))

    @app.get("/api/boom")
    def boom():
        raise RuntimeError("secret detail at C:\\srv\\app\\thing.py")

    client = TestClient(app, raise_server_exceptions=False)
    with caplog.at_level(logging.ERROR, logger="printevr.api"):
        r = client.get("/api/boom")
    assert r.status_code == 500
    err = r.json()["error"]
    assert err["code"] == "INTERNAL_ERROR"
    error_id = err["details"]["error_id"]
    assert len(error_id) == 12 and error_id in err["message"]
    assert_clean(r.text, "secret detail", "RuntimeError")
    # The log has the id, the exception and its traceback.
    record = next(r for r in caplog.records if error_id in r.getMessage())
    assert record.exc_info and "secret detail" in str(record.exc_info[1])


def test_sign_in_not_configured_names_no_variable(settings):
    client = TestClient(create_app(dataclasses.replace(settings, site_password=None, require_password=True)))
    for r in (client.post("/api/calculate", json={"item_id": RIGID_TB, "quantity": 10}), client.post("/api/login", json={"password": "x"})):
        assert r.status_code == 503 and r.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"
        assert_clean(r.text)


@pytest.mark.parametrize(
    "changes",
    [
        {"staff_passcode": None, "site_password": None},
        {"staff_passcode": PASSCODE, "secret_key": None},
    ],
)
def test_invoicing_disabled_names_no_variable(settings, changes):
    client = TestClient(create_app(dataclasses.replace(settings, **changes)))
    for r in (client.get("/api/invoices"), client.post("/api/staff/login", json={"passcode": "x"})):
        assert r.status_code == 503 and r.json()["error"]["code"] == "INVOICING_DISABLED"
        assert r.json()["error"]["message"] == "Invoicing isn't set up on this server"
        assert_clean(r.text)


def test_unreachable_database_is_503_with_an_id_and_no_connection_details(settings, caplog):
    # Nothing listens on port 1; the URL's own connect_timeout keeps the test quick.
    url = "postgresql://printevr:hunter2-secret@127.0.0.1:1/invoices?connect_timeout=1"
    s = dataclasses.replace(settings, database_url=url, staff_passcode=PASSCODE, secret_key="s", rate_limit_backend="memory")
    client = TestClient(create_app(s))
    token = client.post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    with caplog.at_level(logging.ERROR, logger="printevr.api"):
        r = client.get("/api/invoices", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "STORAGE_UNAVAILABLE" and err["details"]["error_id"] in err["message"]
    assert_clean(r.text, "hunter2", "127.0.0.1", "printevr:", "OperationalError", "psycopg")
    assert any(err["details"]["error_id"] in rec.getMessage() for rec in caplog.records)
    # The designer routes behave the same.
    r = client.get("/api/designers", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "STORAGE_UNAVAILABLE"
    assert_clean(r.text, "hunter2", "127.0.0.1")


# ---------------------------------------------------------------- Vercel entry point (api/index.py)


def _index_module():
    path = Path(__file__).resolve().parents[2] / "api" / "index.py"
    spec = importlib.util.spec_from_file_location("vercel_index_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _call(asgi, path: str, headers: list[tuple[bytes, bytes]] | None = None) -> tuple[int, dict]:
    sent: list[dict] = []

    async def receive():
        return {"type": "http.request"}

    async def send(message):
        sent.append(message)

    asyncio.run(asgi({"type": "http", "path": path, "headers": headers or []}, receive, send))
    return sent[0]["status"], json.loads(sent[1]["body"])


@pytest.fixture
def failed_app(monkeypatch, capsys):
    monkeypatch.setenv("ADMIN_TOKEN", "op-token")
    index = _index_module()
    try:
        raise ImportError("No module named 'reportlab' (from C:\\var\\task\\backend\\app\\invoice\\render.py)")
    except ImportError as exc:
        asgi = index._startup_failure(exc)
    logged = capsys.readouterr().err
    return asgi, logged


def test_startup_failure_tells_the_public_nothing(failed_app):
    asgi, logged = failed_app
    status, body = _call(asgi, "/api/calculate")
    assert status == 503 and body["error"]["code"] == "STARTUP_FAILED"
    error_id = body["error"]["details"]["error_id"]
    assert set(body["error"]["details"]) == {"error_id"}
    assert_clean(json.dumps(body), "reportlab", "ImportError", "render.py")
    assert f"error_id={error_id}" in logged and "reportlab" in logged and "Traceback" in logged
    assert _call(asgi, "/api/health") == (503, {"status": "error"})
    _, wrong = _call(asgi, "/api/calculate", [(b"x-admin-token", b"nope")])
    assert "exception" not in wrong["error"]["details"]


def test_startup_failure_details_for_the_operator(failed_app):
    asgi, _ = failed_app
    status, body = _call(asgi, "/api/calculate", [(b"x-admin-token", b"op-token")])
    assert status == 503
    assert "reportlab" in body["error"]["details"]["exception"]
    assert body["error"]["details"]["traceback"]


def test_postgres_connections_give_up_quickly():
    """An unreachable database must fail a request in seconds, not libpq's minutes."""
    from app.invoice.store import CONNECT_TIMEOUT_S, engine_options, normalize_url

    assert engine_options(normalize_url("postgresql://u@h/db"))["connect_args"] == {
        "prepare_threshold": None, "connect_timeout": CONNECT_TIMEOUT_S,
    }
    assert "connect_timeout" not in engine_options(normalize_url("postgresql://u@h/db?connect_timeout=3"))["connect_args"]
    assert CONNECT_TIMEOUT_S <= 10
