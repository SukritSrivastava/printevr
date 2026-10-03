"""Rate limits: bounded memory, limits shared through the database, the fallback, client IPs."""
import dataclasses
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.main import client_ip, create_app
from app.ratelimit import DatabaseRateLimiter, MemoryRateLimiter, client_hash
from app.settings import get_settings

from .pg import migrate, needs_postgres, temp_schema
from .test_invoice_api import PASSCODE

PASSWORD = "site-password"


class Clock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


# ---------------------------------------------------------------- in memory


def test_memory_limits_each_client():
    limiter = MemoryRateLimiter(3, clock=Clock())
    assert [limiter.allow("a") for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("b")


def test_memory_never_holds_more_than_max_keys():
    limiter = MemoryRateLimiter(5, max_keys=100, clock=Clock())
    for i in range(10_000):
        limiter.allow(f"10.0.{i // 256}.{i % 256}")
    assert len(limiter) == 100


def test_memory_forgets_the_least_recently_seen_client_first():
    limiter = MemoryRateLimiter(2, max_keys=3, clock=Clock())
    for key in ("a", "b", "c"):
        limiter.allow(key)
    limiter.allow("a")  # a is now the most recent
    limiter.allow("d")  # evicts b
    assert list(limiter.hits) == ["c", "a", "d"]
    assert not limiter.allow("a")  # a's count survived: 2 of 2


def test_memory_sweeps_idle_clients_once_a_window():
    clock = Clock()
    limiter = MemoryRateLimiter(5, clock=clock)
    for i in range(500):
        limiter.allow(f"client-{i}")
    assert len(limiter) == 500
    clock.now += 61
    limiter.allow("someone-new")
    assert len(limiter) == 1


def test_memory_window_slides():
    clock = Clock()
    limiter = MemoryRateLimiter(2, clock=clock)
    assert limiter.allow("a") and limiter.allow("a") and not limiter.allow("a")
    clock.now += 61
    assert limiter.allow("a")


# ---------------------------------------------------------------- shared (database)


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=needs_postgres)])
def shared_url(request, tmp_path):
    if request.param == "sqlite":
        url = f"sqlite:///{(tmp_path / 'shared.db').as_posix()}"
        migrate.migrate(url, out=lambda _: None)
        yield url
    else:
        with temp_schema() as url:
            migrate.migrate(url, out=lambda _: None)
            yield url


def instance(url: str, **changes):
    """One server instance; several of these on one DATABASE_URL are like several Vercel instances."""
    s = dataclasses.replace(
        get_settings(), site_password=PASSWORD, staff_passcode=PASSCODE, secret_key="s", database_url=url,
        rate_limit_backend="database", rate_limit_per_minute=0, **changes,
    )
    return TestClient(create_app(s))


def test_site_login_limit_holds_across_instances(shared_url):
    a, b = instance(shared_url), instance(shared_url)
    codes = [(a if i % 2 else b).post("/api/login", json={"password": "wrong"}).status_code for i in range(12)]
    assert codes == [401] * 10 + [429] * 2  # 10 a minute in total, not 10 per instance
    # The right password is refused too while over the limit, on either instance.
    assert a.post("/api/login", json={"password": PASSWORD}).status_code == 429


def test_staff_login_limit_holds_across_instances(shared_url):
    a, b, c = (instance(shared_url) for _ in range(3))
    for client in (a, b, c):
        client.post("/api/login", json={"password": PASSWORD})
    codes = [(a, b, c)[i % 3].post("/api/staff/login", json={"passcode": "nope"}).status_code for i in range(7)]
    assert codes == [401] * 5 + [429] * 2


def test_limits_are_per_client_and_store_no_addresses(shared_url):
    a = instance(shared_url, trust_proxy_headers=True)
    for _ in range(10):
        a.post("/api/login", json={"password": "wrong"}, headers={"x-forwarded-for": "203.0.113.7"})
    assert a.post("/api/login", json={"password": "wrong"}, headers={"x-forwarded-for": "203.0.113.7"}).status_code == 429
    assert a.post("/api/login", json={"password": "wrong"}, headers={"x-forwarded-for": "198.51.100.9"}).status_code == 401
    engine = a.app.state.invoices["store"].engine
    with engine.connect() as conn:
        keys = {r[0] for r in conn.execute(text("SELECT client_key FROM rate_limit_counters"))}
    assert client_hash("site_login", "203.0.113.7") in keys
    assert not any("203.0.113" in k for k in keys)


