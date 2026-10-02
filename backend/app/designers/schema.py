"""Whether the Designer Assignment tables exist, and the database clock.

Postgres gets its tables only from backend/migrations/ (scripts/migrate.py). SQLite (local
development and tests) builds them from the models and seeds Namit and Ajendra.
"""
from sqlalchemy import func, inspect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .models import SEED_DESIGNERS, DesignBase, Designer, RotationState

TABLES = ("designers", "rotation_state", "design_jobs", "job_status_history")


def prepare(engine: Engine) -> bool:
    """True when the tables are there (created and seeded first on SQLite)."""
    if engine.dialect.name == "sqlite":
        DesignBase.metadata.create_all(engine)
        with Session(engine) as s:
            if s.get(RotationState, 1) is None:
                s.add(RotationState(id=1, last_order=0, seq=0))
                if not s.scalar(select(func.count()).select_from(Designer)):
                    s.add_all(Designer(name=name, active=True, rotation_order=order) for name, order in SEED_DESIGNERS)
                s.commit()
        return True
    have = set(inspect(engine).get_table_names())
    return all(t in have for t in TABLES)


def db_now(session: Session):
    """The database server's current time. clock_timestamp() on Postgres, not now(): now() is
    when the transaction began, which could put a job that waited for the rotation lock
    before the job it waited for."""
    if session.get_bind().dialect.name == "postgresql":
        return func.clock_timestamp()
    return func.strftime("%Y-%m-%d %H:%M:%f", "now")  # SQLite: UTC, to the millisecond
