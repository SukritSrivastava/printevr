"""Apply backend/migrations/ to a database, in order, each once.

    python backend/scripts/migrate.py            # apply what's new
    python backend/scripts/migrate.py --status   # list applied and pending files, change nothing

The database comes from DATABASE_URL_UNPOOLED (Neon's direct connection, best for schema
changes), else DATABASE_URL. Postgres and SQLite (`sqlite:///path/to/invoices.db`) both work;
SQLite skips the Postgres-only .sql files, and the app also applies its migrations by itself
on SQLite. Applied files are recorded in `schema_migrations`; each file runs in its own
transaction under a lock, so a failing file leaves nothing half-done and running this from
several places at once is safe (app/migrations.py). Never edit a file that has been applied:
add a new one.
"""
import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine  # noqa: E402

from app import migrations  # noqa: E402
from app.invoice.store import engine_options, normalize_url  # noqa: E402

MIGRATIONS = migrations.MIGRATIONS_DIR


def database_url() -> str:
    for name in ("DATABASE_URL_UNPOOLED", "DATABASE_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value
    sys.exit("Set DATABASE_URL_UNPOOLED (or DATABASE_URL) to the database's connection string.")


def migration_files() -> list[migrations.Migration]:
    return migrations.migration_files()


def engine_for(url: str):
    url = normalize_url(url)
    return create_engine(url, **engine_options(url))


def migrate(url: str, status_only: bool = False, out=print) -> list[str]:
    """Applies pending files; returns their names (with status_only, the pending ones)."""
    engine = engine_for(url)
    try:
        return migrations.migrate(engine, status_only=status_only, out=out)
    finally:
        engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="show applied and pending files only")
    args = parser.parse_args()
    migrate(database_url(), status_only=args.status)


if __name__ == "__main__":
    main()
