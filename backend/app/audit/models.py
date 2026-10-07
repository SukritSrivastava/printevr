"""The activity log table. It comes from backend/migrations/0010_audit_log.py on every
database (never create_all); this class must match it (tests/test_audit.py compares them)."""
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, SmallInteger, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# What the Logs tab filters by (category -> label).
CATEGORIES: dict[str, str] = {
    "invoices": "Invoices & payments",
    "design": "Designer Assignment",
    "production": "Production",
    "employees": "Employees",
    "attendance": "Attendance",
    "access": "Sign-ins",
    "other": "Other",
}


class AuditBase(DeclarativeBase):
    """Separate from the other tables' bases: a database without this table yet still works
    (changes just aren't logged until it's migrated)."""


class AuditEntry(AuditBase):
    __tablename__ = "audit_log"

    # BIGSERIAL on Postgres, INTEGER (rowid) on SQLite.
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    actor_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(String(300), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    path: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)


TABLES = ("audit_log",)
