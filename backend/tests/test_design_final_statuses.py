"""Migration 0008: design statuses 5 (Final design) and 6 (Final vendor) on a database whose
checks still say 1 to 4. Existing rows come through untouched. SQLite always; Postgres too
when TEST_DATABASE_URL is set."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

from app import migrations
from app.designers.models import DesignBase, DesignJob

from .pg import migrate, needs_postgres, temp_schema

NEW = "0008_design_final_statuses.py"
JOB = (
    "INSERT INTO design_jobs (id, series, bill_no, customer_name, invoice_total, items_summary, assigned_at, status,"
    " vendor_name, updated_at) VALUES (:id, 'non_gst', :bill, 'A', 100, 'Box x1', '2026-10-01 10:00:00+00', :status,"
    " :vendor, '2026-10-02 10:00:00+00')"
)
ITEM = (
    "INSERT INTO design_items (job_id, line_no, designer_id, status, vendor_name, updated_at)"
    " VALUES (:job, 0, NULL, :status, NULL, '2026-10-02 10:00:00+00')"
)


def old_sqlite(url: str):
    """design_jobs as create_all() built it with the four-stage check, then migrations 0003-0007."""
    engine = create_engine(url)
    old_jobs = str(CreateTable(DesignJob.__table__).compile(engine)).replace("BETWEEN 1 AND 6", "BETWEEN 1 AND 4")
    assert "BETWEEN 1 AND 4" in old_jobs
    with engine.begin() as conn:
        conn.execute(text(old_jobs))
    DesignBase.metadata.create_all(engine)  # the other designer tables; design_jobs is there already
    for m in migrations.migration_files():
        if m.runs_on("sqlite") and m.name < NEW:
            with migrations._Transaction(engine) as ctx:
                m.apply(ctx)
                ctx.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (m.name,))
    return engine


def old_postgres(url: str):
    """Everything applied, then 0008 undone: the checks back to 1-4 and its row removed."""
    migrate.migrate(url, out=lambda _: None)
    engine = migrate.engine_for(url)
    with engine.begin() as conn:
        for table, column in (("design_jobs", "status"), ("job_status_history", "old_status"),
                              ("job_status_history", "new_status"), ("design_items", "status")):
            conn.execute(text(f"ALTER TABLE {table} DROP CONSTRAINT {table}_{column}_check"))
            conn.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {table}_{column}_check CHECK ({column} BETWEEN 1 AND 4)"))
        conn.execute(text("DELETE FROM schema_migrations WHERE version = :v"), {"v": NEW})
    return engine


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=needs_postgres)])
def old_db(request, tmp_path):
    if request.param == "sqlite":
        engine = old_sqlite(f"sqlite:///{(tmp_path / 'invoices.db').as_posix()}")
        yield engine
        engine.dispose()
    else:
        with temp_schema() as url:
            engine = old_postgres(url)
            yield engine
            engine.dispose()


def rows(engine) -> dict:
    with engine.connect() as conn:
        return {
            t: conn.execute(text(f"SELECT * FROM {t} ORDER BY 1, 2")).all()
            for t in ("design_jobs", "design_items", "job_status_history")
        }


def test_old_checks_are_widened_and_rows_stay(old_db):
    with old_db.begin() as conn:
        conn.execute(text(JOB), {"id": 1, "bill": 18, "status": 4, "vendor": "Vendor A"})
        conn.execute(text(JOB), {"id": 2, "bill": 19, "status": 1, "vendor": None})
        conn.execute(text(ITEM), {"job": 1, "status": 3})
    with pytest.raises(IntegrityError), old_db.begin() as conn:
        conn.execute(text(JOB), {"id": 3, "bill": 20, "status": 5, "vendor": None})  # refused before 0008
    before = rows(old_db)
    assert migrations.pending(old_db) == [NEW]

    assert migrations.migrate(old_db, out=lambda _: None) == [NEW]
    assert rows(old_db) == before
    assert migrations.migrate(old_db, out=lambda _: None) == []

    with old_db.begin() as conn:
        conn.execute(text("UPDATE design_jobs SET status = 5 WHERE id = 1"))
        conn.execute(text("UPDATE design_jobs SET status = 6 WHERE id = 2"))
        conn.execute(text("UPDATE design_items SET status = 6 WHERE job_id = 1"))
        conn.execute(text(
            "INSERT INTO job_status_history (job_id, old_status, new_status, changed_at)"
            " VALUES (1, 5, 6, '2026-10-03 10:00:00+00')"
        ))
    for statement in ("UPDATE design_jobs SET status = 7 WHERE id = 1", "UPDATE design_items SET status = 7 WHERE job_id = 1"):
        with pytest.raises(IntegrityError), old_db.begin() as conn:
            conn.execute(text(statement))
