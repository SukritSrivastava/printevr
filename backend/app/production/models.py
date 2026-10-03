"""Production tab tables. They come from backend/migrations/0005_production.py,
0006_production_stages.py and 0007_product_tracking.py on every database (never create_all); these classes must match them.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# The production stages, in order. The UI shows these labels (frontend src/lib/production.ts).
STAGES: dict[int, str] = {
    1: "Sampling",
    2: "Paper / Material",
    3: "Printing",
    4: "Lamination",
    5: "UV / Foiling / Special Finishing",
    6: "Cutting / Making / Pasting",
    7: "Quality Check",
    8: "Packaging",
    9: "Delivery / Dispatch",
    10: "Customer Feedback",
}

# Invoices that can go into production. Quotations can't.
JOB_SERIES = ("non_gst", "gst")

NAME_MAX = 40
VENDOR_MAX = 80


class ProductionBase(DeclarativeBase):
    """Separate from the invoice tables' Base, so a database without these tables yet still
    serves invoices (the Production tab answers PRODUCTION_NOT_SET_UP until it's migrated)."""


class ProductionEmployee(ProductionBase):
    __tablename__ = "production_employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProductionJob(ProductionBase):
    __tablename__ = "production_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    series: Mapped[str] = mapped_column(String(16), nullable=False)
    bill_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # The earliest current stage among the job's products (10 when every product is complete).
    stage: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("production_employees.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class StageProgress(ProductionBase):
    """One job's record for one stage, for the whole order: what was tracked before products
    had their own stages (0007). Read only now; shown for orders with several products."""

    __tablename__ = "production_stage_progress"

    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id", ondelete="CASCADE"), primary_key=True)
    stage: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    vendor_name: Mapped[str | None] = mapped_column(String(VENDOR_MAX), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_to_vendor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ItemProgress(ProductionBase):
    """One product's record for one stage. A product is one non-add-on line of the job's
    invoice (line_no = its position in the stored lines). No row = nothing recorded yet."""

    __tablename__ = "production_item_progress"

    job_id: Mapped[int] = mapped_column(ForeignKey("production_jobs.id", ondelete="CASCADE"), primary_key=True)
    line_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    stage: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    vendor_name: Mapped[str | None] = mapped_column(String(VENDOR_MAX), nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sent_to_vendor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    received: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


TABLES = ("production_employees", "production_jobs", "production_stage_progress", "production_item_progress")
