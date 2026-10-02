-- Designer Assignment: designers, the rotation pointer, design jobs and their status history.
-- Postgres only. Apply with `python backend/scripts/migrate.py` (see README).
-- backend/app/designers/models.py mirrors these tables for local SQLite; keep them in step
-- (tests/test_designer_migrations.py checks it against Postgres).

CREATE TABLE designers (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(40)  NOT NULL UNIQUE,
    active          BOOLEAN      NOT NULL DEFAULT TRUE,
    -- Position in the rotation, lowest first. New designers go to the end.
    rotation_order  INTEGER      NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp()
);

-- Exactly one row (id = 1). Every assignment locks it with SELECT ... FOR UPDATE, so two
-- invoices printed at the same moment take turns and the rotation never skips or repeats.
CREATE TABLE rotation_state (
    id          INTEGER  PRIMARY KEY CHECK (id = 1),
    -- rotation_order of the designer who got the last job (0 = nobody yet).
    last_order  INTEGER  NOT NULL DEFAULT 0,
    -- Number of jobs assigned so far; each assigned job stores its value.
    seq         BIGINT   NOT NULL DEFAULT 0
);
INSERT INTO rotation_state (id, last_order, seq) VALUES (1, 0, 0);

-- One job per invoice. series + bill_no identify the invoice (each series numbers on its own).
CREATE TABLE design_jobs (
    id              SERIAL PRIMARY KEY,
    series          VARCHAR(16)    NOT NULL CHECK (series IN ('non_gst', 'gst')),
    bill_no         INTEGER        NOT NULL,
    customer_name   VARCHAR(60)    NOT NULL,
    invoice_total   NUMERIC(12, 2) NOT NULL,
    items_summary   VARCHAR(300)   NOT NULL,
    -- Null only when no designer was active at the time.
    designer_id     INTEGER        REFERENCES designers (id),
    assignment_seq  BIGINT         UNIQUE,
    assigned_at     TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
    -- 1 Work assigned, 2 Sent to customer for approval, 3 Approval received, 4 Sent for sampling
    status          SMALLINT       NOT NULL DEFAULT 1 CHECK (status BETWEEN 1 AND 4),
    vendor_name     VARCHAR(80),
    updated_at      TIMESTAMPTZ    NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT design_jobs_invoice_unique UNIQUE (series, bill_no)
);
CREATE INDEX design_jobs_designer_status ON design_jobs (designer_id, status);
CREATE INDEX design_jobs_assigned_at ON design_jobs (assigned_at DESC);

CREATE TABLE job_status_history (
    id          SERIAL PRIMARY KEY,
    job_id      INTEGER      NOT NULL REFERENCES design_jobs (id) ON DELETE CASCADE,
    -- Null on the row written when the job is created.
    old_status  SMALLINT     CHECK (old_status BETWEEN 1 AND 4),
    new_status  SMALLINT     NOT NULL CHECK (new_status BETWEEN 1 AND 4),
    changed_at  TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX job_status_history_job ON job_status_history (job_id, id);
