"""Invoice tables, Postgres and SQLite: what Store used to build at runtime with create_all()
plus ALTER TABLE ADD COLUMN, now as a versioned migration.

It upgrades every schema the app has created so far, without touching a row:

- a new database: creates all five tables;
- the first invoice schema (only `invoices` and `invoice_events`, before GST invoices,
  quotations, per-invoice advance percent and event series): adds the missing tables and the
  missing columns, all nullable, so existing invoices, payments and events stay as they are
  (rows that predate a column read it as NULL, which the app already handles);
- a database already brought up to date by the old runtime code: nothing to do.

Index names are the ones create_all() gave them, so CREATE INDEX IF NOT EXISTS finds them.
A table that exists but lacks a NOT NULL column is a schema this file doesn't know; it stops
rather than guess. Frozen: never edit this file once applied; add a new migration instead.
"""

TYPES = {
    "postgresql": {"pk": "SERIAL", "json": "JSON", "ts": "TIMESTAMP WITH TIME ZONE"},
    "sqlite": {"pk": "INTEGER", "json": "JSON", "ts": "DATETIME"},
}

# (name, type, NOT NULL). {pk}/{json}/{ts} are filled per dialect.
DOCUMENT = [
    ("id", "{pk}", True),
    ("bill_no", "INTEGER", True),
    ("invoice_date", "DATE", True),
    ("billing_type", "VARCHAR(16)", True),
    ("business_name", "VARCHAR(60)", True),
    ("customer", "{json}", True),
    ("lines", "{json}", True),
    ("payments", "{json}", True),
    ("saving_amount", "NUMERIC(12, 2)", False),
    ("total", "NUMERIC(12, 2)", True),
    ("gst_amount", "NUMERIC(12, 2)", True),
    ("gst", "{json}", False),
    ("payable", "NUMERIC(12, 2)", True),
    ("advance_pct", "NUMERIC(5, 2)", False),
    ("received", "NUMERIC(12, 2)", True),
    ("status", "VARCHAR(16)", True),
    ("version", "INTEGER", True),
    ("created_at", "{ts}", True),
    ("updated_at", "{ts}", True),
]

TABLES = {
    "invoices": (DOCUMENT + [("salesperson", "VARCHAR(100)", False)], "id"),
    "gst_invoices": (DOCUMENT + [("details", "{json}", True)], "id"),
    "quotations": (DOCUMENT, "id"),
    "document_counters": ([("series", "VARCHAR(16)", True), ("last_no", "INTEGER", True)], "series"),
    "invoice_events": (
        [
            ("id", "{pk}", True),
            ("bill_no", "INTEGER", True),
            ("series", "VARCHAR(16)", False),
            ("event", "VARCHAR(20)", True),
            ("at", "{ts}", True),
            ("detail", "{json}", True),
        ],
        "id",
    ),
}

INDEXES = [
    ("ix_invoices_bill_no", "invoices", "bill_no", True),
    ("ix_invoices_business_name", "invoices", "business_name", False),
    ("ix_gst_invoices_bill_no", "gst_invoices", "bill_no", True),
    ("ix_gst_invoices_business_name", "gst_invoices", "business_name", False),
    ("ix_quotations_bill_no", "quotations", "bill_no", True),
    ("ix_quotations_business_name", "quotations", "business_name", False),
    ("ix_invoice_events_bill_no", "invoice_events", "bill_no", False),
]


def upgrade(ctx) -> None:
    types = TYPES[ctx.dialect]
    have_tables = ctx.tables()
    for table, (columns, pk) in TABLES.items():
        if table not in have_tables:
            cols = [f"{name} {kind.format(**types)}{' NOT NULL' if not_null else ''}" for name, kind, not_null in columns]
            ctx.execute(f"CREATE TABLE {table} ({', '.join(cols)}, PRIMARY KEY ({pk}))")
            continue
        have = ctx.columns(table)
        for name, kind, not_null in columns:
            if name in have:
                continue
            if not_null:
                raise RuntimeError(f"{table} exists without its NOT NULL column {name}: unknown schema, fix it by hand")
            ctx.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind.format(**types)}")
    for name, table, column, unique in INDEXES:
        ctx.execute(f"CREATE {'UNIQUE ' if unique else ''}INDEX IF NOT EXISTS {name} ON {table} ({column})")
