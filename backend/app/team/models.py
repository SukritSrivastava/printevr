"""Team tab tables: employees and their attendance. They come from
backend/migrations/0009_team_attendance.py on every database (never create_all); these classes
must match it (tests/test_team.py compares them).
"""
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# What each employee does. Role-based login will use the same keys, so keep them stable;
# the labels are what the UI shows (sent by GET /api/team/settings).
ROLES: dict[str, str] = {
    "admin": "Admin",
    "sales": "Sales",
    "designer": "Designer",
    "production": "Production",
    "accounts": "Accounts",
    "staff": "Staff",
}

# Attendance days and times are Indian Standard Time (no daylight saving, so a fixed offset).
IST = timezone(timedelta(hours=5, minutes=30), "IST")

NAME_MAX = 80
PHONE_MAX = 20
EMAIL_MAX = 120
NOTE_MAX = 200


class TeamBase(DeclarativeBase):
    """Separate from the invoice tables' Base, so a database without these tables yet still
    serves invoices (the Team tab answers TEAM_NOT_SET_UP until it's migrated)."""


class Employee(TeamBase):
    __tablename__ = "employees"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(NAME_MAX), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(PHONE_MAX), nullable=True)
    email: Mapped[str | None] = mapped_column(String(EMAIL_MAX), nullable=True)
    joined_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    # False = removed from the workforce; the attendance history stays.
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Attendance(TeamBase):
    """One employee's working day: checked in, and later checked out (None = still in)."""

    __tablename__ = "attendance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    check_in: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    check_out: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str | None] = mapped_column(String(NOTE_MAX), nullable=True)
    # True once an admin has set or corrected the times by hand.
    edited_by_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


TABLES = ("employees", "attendance")
