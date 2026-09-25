"""Runtime settings, read from the environment."""
import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


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


def get_settings() -> Settings:
    return Settings(
        data_file=Path(_env("DATA_FILE", str(ROOT / "data" / "Printevr_Pricing_Master_2025-26.xlsx"))),
        config_file=Path(_env("CONFIG_FILE", str(ROOT / "config" / "products.yaml"))),
        admin_token=_env("ADMIN_TOKEN", "") or None,
        cors_origins=[o.strip() for o in _env("CORS_ORIGIN", "http://localhost:5173").split(",") if o.strip()],
        rate_limit_per_minute=_env_int("RATE_LIMIT_PER_MINUTE", 60),
        trust_proxy_headers=_env("TRUST_PROXY_HEADERS", "1" if os.getenv("VERCEL") else "0") == "1",
    )
