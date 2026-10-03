"""Login rate-limit counters shared by every server instance (app/ratelimit.py), Postgres and
SQLite. One row per (limit, hashed client address, minute); rows older than the previous
minute are deleted as the limiter goes. Holds no invoice data. Frozen once applied.
"""


def upgrade(ctx) -> None:
    ctx.execute(
        "CREATE TABLE IF NOT EXISTS rate_limit_counters ("
        " scope VARCHAR(32) NOT NULL,"
        " client_key VARCHAR(64) NOT NULL,"
        " window_start BIGINT NOT NULL,"
        " hits INTEGER NOT NULL,"
        " PRIMARY KEY (scope, client_key, window_start))"
    )
    ctx.execute("CREATE INDEX IF NOT EXISTS ix_rate_limit_counters_window ON rate_limit_counters (window_start)")
