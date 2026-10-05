"""Design statuses 5 (Final design) and 6 (Final vendor), Postgres and SQLite.

The status columns of design_jobs, job_status_history and design_items had CHECK (... BETWEEN
1 AND 4); they now allow 1 to 6. Only the constraints change: no row is read, rewritten or
deleted, and every existing value (1-4) still passes.

- Postgres: each old CHECK on those columns is dropped and `<table>_<column>_check` added with
  the wider range.
- SQLite can't alter a CHECK, and rebuilding the tables would rewrite their rows, so the stored
  CREATE TABLE text is widened in place (SQLite's documented writable_schema procedure for a
  change that doesn't touch stored data). SQLite builds design_jobs from the models, which
  already say 1 to 6, so only an existing database's design_jobs and design_items change.
Frozen once applied: add a new migration instead.
"""

COLUMNS = {
    "design_jobs": ("status",),
    "job_status_history": ("old_status", "new_status"),
    "design_items": ("status",),
}
OLD = "status BETWEEN 1 AND 4"
NEW = "status BETWEEN 1 AND 6"


def _postgres(ctx, have: set[str]) -> None:
    for table, columns in COLUMNS.items():
        if table not in have:
            continue
        for column in columns:
            for (name,) in ctx.execute(
                "SELECT c.conname FROM pg_constraint c"
                " JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)"
                " WHERE c.conrelid = %s::regclass AND c.contype = 'c' AND a.attname = %s",
                (table, column),
            ):
                ctx.execute(f'ALTER TABLE {table} DROP CONSTRAINT "{name}"')
            ctx.execute(f"ALTER TABLE {table} ADD CONSTRAINT {table}_{column}_check CHECK ({column} BETWEEN 1 AND 6)")


def _sqlite(ctx, have: set[str]) -> None:
    changes = []
    for table in COLUMNS:
        if table not in have:
            continue
        (sql,) = ctx.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = %s", (table,))[0]
        if OLD in sql:
            changes.append((sql.replace(OLD, NEW), table))
    if not changes:
        return
    (version,) = ctx.execute("PRAGMA schema_version")[0]
    ctx.execute("PRAGMA writable_schema = ON")
    for sql, table in changes:
        ctx.execute("UPDATE sqlite_master SET sql = %s WHERE type = 'table' AND name = %s", (sql, table))
    ctx.execute(f"PRAGMA schema_version = {int(version) + 1}")
    ctx.execute("PRAGMA writable_schema = OFF")
    (result,) = ctx.execute("PRAGMA quick_check")[0]
    if result != "ok":
        raise RuntimeError(f"quick_check after widening the design status checks: {result}")


def upgrade(ctx) -> None:
    have = ctx.tables()
    if ctx.dialect == "postgresql":
        _postgres(ctx, have)
    else:
        _sqlite(ctx, have)
