"""Versioned schema migrations from backend/migrations/, for Postgres and SQLite.

Two kinds of file, numbered in one sequence (`NNNN_name.sql` / `NNNN_name.py`):

- `.sql`: Postgres only (the Designer Assignment files 0001-0002; SQLite builds those tables
  from app/designers/models.py instead).
- `.py`: every dialect. The module defines `upgrade(ctx)`, which uses only `ctx.execute`,
  `ctx.tables()` and `ctx.columns(table)` with hand-written SQL, so a migration never changes
  when the models do.

Each pending file runs in its own transaction, together with its row in `schema_migrations`,
so a failing file leaves nothing half-done and an applied file never runs again. The
transaction first takes a database-wide lock (Postgres `pg_advisory_xact_lock`, SQLite
`BEGIN IMMEDIATE`) and only then checks whether the file is still pending, so any number of
processes can run the migrations at the same moment: one applies each file and the others
wait, then skip it. The lock is transaction-scoped, so it also works through a
transaction-mode pooler. Never edit a file that has been applied anywhere: add a new one.
"""
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy.engine import Engine

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
# pg_advisory_xact_lock key for migrations (app-unique; store.SERIES_LOCK_BASE uses 72_810_000+).
LOCK_KEY = 72_809_999

TRACKING_TABLE = {
    "postgresql": (
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version VARCHAR(200) PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    ),
    "sqlite": (
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version VARCHAR(200) NOT NULL PRIMARY KEY, applied_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    ),
}


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    path: Path

    @property
    def name(self) -> str:
        return self.path.name

    def runs_on(self, dialect: str) -> bool:
        return self.path.suffix == ".py" or dialect == "postgresql"

    def apply(self, ctx: "Context") -> None:
        if self.path.suffix == ".sql":
            ctx.execute_script(self.path.read_text(encoding="utf-8"))
            return
        spec = importlib.util.spec_from_file_location(f"migration_{self.path.stem}", self.path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.upgrade(ctx)


def migration_files() -> list[Migration]:
    files = [*MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"), *MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.py")]
    return [Migration(p) for p in sorted(files, key=lambda p: p.name)]


class Context:
    """What a migration gets: one DB-API connection inside the migration's transaction."""

    def __init__(self, dbapi, dialect: str):
        self.dbapi = dbapi
        self.dialect = dialect

    def execute(self, sql: str, params: tuple = ()) -> list[tuple]:
        """One statement; placeholders are written %s for both dialects."""
        cur = self.dbapi.cursor()
        try:
            if self.dialect == "sqlite":
                cur.execute(sql.replace("%s", "?"), params)
            else:
                cur.execute(sql, params or None)
            return cur.fetchall() if cur.description else []
        finally:
            cur.close()

    def execute_script(self, sql: str) -> None:
        """Several statements, no parameters (the .sql files)."""
        if self.dialect == "sqlite":
            raise MigrationError("SQL files are Postgres-only")
        cur = self.dbapi.cursor()
        try:
            cur.execute(sql)
        finally:
            cur.close()

    def tables(self) -> set[str]:
        if self.dialect == "sqlite":
            rows = self.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        else:
            rows = self.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
            )
        return {r[0] for r in rows}

    def columns(self, table: str) -> set[str]:
        if self.dialect == "sqlite":
            return {r[1] for r in self.execute(f'PRAGMA table_info("{table}")')}
        rows = self.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = %s",
            (table,),
        )
        return {r[0] for r in rows}


def _dialect(engine: Engine) -> str:
    name = engine.dialect.name
    if name not in TRACKING_TABLE:
        raise MigrationError(f"Unsupported database: {name}")
    return name


class _Transaction:
    """A locked transaction on a raw DB-API connection (see the module docstring)."""

    def __init__(self, engine: Engine):
        self.dialect = _dialect(engine)
        self.raw = engine.raw_connection()
        self.dbapi = self.raw.driver_connection
        self._saved_autocommit = None

    def __enter__(self) -> Context:
        ctx = Context(self.dbapi, self.dialect)
        if self.dialect == "sqlite":
            # Take the transaction into our own hands: BEGIN IMMEDIATE takes the write lock now,
            # before reading schema_migrations, and SQLite DDL is transactional.
            self._saved_autocommit = self.dbapi.autocommit
            self.dbapi.autocommit = True
            ctx.execute("BEGIN IMMEDIATE")
        else:
            ctx.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))
        ctx.execute(TRACKING_TABLE[self.dialect])
        return ctx

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            if self.dialect == "sqlite":
                self.dbapi.execute("ROLLBACK" if exc_type else "COMMIT")
            elif exc_type:
                self.dbapi.rollback()
            else:
                self.dbapi.commit()
        finally:
            if self._saved_autocommit is not None:
                self.dbapi.autocommit = self._saved_autocommit
            self.raw.close()


def applied(engine: Engine) -> set[str]:
    """Versions recorded in schema_migrations (empty if the table isn't there). Takes no lock."""
    dialect = _dialect(engine)
    raw = engine.raw_connection()
    try:
        ctx = Context(raw.driver_connection, dialect)
        if "schema_migrations" not in ctx.tables():
            return set()
        return {r[0] for r in ctx.execute("SELECT version FROM schema_migrations")}
    finally:
        raw.rollback()
        raw.close()


def pending(engine: Engine) -> list[str]:
    dialect = _dialect(engine)
    done = applied(engine)
    return [m.name for m in migration_files() if m.runs_on(dialect) and m.name not in done]


def migrate(engine: Engine, status_only: bool = False, out: Callable[[str], None] = print) -> list[str]:
    """Applies pending migrations in order; returns the names this call applied (with
    status_only, the names still pending, applying nothing)."""
    dialect = _dialect(engine)
    files = [m for m in migration_files() if m.runs_on(dialect)]
    done = applied(engine)
    for m in files:
        out(f"{'applied' if m.name in done else 'pending'}  {m.name}")
    if status_only:
        return [m.name for m in files if m.name not in done]
    ran: list[str] = []
    for m in files:
        if m.name in done:
            continue
        with _Transaction(engine) as ctx:
            # Re-checked under the lock: another process may have applied it meanwhile.
            if ctx.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (m.name,)):
                continue
            m.apply(ctx)
            ctx.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (m.name,))
        ran.append(m.name)
        out(f"applied  {m.name}  (just now)")
    if not ran:
        out("Nothing to apply: the database is up to date.")
    return ran

