"""Invoice-table migrations (backend/migrations/0003_invoice_tables.py, 0004_rate_limits.py).

Covers a new database, the first invoice schema (what var/invoices.db still looks like), a
schema the old runtime create_all()/ALTER code brought up to date, reruns, several processes
starting at once, and that issued invoices, payments, events, counters and design jobs come
through untouched. SQLite always; Postgres too when TEST_DATABASE_URL is set.
"""
import dataclasses
import json
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from app import migrations
from app.designers import schema as designer_schema
from app.invoice.store import Base, SchemaNotReady, Store, missing_schema
from app.main import create_app
from app.settings import get_settings

from .pg import migrate, needs_postgres, temp_schema
from .test_invoice_api import PASSCODE

ALL = ["0003_invoice_tables.py", "0004_rate_limits.py", "0005_production.py", "0006_production_stages.py", "0007_product_tracking.py",
       "0008_design_final_statuses.py"]
PG_ALL = ["0001_designer_jobs.sql", "0002_seed_designers.sql", *ALL]

# The first invoice schema, exactly as create_all() made it before GST invoices, quotations,
# advance_pct and event series existed (copied from a real var/invoices.db).
FIRST_SCHEMA = {
    "sqlite": [
        """CREATE TABLE invoice_events (id INTEGER NOT NULL, bill_no INTEGER NOT NULL, event VARCHAR(20) NOT NULL,
            at DATETIME NOT NULL, detail JSON NOT NULL, PRIMARY KEY (id))""",
        """CREATE TABLE invoices (id INTEGER NOT NULL, bill_no INTEGER NOT NULL, invoice_date DATE NOT NULL,
            billing_type VARCHAR(16) NOT NULL, business_name VARCHAR(60) NOT NULL, customer JSON NOT NULL,
            lines JSON NOT NULL, payments JSON NOT NULL, saving_amount NUMERIC(12, 2), total NUMERIC(12, 2) NOT NULL,
            gst_amount NUMERIC(12, 2) NOT NULL, payable NUMERIC(12, 2) NOT NULL, received NUMERIC(12, 2) NOT NULL,
            status VARCHAR(16) NOT NULL, version INTEGER NOT NULL, created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL, PRIMARY KEY (id))""",
        "CREATE INDEX ix_invoice_events_bill_no ON invoice_events (bill_no)",
        "CREATE UNIQUE INDEX ix_invoices_bill_no ON invoices (bill_no)",
        "CREATE INDEX ix_invoices_business_name ON invoices (business_name)",
    ],
}
FIRST_SCHEMA["postgresql"] = [
    s.replace("id INTEGER NOT NULL", "id SERIAL NOT NULL").replace("DATETIME", "TIMESTAMP WITH TIME ZONE")
    for s in FIRST_SCHEMA["sqlite"]
]

CUSTOMER = {"business_name": "Sogat Jutti Store", "contact_person": "", "address": "Sector 67, Mohali", "phone": "+91 95010 60618"}
LINE = {
    "id": "l1", "source": "custom", "parent_id": None, "calc_request": None, "title": "Customised rigid box printing",
    "specs": [], "customisations": [], "quantity": 1000, "unit_label": "boxes", "middle": {"kind": "none"},
    "catalogue_unit_price": None, "unit_price": "148", "warnings": [], "price_edited": False,
}
PAYMENT = {"amount": "30000", "date": "2026-09-09", "mode": "upi", "note": None, "recorded_at": "2026-09-09T10:00:00+00:00"}


def insert_first_schema_rows(conn) -> None:
    """Two issued invoices (one part-paid) and their events, as the first schema stored them."""
    invoice = text(
        "INSERT INTO invoices (bill_no, invoice_date, billing_type, business_name, customer, lines, payments,"
        " saving_amount, total, gst_amount, payable, received, status, version, created_at, updated_at)"
        " VALUES (:no, '2026-09-14', 'without_gst', 'Sogat Jutti Store', :customer, :lines, :payments,"
        " 30000, 148000, 0, 148000, :received, :status, :version, '2026-09-14 10:00:00+00', '2026-09-15 10:00:00+00')"
    )
    conn.execute(invoice, {"no": 18, "customer": json.dumps(CUSTOMER), "lines": json.dumps([LINE]),
                           "payments": json.dumps([PAYMENT]), "received": 30000, "status": "part_paid", "version": 2})
    conn.execute(invoice, {"no": 19, "customer": json.dumps(CUSTOMER), "lines": json.dumps([LINE]),
                           "payments": "[]", "received": 0, "status": "unpaid", "version": 1})
    event = text("INSERT INTO invoice_events (bill_no, event, at, detail) VALUES (:no, :event, '2026-09-14 10:00:00+00', :detail)")
    for no, ev in ((18, "created"), (18, "payment_added"), (19, "created")):
        conn.execute(event, {"no": no, "event": ev, "detail": json.dumps({"version": 1})})


def snapshot(engine, tables=("invoices", "invoice_events")) -> dict:
    """Every row of every table, as the database returns it: any rewrite shows up."""
    with engine.connect() as conn:
        return {t: [tuple(r) for r in conn.execute(text(f"SELECT * FROM {t} ORDER BY 1"))] for t in tables}


