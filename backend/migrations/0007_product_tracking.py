"""Per-product design and production tracking, Postgres and SQLite.

An order (invoice) can hold several products; each product is one non-add-on line of the
invoice, identified by its position in the stored lines (`line_no`, from 0; issued invoices
never change). New tables:

- production_item_progress: per production job, product and stage: vendor, Completed, Sent to
  vendor, Picked up / received (what production_stage_progress held for the whole order).
- design_items: per design job and product: designer (NULL = the order's designer), status
  (1-4, as design_jobs) and vendor.
- design_item_history: status changes of a product's design.

Existing data is adapted without guessing:
- An order with exactly one product: its order-level production stage rows and its design
  status and vendor become that product's.
- An order with several products: nothing is copied (one product's progress can't be told
  from another's). The order-level records stay where they are and the app shows them
  read-only as "recorded for the whole order"; each product starts empty.
Nothing is deleted or rewritten. Frozen once applied: add a new migration instead.
"""
import json

TYPES = {
    "postgresql": {"pk": "SERIAL", "ts": "TIMESTAMP WITH TIME ZONE"},
    "sqlite": {"pk": "INTEGER", "ts": "DATETIME"},
}
INVOICE_TABLES = {"non_gst": "invoices", "gst": "gst_invoices"}


def _product_lines(raw) -> list[int]:
    """Positions of the non-add-on lines. JSON arrives as text (SQLite) or parsed (Postgres)."""
    lines = json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or [])
    return [i for i, line in enumerate(lines) if isinstance(line, dict) and line.get("source") != "addon"]


def _single_product(ctx, have: set[str], series: str, bill_no: int) -> int | None:
    table = INVOICE_TABLES.get(series)
    if table not in have:
        return None
    rows = ctx.execute(f"SELECT lines FROM {table} WHERE bill_no = %s", (bill_no,))
    if not rows:
        return None
    found = _product_lines(rows[0][0])
    return found[0] if len(found) == 1 else None


def upgrade(ctx) -> None:
    t = TYPES[ctx.dialect]
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS production_item_progress ("
        " job_id INTEGER NOT NULL REFERENCES production_jobs (id) ON DELETE CASCADE,"
        " line_no INTEGER NOT NULL CHECK (line_no >= 0),"
        " stage SMALLINT NOT NULL CHECK (stage BETWEEN 1 AND 10),"
        " vendor_name VARCHAR(80),"
        " completed BOOLEAN NOT NULL DEFAULT FALSE,"
        " sent_to_vendor BOOLEAN NOT NULL DEFAULT FALSE,"
        " received BOOLEAN NOT NULL DEFAULT FALSE,"
        f" updated_at {t['ts']} NOT NULL,"
        " PRIMARY KEY (job_id, line_no, stage))"
    )
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS design_items ("
        " job_id INTEGER NOT NULL REFERENCES design_jobs (id) ON DELETE CASCADE,"
        " line_no INTEGER NOT NULL CHECK (line_no >= 0),"
        " designer_id INTEGER REFERENCES designers (id),"
        " status SMALLINT NOT NULL CHECK (status BETWEEN 1 AND 4),"
        " vendor_name VARCHAR(80),"
        f" updated_at {t['ts']} NOT NULL,"
        " PRIMARY KEY (job_id, line_no))"
    )
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS design_item_history ("
        f" id {t['pk']} NOT NULL,"
        " job_id INTEGER NOT NULL,"
        " line_no INTEGER NOT NULL,"
        " old_status SMALLINT,"
        " new_status SMALLINT NOT NULL,"
        f" changed_at {t['ts']} NOT NULL,"
        " PRIMARY KEY (id))"
    )
    ctx.execute("CREATE INDEX IF NOT EXISTS ix_design_item_history_job ON design_item_history (job_id, line_no, id)")

    have = ctx.tables()
    if "production_jobs" in have and "production_stage_progress" in have:
        for job_id, series, bill_no in ctx.execute("SELECT id, series, bill_no FROM production_jobs"):
            line_no = _single_product(ctx, have, series, bill_no)
            if line_no is None:
                continue
            ctx.execute(
                "INSERT INTO production_item_progress"
                " (job_id, line_no, stage, vendor_name, completed, sent_to_vendor, received, updated_at)"
                " SELECT p.job_id, %s, p.stage, p.vendor_name, p.completed, p.sent_to_vendor, p.received, p.updated_at"
                " FROM production_stage_progress p WHERE p.job_id = %s AND NOT EXISTS"
                " (SELECT 1 FROM production_item_progress i WHERE i.job_id = p.job_id AND i.line_no = %s AND i.stage = p.stage)",
                (line_no, job_id, line_no),
            )
    if "design_jobs" in have:
        for job_id, series, bill_no, status, vendor, updated_at in ctx.execute(
            "SELECT id, series, bill_no, status, vendor_name, updated_at FROM design_jobs"
        ):
            line_no = _single_product(ctx, have, series, bill_no)
            if line_no is None or ctx.execute(
                "SELECT 1 FROM design_items WHERE job_id = %s AND line_no = %s", (job_id, line_no)
            ):
                continue
            ctx.execute(
                "INSERT INTO design_items (job_id, line_no, designer_id, status, vendor_name, updated_at)"
                " VALUES (%s, %s, NULL, %s, %s, %s)",
                (job_id, line_no, status, vendor, updated_at),
            )
