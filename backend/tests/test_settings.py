"""Settings must survive variables that are set but empty (the Vercel crash)."""
import pytest

from app.settings import ROOT, get_settings

NAMES = ("DATA_FILE", "CONFIG_FILE", "ADMIN_TOKEN", "CORS_ORIGIN", "RATE_LIMIT_PER_MINUTE", "TRUST_PROXY_HEADERS", "VERCEL")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_empty_variables_fall_back_to_defaults(monkeypatch):
    for name in NAMES[:-1]:
        monkeypatch.setenv(name, "")
    s = get_settings()
    assert s.rate_limit_per_minute == 60
    assert s.admin_token is None
    assert s.cors_origins == ["http://localhost:5173"]
    assert s.data_file == ROOT / "data" / "Printevr_Pricing_Master_2025-26.xlsx"
    assert s.config_file == ROOT / "config" / "products.yaml"
    assert s.trust_proxy_headers is False


def test_values_are_read(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", " 120 ")
    monkeypatch.setenv("CORS_ORIGIN", "https://a.example, https://b.example")
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    s = get_settings()
    assert (s.rate_limit_per_minute, s.admin_token) == (120, "secret")
    assert s.cors_origins == ["https://a.example", "https://b.example"]


def test_vercel_trusts_proxy_headers_by_default(monkeypatch):
    monkeypatch.setenv("VERCEL", "1")
    assert get_settings().trust_proxy_headers is True


def test_bad_number_names_the_variable(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "sixty")
    with pytest.raises(ValueError, match="RATE_LIMIT_PER_MINUTE"):
        get_settings()
