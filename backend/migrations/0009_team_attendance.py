"""Team tab tables, Postgres and SQLite: the employee list (the current workforce) and one
attendance record per employee per working day (IST), with the check-in and check-out times.

Removing an employee only clears `active`, so their attendance history stays. `role` is
checked by the API against app/team/models.py ROLES (no CHECK here, so a new role needs no
migration); role-based login will hang user accounts off employees.id.
Frozen once applied: add a new migration instead of editing this one.
"""

TYPES = {
    "postgresql": {"pk": "SERIAL", "ts": "TIMESTAMP WITH TIME ZONE", "true": "TRUE"},
    "sqlite": {"pk": "INTEGER", "ts": "DATETIME", "true": "1"},
}


def upgrade(ctx) -> None:
    t = TYPES[ctx.dialect]
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS employees ("
        f" id {t['pk']} NOT NULL,"
        " name VARCHAR(80) NOT NULL,"
        " role VARCHAR(20) NOT NULL,"
        " phone VARCHAR(20),"
        " email VARCHAR(120),"
        " joined_on DATE,"
        f" active BOOLEAN NOT NULL DEFAULT {t['true']},"
        f" created_at {t['ts']} NOT NULL,"
        f" updated_at {t['ts']} NOT NULL,"
        " PRIMARY KEY (id))"
    )
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS attendance ("
        f" id {t['pk']} NOT NULL,"
        " employee_id INTEGER NOT NULL REFERENCES employees (id),"
        " work_date DATE NOT NULL,"
        f" check_in {t['ts']} NOT NULL,"
        f" check_out {t['ts']},"
        " note VARCHAR(200),"
        " edited_by_admin BOOLEAN NOT NULL DEFAULT FALSE,"
        f" created_at {t['ts']} NOT NULL,"
        f" updated_at {t['ts']} NOT NULL,"
        " PRIMARY KEY (id))"
    )
    ctx.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_attendance_employee_day ON attendance (employee_id, work_date)")
    ctx.execute("CREATE INDEX IF NOT EXISTS ix_attendance_work_date ON attendance (work_date)")
