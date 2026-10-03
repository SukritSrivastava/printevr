"""Per-stage production progress, Postgres and SQLite: one row per (job, stage) with that
stage's vendor, its Completed tick, and whether the work was sent to the vendor and picked up.
A missing row means nothing recorded yet for that stage.

Existing jobs only had a current stage (production_jobs.stage, chosen from a dropdown). A job
at stage N gets stages 1..N-1 marked complete, which is what that dropdown said; stage N and
later stay open, and nothing is recorded as sent or picked up. production_jobs.stage stays and
now holds the derived current stage (the first incomplete one; 10 when all are complete).
Frozen once applied: add a new migration instead of editing this one.
"""

TYPES = {
    "postgresql": {"ts": "TIMESTAMP WITH TIME ZONE"},
    "sqlite": {"ts": "DATETIME"},
}

STAGE_COUNT = 10


def upgrade(ctx) -> None:
    t = TYPES[ctx.dialect]
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS production_stage_progress ("
        " job_id INTEGER NOT NULL REFERENCES production_jobs (id) ON DELETE CASCADE,"
        f" stage SMALLINT NOT NULL CHECK (stage BETWEEN 1 AND {STAGE_COUNT}),"
        " vendor_name VARCHAR(80),"
        " completed BOOLEAN NOT NULL DEFAULT FALSE,"
        " sent_to_vendor BOOLEAN NOT NULL DEFAULT FALSE,"
        " received BOOLEAN NOT NULL DEFAULT FALSE,"
        f" updated_at {t['ts']} NOT NULL,"
        " PRIMARY KEY (job_id, stage))"
    )
    for stage in range(1, STAGE_COUNT):
        ctx.execute(
            "INSERT INTO production_stage_progress"
            " (job_id, stage, vendor_name, completed, sent_to_vendor, received, updated_at)"
            " SELECT j.id, %s, NULL, TRUE, FALSE, FALSE, j.updated_at FROM production_jobs j"
            " WHERE j.stage > %s AND NOT EXISTS"
            " (SELECT 1 FROM production_stage_progress p WHERE p.job_id = j.id AND p.stage = %s)",
            (stage, stage, stage),
        )