def strip_new_columns(rows: list[tuple], before: list[tuple]) -> list[tuple]:
    """Columns added by the migration come last; the old ones must be identical."""
    width = len(before[0])
    return [r[:width] for r in rows]


# ---------------------------------------------------------------- backends


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=needs_postgres)])
def db(request, tmp_path):
    """(url, dialect) of an empty database."""
    if request.param == "sqlite":
        yield f"sqlite:///{(tmp_path / 'invoices.db').as_posix()}", "sqlite"
    else:
        with temp_schema() as url:
            yield url, "postgresql"


def engine_for(url: str):
    return migrate.engine_for(url)


def open_store(url: str, dialect: str) -> Store:
    """What the app does: SQLite migrates itself; Postgres is migrated first (deploy step)."""
    if dialect == "postgresql":
        migrate.migrate(url, out=lambda _: None)
    return Store(url)


# ---------------------------------------------------------------- tests


def test_files_are_numbered_and_both_dialects_know_which_to_run():
    names = [m.name for m in migrations.migration_files()]
    assert names == PG_ALL
    assert [m.name for m in migrations.migration_files() if m.runs_on("sqlite")] == ALL


def test_new_database_matches_the_models(db):
    url, dialect = db
    store = open_store(url, dialect)
    try:
        assert missing_schema(store.engine) == []
        assert migrations.pending(store.engine) == []
        insp = inspect(store.engine)
        for table in Base.metadata.sorted_tables:
            in_db = {c["name"]: c["nullable"] for c in insp.get_columns(table.name)}
            in_model = {c.name: c.nullable for c in table.columns}
            assert in_db == in_model, table.name
            unique = {tuple(i["column_names"]) for i in insp.get_indexes(table.name) if i["unique"]}
            if "bill_no" in in_model and table.name != "invoice_events":
                assert ("bill_no",) in unique, table.name
        assert "rate_limit_counters" in insp.get_table_names()
    finally:
        store.engine.dispose()


def test_rerunning_changes_nothing(db):
    url, dialect = db
    expected = PG_ALL if dialect == "postgresql" else ALL
    assert migrate.migrate(url, out=lambda _: None) == expected
    assert migrate.migrate(url, out=lambda _: None) == []
    lines: list[str] = []
    assert migrate.migrate(url, status_only=True, out=lines.append) == []
    assert all(line.startswith("applied") for line in lines)
    engine = engine_for(url)
    with engine.connect() as conn:
        assert sorted(r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))) == expected
    engine.dispose()


