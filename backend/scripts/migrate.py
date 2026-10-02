"""Apply backend/migrations/*.sql to the hosted Postgres, in order, each once.

    python backend/scripts/migrate.py            # apply what's new
    python backend/scripts/migrate.py --status   # list applied and pending files, change nothing

The database comes from DATABASE_URL_UNPOOLED (Neon's direct connection, best for schema
changes), else DATABASE_URL. Applied files are recorded in `schema_migrations`; each file runs
in its own transaction, so a failing file leaves nothing half-done. Never edit a file that has
been applied: add a new one.
"""
import argparse
import os
import sys
from pathlib import Path

import psycopg

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"


def database_url() -> str:
    for name in ("DATABASE_URL_UNPOOLED", "DATABASE_URL"):
        value = os.getenv(name, "").strip()
        if value:
            return value.replace("postgresql+psycopg://", "postgresql://", 1)
    sys.exit("Set DATABASE_URL_UNPOOLED (or DATABASE_URL) to the Postgres connection string.")


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def applied(conn: psycopg.Connection) -> set[str]:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version VARCHAR(200) PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    conn.commit()
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def migrate(url: str, status_only: bool = False, out=print) -> list[str]:
    """Applies pending files; returns their names."""
    with psycopg.connect(url, prepare_threshold=None) as conn:
        done = applied(conn)
        pending = [f for f in migration_files() if f.name not in done]
        for f in migration_files():
            out(f"{'applied' if f.name in done else 'pending'}  {f.name}")
        if status_only:
            return [f.name for f in pending]
        for f in pending:
            with conn.transaction():
                conn.execute(f.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (f.name,))
            out(f"applied  {f.name}  (just now)")
        if not pending:
            out("Nothing to apply: the database is up to date.")
        return [f.name for f in pending]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true", help="show applied and pending files only")
    args = parser.parse_args()
    migrate(database_url(), status_only=args.status)


if __name__ == "__main__":
    main()
