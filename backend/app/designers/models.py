"""Designer Assignment tables.

On Postgres the tables come from the SQL files in backend/migrations/ (never create_all), so
these classes must match them; tests/test_designer_migrations.py checks that. Local SQLite
and the tests build the same tables from these classes (schema.prepare).
"""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, SmallInteger, String,
    UniqueConstraint, func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# The six progress stages, in order. The UI shows these labels.
STATUSES: dict[int, str] = {
    1: "Work assigned",
    2: "Sent to customer for approval",
    3: "Approval received",
    4: "Sent for sampling",
    5: "Final design",
    6: "Final vendor",
}
# Stages that still need the designer. Only stage 6 (the last) counts as done.
# The frontend has the same constant (src/lib/designers.ts); a test keeps them equal.
PENDING_STATUSES: frozenset[int] = frozenset({1, 2, 3, 4, 5})

# Invoices that become design jobs. Quotations don't.
JOB_SERIES = ("non_gst", "gst")

NAME_MAX = 40
VENDOR_MAX = 80
SUMMARY_MAX = 300


class DesignBase(DeclarativeBase):
    """Separate from the invoice tables' Base (built only by migrations 0003+, never create_all)."""


class Designer(DesignBase):
    __tablename__ = "designers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX), unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    rotation_order: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class RotationState(DesignBase):
    """One row (id 1): who got the last job. Locked for every assignment."""

    __tablename__ = "rotation_state"
    __table_args__ = (CheckConstraint("id = 1"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class DesignJob(DesignBase):
    __tablename__ = "design_jobs"
    __table_args__ = (
        UniqueConstraint("series", "bill_no", name="design_jobs_invoice_unique"),
        CheckConstraint("series IN ('non_gst', 'gst')"),
        CheckConstraint("status BETWEEN 1 AND 6"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series: Mapped[str] = mapped_column(String(16), nullable=False)
    bill_no: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_name: Mapped[str] = mapped_column(String(60), nullable=False)
    invoice_total: Mapped[Decimal] = mapped_column(Numeric(12, 2, asdecimal=True), nullable=False)
    items_summary: Mapped[str] = mapped_column(String(SUMMARY_MAX), nullable=False)
    designer_id: Mapped[int | None] = mapped_column(ForeignKey("designers.id"), nullable=True)
    assignment_seq: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    vendor_name: Mapped[str | None] = mapped_column(String(VENDOR_MAX), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobStatusHistory(DesignBase):
    __tablename__ = "job_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("design_jobs.id", ondelete="CASCADE"), nullable=False)
    old_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    new_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


SEED_DESIGNERS = (("Namit", 1), ("Ajendra", 2))


class DesignItemBase(DeclarativeBase):
    """Per-product design tables, built by migration 0007 on every database (not create_all),
    so they are kept out of DesignBase."""


class DesignItem(DesignItemBase):
    """One product's design: a product is one non-add-on line of the job's invoice (line_no =
    its position in the stored lines). designer_id None = the order's designer. No row = the
    order's designer, status 1, no vendor."""

    __tablename__ = "design_items"

    job_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    designer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    vendor_name: Mapped[str | None] = mapped_column(String(VENDOR_MAX), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DesignItemHistory(DesignItemBase):
    __tablename__ = "design_item_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, nullable=False)
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    old_status: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    new_status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


ITEM_TABLES = ("design_items", "design_item_history")