def test_shared_window_slides_and_old_rows_are_deleted(shared_url):
    clock = Clock(6_000_000.0)  # a minute boundary
    engine = migrate.engine_for(shared_url)
    limiter = DatabaseRateLimiter("t", 4, lambda: engine, MemoryRateLimiter(4), clock=clock)
    assert [limiter.allow("x") for _ in range(5)] == [True] * 4 + [False]  # 5 hits now (refusals count)
    clock.now += 60 + 30  # half way through the next minute: 5 × 0.5 = 2.5 still count
    assert limiter.allow("x")  # 2.5 + 1
    assert not limiter.allow("x")  # 2.5 + 2 > 4
    clock.now += 60 * 5
    assert limiter.allow("x")
    with engine.connect() as conn:
        windows = {r[0] for r in conn.execute(text("SELECT window_start FROM rate_limit_counters WHERE scope = 't'"))}
    assert windows == {int(clock.now // 60) * 60}  # earlier minutes were cleaned up
    engine.dispose()


def test_falls_back_to_memory_when_the_database_cant_count(tmp_path, caplog):
    engine = migrate.engine_for(f"sqlite:///{(tmp_path / 'unmigrated.db').as_posix()}")  # no rate_limit_counters
    limiter = DatabaseRateLimiter("t", 2, lambda: engine, MemoryRateLimiter(2))
    with caplog.at_level(logging.WARNING, logger="printevr.ratelimit"):
        assert [limiter.allow("x") for _ in range(3)] == [True, True, False]
    assert "counting in this instance only" in caplog.text
    assert sum("shared rate limit unavailable" in r.message for r in caplog.records) == 1  # not once per request

    def broken():
        raise RuntimeError("database down")

    limiter = DatabaseRateLimiter("t", 1, broken, MemoryRateLimiter(1))
    assert [limiter.allow("y") for _ in range(2)] == [True, False]
    engine.dispose()


def test_auto_shares_only_on_postgres():
    from app.main import shared_limits

    base = get_settings()
    assert shared_limits(dataclasses.replace(base, database_url="postgresql://u@h/db"))
    assert not shared_limits(dataclasses.replace(base, database_url="sqlite:///x.db"))
    assert not shared_limits(dataclasses.replace(base, database_url=None))
    assert not shared_limits(dataclasses.replace(base, database_url="postgresql://u@h/db", rate_limit_backend="memory"))
    assert shared_limits(dataclasses.replace(base, database_url="sqlite:///x.db", rate_limit_backend="database"))


# ---------------------------------------------------------------- client IP


class _Req:
    def __init__(self, peer: str, headers: list[tuple[str, str]]):
        from starlette.datastructures import Headers

        self.client = type("C", (), {"host": peer})()
        self.headers = Headers(raw=[(k.lower().encode(), v.encode()) for k, v in headers])


def ip(peer="10.0.0.2", headers=(), **changes):
    return client_ip(_Req(peer, list(headers)), dataclasses.replace(get_settings(), **changes))


def test_forwarded_headers_ignored_unless_trusted():
    assert ip(headers=[("X-Forwarded-For", "1.1.1.1")]) == "10.0.0.2"
    assert ip(headers=[("X-Real-IP", "1.1.1.1")]) == "10.0.0.2"


def test_client_typed_entries_on_the_left_are_ignored():
    # nginx's $proxy_add_x_forwarded_for appends the real peer to whatever the client sent.
    spoofed = [("X-Forwarded-For", "6.6.6.6, 7.7.7.7, 203.0.113.7")]
    assert ip(headers=spoofed, trust_proxy_headers=True) == "203.0.113.7"
    assert ip(headers=spoofed, trust_proxy_headers=True, trusted_proxy_hops=2) == "7.7.7.7"
    # Several X-Forwarded-For headers count as one list, in order.
    two = [("X-Forwarded-For", "6.6.6.6"), ("X-Forwarded-For", "203.0.113.7")]
    assert ip(headers=two, trust_proxy_headers=True) == "203.0.113.7"
    # Fewer entries than hops: the first one is the client the outermost proxy saw.
    assert ip(headers=[("X-Forwarded-For", "203.0.113.7")], trust_proxy_headers=True, trusted_proxy_hops=2) == "203.0.113.7"


def test_x_real_ip_only_without_x_forwarded_for():
    both = [("X-Real-IP", "6.6.6.6"), ("X-Forwarded-For", "203.0.113.7")]
    assert ip(headers=both, trust_proxy_headers=True) == "203.0.113.7"
    assert ip(headers=[("X-Real-IP", "203.0.113.7")], trust_proxy_headers=True) == "203.0.113.7"
    assert ip(headers=[], trust_proxy_headers=True) == "10.0.0.2"


def test_trusted_proxies_restricts_who_may_forward():
    fwd = [("X-Forwarded-For", "203.0.113.7")]
    trusted = ("10.0.0.0/8", "192.168.1.5")
    assert ip("10.1.2.3", fwd, trust_proxy_headers=True, trusted_proxies=trusted) == "203.0.113.7"
    assert ip("192.168.1.5", fwd, trust_proxy_headers=True, trusted_proxies=trusted) == "203.0.113.7"
    assert ip("198.51.100.1", fwd, trust_proxy_headers=True, trusted_proxies=trusted) == "198.51.100.1"
    assert ip("testclient", fwd, trust_proxy_headers=True, trusted_proxies=trusted) == "testclient"


def test_settings_read_the_proxy_and_limit_variables(monkeypatch):
    monkeypatch.setenv("TRUSTED_PROXY_HOPS", "2")
    monkeypatch.setenv("TRUSTED_PROXIES", "10.0.0.0/8, 172.16.0.0/12")
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "Database")
    monkeypatch.setenv("RATE_LIMIT_MAX_KEYS", "5000")
    s = get_settings()
    assert (s.trusted_proxy_hops, s.trusted_proxies) == (2, ("10.0.0.0/8", "172.16.0.0/12"))
    assert (s.rate_limit_backend, s.rate_limit_max_keys) == ("database", 5000)
    monkeypatch.setenv("RATE_LIMIT_BACKEND", "redis")
    with pytest.raises(ValueError, match="RATE_LIMIT_BACKEND"):
        get_settings()