def test_upgrade_from_the_first_schema_keeps_every_row(db):
    url, dialect = db
    engine = engine_for(url)
    with engine.begin() as conn:
        for stmt in FIRST_SCHEMA[dialect]:
            conn.execute(text(stmt))
        insert_first_schema_rows(conn)
    before = snapshot(engine)
    engine.dispose()

    store = open_store(url, dialect)
    try:
        after = snapshot(store.engine)
        for table in before:
            assert strip_new_columns(after[table], before[table]) == before[table], table
        with store.engine.connect() as conn:
            # New columns are NULL on old rows; the new tables are there and empty.
            assert conn.execute(text("SELECT advance_pct, gst, salesperson FROM invoices")).fetchall() == [(None,) * 3] * 2
            assert conn.execute(text("SELECT series FROM invoice_events")).fetchall() == [(None,)] * 3
            for t in ("gst_invoices", "quotations", "document_counters"):
                assert conn.execute(text(f"SELECT count(*) FROM {t}")).scalar() == 0
        assert missing_schema(store.engine) == []
    finally:
        store.engine.dispose()

    # The app reads, reprints and numbers after the old invoices as before.
    app = create_app(dataclasses.replace(get_settings(), staff_passcode=PASSCODE, secret_key="s", database_url=url))
    client = TestClient(app)
    token = client.post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    listing = client.get("/api/invoices").json()
    assert [(r["bill_no"], r["status"]) for r in listing["invoices"]] == [(19, "unpaid"), (18, "part_paid")]
    pdf = client.get("/api/invoices/18/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert client.get("/api/invoices/next-bill-no").json()["next_bill_no"] == 20
    app.state.invoices["store"].engine.dispose()


def test_upgrade_from_the_old_runtime_schema_keeps_invoices_counters_and_jobs(db):
    """A database the old Store built with create_all() + ALTER (no schema_migrations for
    invoices): migrating records the versions and touches no row."""
    url, dialect = db
    engine = engine_for(url)
    if dialect == "postgresql":
        migrate.migrate(url, out=lambda _: None)  # designer migrations, as production has them
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM schema_migrations WHERE version IN ('0003_invoice_tables.py', '0004_rate_limits.py')"))
            conn.execute(text("DROP TABLE rate_limit_counters"))
            for t in ("invoices", "gst_invoices", "quotations", "document_counters", "invoice_events"):
                conn.execute(text(f"DROP TABLE {t}"))
    else:
        designer_schema.prepare(engine)
    Base.metadata.create_all(engine)  # what the old runtime code left behind
    with engine.begin() as conn:
        insert_first_schema_rows(conn)
        conn.execute(text("INSERT INTO document_counters (series, last_no) VALUES ('non_gst', 25), ('gst', 4)"))
        conn.execute(text(
            "INSERT INTO design_jobs (series, bill_no, customer_name, invoice_total, items_summary, designer_id,"
            " assignment_seq, assigned_at, status, vendor_name, updated_at)"
            " VALUES ('non_gst', 18, 'Sogat Jutti Store', 148000, 'Box x1000', 1, 1, '2026-09-14 10:00:00+00', 3, 'Vendor A',"
            " '2026-09-15 10:00:00+00')"
        ))
    tables = ("invoices", "invoice_events", "document_counters", "design_jobs", "designers", "rotation_state")
    before = snapshot(engine, tables)
    engine.dispose()

    store = open_store(url, dialect)
    try:
        assert snapshot(store.engine, tables) == before
        assert migrations.pending(store.engine) == []
        with store.session() as s:
            # The counter still decides the next number (25 was issued, then deleted).
            assert store.next_bill_no(s, 19, "non_gst") == 26
    finally:
        store.engine.dispose()


def test_an_unknown_schema_stops_without_half_changes(db):
    url, dialect = db
    engine = engine_for(url)
    with engine.begin() as conn:
        # invoice_events is the last table 0003 handles: the four before it get created first.
        conn.execute(text("CREATE TABLE invoice_events (id INTEGER PRIMARY KEY, note VARCHAR(10))"))
        conn.execute(text("INSERT INTO invoice_events (id, note) VALUES (1, 'keep me')"))
    engine.dispose()
    with pytest.raises(Exception, match="bill_no"):
        migrate.migrate(url, out=lambda _: None)
    engine = engine_for(url)
    insp = inspect(engine)
    tables = set(insp.get_table_names())
    assert not tables & {"invoices", "gst_invoices", "quotations", "document_counters"}  # rolled back
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id, note FROM invoice_events")).fetchall() == [(1, "keep me")]
    assert "0003_invoice_tables.py" not in migrations.applied(engine)
    engine.dispose()


def test_many_processes_starting_at_once_apply_each_file_once(db):
    url, dialect = db
    engine = engine_for(url)
    with engine.begin() as conn:
        for stmt in FIRST_SCHEMA[dialect]:
            conn.execute(text(stmt))
        insert_first_schema_rows(conn)
    before = snapshot(engine)
    engine.dispose()

    n = 8
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []
    applied: list[list[str]] = []

    def start():
        try:
            barrier.wait()
            applied.append(migrate.migrate(url, out=lambda _: None))
        except BaseException as exc:  # collected, asserted below
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(n)]
    [t.start() for t in threads]
    [t.join(timeout=120) for t in threads]
    assert errors == []
    expected = PG_ALL if dialect == "postgresql" else ALL
    assert sorted(name for names in applied for name in names) == sorted(expected)  # each file once overall
    engine = engine_for(url)
    with engine.connect() as conn:
        assert sorted(r[0] for r in conn.execute(text("SELECT version FROM schema_migrations"))) == expected
    after = snapshot(engine)
    for table in before:
        assert strip_new_columns(after[table], before[table]) == before[table]
    engine.dispose()


def test_sqlite_stores_opening_at_once_all_work(tmp_path):
    """uvicorn --workers N on one SQLite file: every worker opens its Store at the same time."""
    url = f"sqlite:///{(tmp_path / 'invoices.db').as_posix()}"
    n = 6
    barrier = threading.Barrier(n)
    errors: list[BaseException] = []
    stores: list[Store] = []

    def start():
        try:
            barrier.wait()
            stores.append(Store(url))
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=start) for _ in range(n)]
    [t.start() for t in threads]
    [t.join(timeout=120) for t in threads]
    assert errors == [] and len(stores) == n
    assert migrations.applied(stores[0].engine) == set(ALL)
    for s in stores:
        s.engine.dispose()


@needs_postgres
def test_postgres_store_is_never_built_at_runtime():
    """Before the migrations, a Postgres Store refuses (no CREATE/ALTER from the app) and the
    API says so to staff without internals."""
    with temp_schema() as url:
        with pytest.raises(SchemaNotReady):
            Store(url)
        engine = engine_for(url)
        assert inspect(engine).get_table_names() == []  # the app created nothing
        engine.dispose()

        app = create_app(dataclasses.replace(get_settings(), staff_passcode=PASSCODE, secret_key="s", database_url=url))
        client = TestClient(app)
        token = client.post("/api/staff/login", json={"passcode": PASSCODE}).json()["token"]
        r = client.get("/api/invoices", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 503 and r.json()["error"]["code"] == "STORAGE_NOT_READY"
        assert "migrations" in r.json()["error"]["message"]
        assert "postgres" not in r.text.lower() and "invoices," not in r.text

        migrate.migrate(url, out=lambda _: None)  # the deploy step
        assert client.get("/api/invoices", headers={"Authorization": f"Bearer {token}"}).status_code == 200

