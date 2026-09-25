"""Site password: every pricing route needs the session cookie from /api/login."""
import dataclasses

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.main import create_app

from .conftest import RIGID_TB

PASSWORD = "test-password"
QUOTE = {"item_id": RIGID_TB, "quantity": 350}


@pytest.fixture
def client(settings):
    s = dataclasses.replace(settings, site_password=PASSWORD, rate_limit_per_minute=0)
    return TestClient(create_app(s))


def login(client, password=PASSWORD):
    return client.post("/api/login", json={"password": password})


def test_pricing_routes_need_a_session(client):
    assert client.get("/api/catalog").status_code == 401
    r = client.post("/api/calculate", json=QUOTE)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHENTICATED"
    assert client.get("/api/session").json() == {"authenticated": False, "password_required": True}


def test_health_stays_public(client):
    assert client.get("/api/health").status_code == 200


def test_wrong_password_is_rejected(client):
    r = login(client, "ghost")
    assert r.status_code == 401 and r.json()["error"]["code"] == "WRONG_PASSWORD"
    assert auth.COOKIE_NAME not in r.cookies
    assert client.get("/api/catalog").status_code == 401


def test_right_password_unlocks_the_site(client):
    r = login(client)
    assert r.status_code == 200
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert client.get("/api/session").json()["authenticated"] is True
    assert client.get("/api/catalog").status_code == 200
    assert client.post("/api/calculate", json=QUOTE).json()["data"]["totals"]["grand_total"] == "30975.00"


def test_logout_locks_it_again(client):
    login(client)
    client.post("/api/logout")
    assert client.get("/api/catalog").status_code == 401


def test_forged_or_expired_cookies_are_rejected(client):
    client.cookies.set(auth.COOKIE_NAME, "9999999999.deadbeef")
    assert client.get("/api/catalog").status_code == 401
    expired = auth.issue_token(PASSWORD, "", days=1, now=0)
    client.cookies.set(auth.COOKIE_NAME, expired)
    assert client.get("/api/catalog").status_code == 401


def test_changing_the_password_signs_everyone_out():
    token = auth.issue_token(PASSWORD, "", days=7)
    assert auth.token_valid(token, PASSWORD, "")
    assert not auth.token_valid(token, "new-password", "")
    assert not auth.token_valid(token, PASSWORD, "other-secret")


def test_secure_cookie_over_https(settings):
    s = dataclasses.replace(settings, site_password=PASSWORD, trust_proxy_headers=True)
    client = TestClient(create_app(s))
    r = client.post("/api/login", json={"password": PASSWORD}, headers={"x-forwarded-proto": "https"})
    assert "Secure" in r.headers["set-cookie"]


def test_login_attempts_are_rate_limited(client):
    statuses = [login(client, f"guess{i}").status_code for i in range(11)]
    assert statuses[:10] == [401] * 10 and statuses[10] == 429


def test_public_host_without_password_refuses_to_run_open(settings):
    s = dataclasses.replace(settings, site_password=None, require_password=True)
    client = TestClient(create_app(s))
    r = client.get("/api/catalog")
    assert r.status_code == 503 and r.json()["error"]["code"] == "AUTH_NOT_CONFIGURED"


def test_admin_reload_uses_its_own_token(settings):
    s = dataclasses.replace(settings, site_password=PASSWORD, admin_token="t")
    client = TestClient(create_app(s))
    assert client.post("/api/admin/reload", headers={"X-Admin-Token": "t"}).status_code == 200
