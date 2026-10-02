"""Designer Assignment schema: SQL migrations (Postgres) and the SQLite mirror."""
import psycopg
import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.designers import schema
from app.designers.models import DesignBase, Designer, RotationState

from .pg import migrate, needs_postgres, pg_url  # noqa: F401  (fixture)


def sqlite_engine(tmp_path):
    return create_engine(f"sqlite:///{(tmp_path / 'd.db').as_posix()}")


def test_sqlite_prepare_creates_and_seeds_once(tmp_path):
    engine = sqlite_engine(tmp_path)
    assert schema.prepare(engine)
    assert schema.prepare(engine)  # second start: nothing doubles
    with Session(engine) as s:
        designers = s.scalars(select(Designer).order_by(Designer.rotation_order)).all()
        assert [(d.name, d.rotation_order, d.active) for d in designers] == [("Namit", 1, True), ("Ajendra", 2, True)]
        state = s.get(RotationState, 1)
        assert (state.last_order, state.seq) == (0, 0)


def test_migration_files_are_numbered_and_unique():
    names = [f.name for f in migrate.migration_files()]
    assert names == sorted(names)
    assert names[:2] == ["0001_designer_jobs.sql", "0002_seed_designers.sql"]
    assert len({n[:4] for n in names}) == len(names)


@needs_postgres
def test_migrations_apply_once_and_seed(pg_url):
    lines: list[str] = []
    assert migrate.migrate(pg_url, out=lines.append) == ["0001_designer_jobs.sql", "0002_seed_designers.sql"]
    assert migrate.migrate(pg_url, out=lines.append) == []  # already applied
    with psycopg.connect(pg_url) as conn:
        assert conn.execute("SELECT name, rotation_order, active FROM designers ORDER BY rotation_order").fetchall() == [
            ("Namit", 1, True), ("Ajendra", 2, True),
        ]
        assert conn.execute("SELECT last_order, seq FROM rotation_state").fetchall() == [(0, 0)]


@needs_postgres
def test_models_match_migrations(pg_url):
    """The SQLite mirror (models.py) has the same tables and columns as the SQL files."""
    migrate.migrate(pg_url, out=lambda _: None)
    engine = create_engine(pg_url.replace("postgresql://", "postgresql+psycopg://", 1))
    assert schema.prepare(engine)
    insp = inspect(engine)
    for table in DesignBase.metadata.sorted_tables:
        in_db = {c["name"]: c["nullable"] for c in insp.get_columns(table.name)}
        in_model = {c.name: c.nullable for c in table.columns}
        assert in_db == in_model, table.name
    engine.dispose()


@needs_postgres
def test_database_enforces_the_rules(pg_url):
    migrate.migrate(pg_url, out=lambda _: None)
    insert = (
        "INSERT INTO design_jobs (series, bill_no, customer_name, invoice_total, items_summary, status)"
        " VALUES (%s, %s, 'A', 1, 'x', %s)"
    )
    with psycopg.connect(pg_url, autocommit=True) as conn:
        conn.execute(insert, ("non_gst", 1, 1))
        conn.execute(insert, ("gst", 1, 1))  # same number, other series: fine
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(insert, ("non_gst", 1, 1))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, ("non_gst", 2, 5))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(insert, ("quotation", 3, 1))
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("INSERT INTO rotation_state (id) VALUES (2)")

