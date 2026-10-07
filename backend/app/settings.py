"""Runtime settings, read from the environment."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_URL = "sqlite:///./var/invoices.db"  # relative to the repo root


@dataclass(frozen=True)
class Settings:
    data_file: Path
    config_file: Path
    admin_token: str | None
    cors_origins: list[str]
    rate_limit_per_minute: int
    # Behind a proxy (Vercel, nginx) every request comes from the proxy's address, so the
    # rate limit must key on the client IP the proxy forwards instead.
    trust_proxy_headers: bool = False
    # How many proxies append to X-Forwarded-For in front of the app: the client is that many
    # entries from the right (entries further left are whatever the client sent).
    trusted_proxy_hops: int = 1
    # Optional: only believe forwarded headers from these peers (IPs or CIDRs). Empty = any peer.
    trusted_proxies: tuple[str, ...] = ()
    # Login limits: "database" shares them through DATABASE_URL (all instances count together),
    # "memory" keeps them per process, "auto" = database when DATABASE_URL is Postgres.
    rate_limit_backend: str = "auto"
    # The in-memory limiters forget the least recently seen clients beyond this many.
    rate_limit_max_keys: int = 10_000
    # Shared site password. None = no password (local development and tests).
    site_password: str | None = None
    session_secret: str = ""
    session_days: int = 7
    # On a public host the site must never run open by accident: without a password,
    # every protected route refuses to answer.
    require_password: bool = False
    # Invoicing (docs/BRD-cart-invoice.md section 8.6). No passcode = invoicing off.
    staff_passcode: str | None = None
    secret_key: str | None = None
    # Team tab: changing employees and correcting attendance (a stand-in for role-based login).
    # No passcode = nobody can make those changes; check-in/out still works.
    admin_passcode: str | None = None
    database_url: str | None = None
    invoice_config_file: Path = ROOT / "config" / "invoice.yaml"
    # Emailing invoices (config/invoice.yaml `email`). No SMTP_PASSWORD = no emails.
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_user: str | None = None  # None = the `email.to` address sends to itself
    smtp_password: str | None = None


def _env(name: str, default: str) -> str:
    """A variable set to an empty string (easy to do in a hosting dashboard) counts as unset."""
    value = os.getenv(name, "").strip()
    return value or default


def _env_int(name: str, default: int) -> int:
    value = _env(name, str(default))
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"{name} must be a whole number, got {value!r}") from None


def _rate_limit_backend() -> str:
    value = _env("RATE_LIMIT_BACKEND", "auto").lower()
    if value not in ("auto", "memory", "database"):
        raise ValueError(f"RATE_LIMIT_BACKEND must be auto, memory or database, got {value!r}")
    return value


def get_settings() -> Settings:
    return Settings(
        data_file=Path(_env("DATA_FILE", str(ROOT / "data" / "Printevr_Pricing_Master_2025-26.xlsx"))),
        config_file=Path(_env("CONFIG_FILE", str(ROOT / "config" / "products.yaml"))),
        admin_token=_env("ADMIN_TOKEN", "") or None,
        cors_origins=[o.strip() for o in _env("CORS_ORIGIN", "http://localhost:5173").split(",") if o.strip()],
        rate_limit_per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 60),
        trust_proxy_headers=_env("TRUST_PROXY_HEADERS", "1" if os.getenv("VERCEL") else "0") == "1",
        trusted_proxy_hops=max(1, _env_int("TRUSTED_PROXY_HOPS", 1)),
        trusted_proxies=tuple(p.strip() for p in _env("TRUSTED_PROXIES", "").split(",") if p.strip()),
        rate_limit_backend=_rate_limit_backend(),
        rate_limit_max_keys=max(100, _env_int("RATE_LIMIT_MAX_KEYS", 10_000)),
        site_password=_env("SITE_PASSWORD", "") or None,
        session_secret=_env("SESSION_SECRET", ""),
        session_days=_env_int("SESSION_DAYS", 7),
        require_password=bool(os.getenv("VERCEL")),
        staff_passcode=_env("STAFF_PASSCODE", "") or None,
        secret_key=_env("SECRET_KEY", "") or None,
        admin_passcode=_env("ADMIN_PASSCODE", "") or None,
        # Serverless disks are wiped between requests, so there is no SQLite default on Vercel:
        # without DATABASE_URL, invoices are rendered and downloaded but not stored.
        database_url=_env("DATABASE_URL", "") or (None if os.getenv("VERCEL") else DEFAULT_DATABASE_URL),
        invoice_config_file=Path(_env("INVOICE_CONFIG_FILE", str(ROOT / "config" / "invoice.yaml"))),
        smtp_host=_env("SMTP_HOST", "smtp.gmail.com"),
        smtp_port=_env_int("SMTP_PORT", 465),
        smtp_user=_env("SMTP_USER", "") or None,
        # Gmail shows app passwords in groups of four; the spaces aren't part of it.
        smtp_password=_env("SMTP_PASSWORD", "").replace(" ", "") or None,
    )
