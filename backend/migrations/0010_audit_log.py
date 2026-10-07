"""Activity log, Postgres and SQLite: one row for every change made through the website
(invoices, payments, design and production jobs, employees, attendance, sign-ins), written by
app/audit after the change succeeded. Only the admin can read it (Logs tab).

`actor_role` is who the request was signed in as (staff or admin passcode); `actor_name` is
empty until role-based login names each person. Rows are never updated.
Frozen once applied: add a new migration instead of editing this one.
"""

TYPES = {
    "postgresql": {"pk": "BIGSERIAL", "ts": "TIMESTAMP WITH TIME ZONE"},
    "sqlite": {"pk": "INTEGER", "ts": "DATETIME"},
}


def upgrade(ctx) -> None:
    t = TYPES[ctx.dialect]
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS audit_log ("
        f" id {t['pk']} NOT NULL,"
        f" at {t['ts']} NOT NULL,"
        " actor_role VARCHAR(20) NOT NULL,"
        " actor_name VARCHAR(80),"
        " category VARCHAR(20) NOT NULL,"
        " summary VARCHAR(300) NOT NULL,"
        " method VARCHAR(8) NOT NULL,"
        " path VARCHAR(200) NOT NULL,"
        " status SMALLINT NOT NULL,"
        " details TEXT,"
        " ip VARCHAR(64),"
        " user_agent VARCHAR(200),"
        " PRIMARY KEY (id))"
    )
    ctx.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_at ON audit_log (at)")
    ctx.execute("CREATE INDEX IF NOT EXISTS ix_audit_log_category ON audit_log (category)")
