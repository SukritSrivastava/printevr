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


def get_settings() -> Settings:
    return Settings(
        data_file=Path(os.getenv("DATA_FILE", ROOT / "data" / "Printevr_Pricing_Master_2025-26.xlsx")),
        config_file=Path(os.getenv("CONFIG_FILE", ROOT / "config" / "products.yaml")),
        admin_token=os.getenv("ADMIN_TOKEN") or None,
        cors_origins=[o.strip() for o in os.getenv("CORS_ORIGIN", "http://localhost:5173").split(",") if o.strip()],
        rate_limit_per_minute=int(os.getenv("RATE_LIMIT_PER_MINUTE", "60")),
    )
