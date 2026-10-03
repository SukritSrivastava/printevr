"""Production tab tables, Postgres and SQLite: production employees (Vivek to start with) and
production jobs. A job points at an issued invoice (series + bill_no) and holds only what the
invoice doesn't: its stage (1-10, app/production/models.py STAGES) and assigned employee.
Frozen once applied: add a new migration instead of editing this one.
"""

TYPES = {
    "postgresql": {"pk": "SERIAL", "ts": "TIMESTAMP WITH TIME ZONE"},
    "sqlite": {"pk": "INTEGER", "ts": "DATETIME"},
}


def upgrade(ctx) -> None:
    t = TYPES[ctx.dialect]
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS production_employees ("
        f" id {t['pk']} NOT NULL,"
        " name VARCHAR(40) NOT NULL,"
        f" created_at {t['ts']} NOT NULL,"
        " PRIMARY KEY (id))"
    )
    ctx.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_production_employees_name ON production_employees (name)")
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS production_jobs ("
        f" id {t['pk']} NOT NULL,"
        " series VARCHAR(16) NOT NULL CHECK (series IN ('non_gst', 'gst')),"
        " bill_no INTEGER NOT NULL,"
        " stage SMALLINT NOT NULL CHECK (stage BETWEEN 1 AND 10),"
        " employee_id INTEGER REFERENCES production_employees (id),"
        f" created_at {t['ts']} NOT NULL,"
        f" updated_at {t['ts']} NOT NULL,"
        " PRIMARY KEY (id))"
    )
    ctx.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_production_jobs_invoice ON production_jobs (series, bill_no)")
    ctx.execute(
        "INSERT INTO production_employees (name, created_at) SELECT 'Vivek', CURRENT_TIMESTAMP"
        " WHERE NOT EXISTS (SELECT 1 FROM production_employees WHERE lower(name) = 'vivek')"
    )
