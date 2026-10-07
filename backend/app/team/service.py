"""Employees (the current workforce) and their attendance.

Attendance is one record per employee per working day, keyed by the day in IST. An employee
checks in (the record is made with the server's time) and later checks out. Until role-based
login exists, anyone with the staff passcode can check anyone in or out; an admin (admin
passcode) can set or correct the times, add a missed day or delete a record, and manage the
employee list. Removing an employee only marks them inactive, so past attendance stays.
"""
from calendar import monthrange
from datetime import date, datetime, time, timezone

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..designers.service import DesignerError as TeamError
from ..designers.service import utc_iso
from .models import EMAIL_MAX, IST, NAME_MAX, NOTE_MAX, PHONE_MAX, ROLES, TABLES, Attendance, Employee

PHONE_CHARS = set("0123456789+-() ")


def tables_ready(engine) -> bool:
    have = set(inspect(engine).get_table_names())
    return all(t in have for t in TABLES)


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def ist_day(moment: datetime) -> date:
    return _aware(moment).astimezone(IST).date()


def _aware(value: datetime) -> datetime:
    """SQLite hands back naive UTC; Postgres gives aware datetimes."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _invalid(message: str, field: str) -> TeamError:
    return TeamError("VALIDATION_ERROR", message, 422, {"field": field})


def _not_found(what: str, id_: int) -> TeamError:
    return TeamError("NOT_FOUND", f"{what} {id_} doesn't exist", 404)


# ---------- employees ----------

def employee_json(e: Employee) -> dict:
    return {
        "id": e.id,
        "name": e.name,
        "role": e.role,
        "phone": e.phone,
        "email": e.email,
        "joined_on": e.joined_on.isoformat() if e.joined_on else None,
        "active": e.active,
    }


def list_employees(session: Session, include_removed: bool = False) -> list[dict]:
    query = select(Employee).order_by(func.lower(Employee.name), Employee.id)
    if not include_removed:
        query = query.where(Employee.active.is_(True))
    return [employee_json(e) for e in session.scalars(query)]


def _clean(fields: dict) -> dict:
    """Squeezed, checked values for the fields present in `fields` (blank optional text = None)."""
    out: dict = {}
    if "name" in fields:
        name = " ".join((fields["name"] or "").split())
        if not name:
            raise _invalid("Enter a name", "name")
        if len(name) > NAME_MAX:
            raise _invalid(f"Names are at most {NAME_MAX} characters", "name")
        out["name"] = name
    if "role" in fields:
        if fields["role"] not in ROLES:
            raise _invalid(f"Role must be one of: {', '.join(ROLES.values())}", "role")
        out["role"] = fields["role"]
    if "phone" in fields:
        phone = " ".join((fields["phone"] or "").split()) or None
        if phone and (len(phone) > PHONE_MAX or not set(phone) <= PHONE_CHARS or sum(c.isdigit() for c in phone) < 6):
            raise _invalid("Enter a phone number (digits, spaces, + and -)", "phone")
        out["phone"] = phone
    if "email" in fields:
        email = (fields["email"] or "").strip() or None
        if email and (len(email) > EMAIL_MAX or " " in email or email.count("@") != 1 or "." not in email.split("@")[1]):
            raise _invalid("Enter an email address like name@example.com", "email")
        out["email"] = email
    if "joined_on" in fields:
        out["joined_on"] = fields["joined_on"]
    return out


def _check_name_free(session: Session, name: str, except_id: int | None = None) -> None:
    query = select(Employee).where(func.lower(Employee.name) == name.lower())
    if except_id is not None:
        query = query.where(Employee.id != except_id)
    taken = session.scalars(query).first()
    if taken is None:
        return
    if taken.active:
        raise TeamError("NAME_TAKEN", f"{taken.name} is already on the list", 409, {"field": "name"})
    raise TeamError(
        "NAME_TAKEN",
        f"{taken.name} was removed earlier: restore them from Removed employees",
        409,
        {"field": "name", "employee_id": taken.id},
    )


def _commit(session: Session, name: str) -> None:
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise TeamError("CONFLICT", f"{name} changed at the same moment - refresh and try again", 409) from None


def add_employee(session: Session, fields: dict) -> dict:
    data = _clean({"phone": None, "email": None, "joined_on": None, **fields})
    if "name" not in data or "role" not in data:
        raise _invalid("Enter a name and a role", "name" if "name" not in data else "role")
    _check_name_free(session, data["name"])
    moment = now_utc()
    employee = Employee(**data, active=True, created_at=moment, updated_at=moment)
    session.add(employee)
    _commit(session, data["name"])
    return employee_json(employee)


def _employee(session: Session, employee_id: int) -> Employee:
    employee = session.get(Employee, employee_id)
    if employee is None:
        raise _not_found("Employee", employee_id)
    return employee


def update_employee(session: Session, employee_id: int, fields: dict) -> dict:
    employee = _employee(session, employee_id)
    data = _clean(fields)
    if "name" in data:
        _check_name_free(session, data["name"], except_id=employee_id)
    for key, value in data.items():
        setattr(employee, key, value)
    employee.updated_at = now_utc()
    _commit(session, employee.name)
    return employee_json(employee)


def set_active(session: Session, employee_id: int, active: bool) -> dict:
    """Remove (False) or restore (True) an employee. Attendance history is kept either way."""
    employee = _employee(session, employee_id)
    if active:
        _check_name_free(session, employee.name, except_id=employee_id)
    employee.active = active
    employee.updated_at = now_utc()
    _commit(session, employee.name)
    return employee_json(employee)


# ---------- attendance ----------

def minutes_worked(record: Attendance) -> int | None:
    if record.check_out is None:
        return None
    return int((_aware(record.check_out) - _aware(record.check_in)).total_seconds() // 60)


def record_json(record: Attendance | None) -> dict | None:
    if record is None:
        return None
    return {
        "work_date": record.work_date.isoformat(),
        "check_in": utc_iso(record.check_in),
        "check_out": utc_iso(record.check_out),
        "minutes": minutes_worked(record),
        "note": record.note,
        "edited_by_admin": record.edited_by_admin,
    }


def _record(session: Session, employee_id: int, day: date) -> Attendance | None:
    return session.scalars(
        select(Attendance).where(Attendance.employee_id == employee_id, Attendance.work_date == day)
    ).first()


def day_register(session: Session, day: date, moment: datetime) -> dict:
    """Every current employee, plus anyone removed since who has a record that day."""
    records = {r.employee_id: r for r in session.scalars(select(Attendance).where(Attendance.work_date == day))}
    employees = session.scalars(
        select(Employee)
        .where(Employee.active.is_(True) | Employee.id.in_(list(records) or [-1]))
        .order_by(func.lower(Employee.name), Employee.id)
    ).all()
    rows = [{"employee": employee_json(e), "record": record_json(records.get(e.id))} for e in employees]
    present = sum(1 for r in rows if r["record"])
    return {
        "date": day.isoformat(),
        "today": ist_day(moment).isoformat(),
        "rows": rows,
        "counts": {
            "employees": len(rows),
            "present": present,
            "checked_in_now": sum(1 for r in rows if r["record"] and not r["record"]["check_out"]),
        },
    }


def check_in(session: Session, employee_id: int, moment: datetime) -> dict:
    employee = _employee(session, employee_id)
    if not employee.active:
        raise TeamError("EMPLOYEE_REMOVED", f"{employee.name} is no longer on the team", 409)
    day = ist_day(moment)
    existing = _record(session, employee_id, day)
    if existing is not None:
        raise TeamError(
            "ALREADY_CHECKED_IN",
            f"{employee.name} already checked in today",
            409,
            {"record": record_json(existing)},
        )
    record = Attendance(
        employee_id=employee_id,
        work_date=day,
        check_in=moment,
        check_out=None,
        edited_by_admin=False,
        created_at=moment,
        updated_at=moment,
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise TeamError("ALREADY_CHECKED_IN", f"{employee.name} already checked in today", 409) from None
    return {"employee": employee_json(employee), "record": record_json(record)}


def check_out(session: Session, employee_id: int, moment: datetime) -> dict:
    employee = _employee(session, employee_id)
    record = _record(session, employee_id, ist_day(moment))
    if record is None:
        raise TeamError("NOT_CHECKED_IN", f"{employee.name} hasn't checked in today", 409)
    if record.check_out is not None:
        raise TeamError(
            "ALREADY_CHECKED_OUT", f"{employee.name} already checked out today", 409, {"record": record_json(record)}
        )
    record.check_out = moment
    record.updated_at = moment
    session.commit()
    return {"employee": employee_json(employee), "record": record_json(record)}


def _at(day: date, hhmm: str, field: str) -> datetime:
    try:
        hours, minutes = (int(p) for p in hhmm.split(":"))
        local = datetime.combine(day, time(hours, minutes), IST)
    except (ValueError, TypeError):
        raise _invalid("Enter a time as HH:MM (24-hour)", field) from None
    return local.astimezone(timezone.utc)


def set_record(
    session: Session, employee_id: int, day: date, check_in_at: str, check_out_at: str | None, note: str | None,
    moment: datetime,
) -> dict:
    """An admin sets a day's times (IST, HH:MM), making the record if the day has none."""
    employee = _employee(session, employee_id)
    if day > ist_day(moment):
        raise _invalid("That day hasn't happened yet", "date")
    start = _at(day, check_in_at, "check_in")
    end = _at(day, check_out_at, "check_out") if check_out_at else None
    if end is not None and end <= start:
        raise _invalid("Check-out must be after check-in", "check_out")
    if start > moment or (end is not None and end > moment):
        raise _invalid("Times can't be in the future", "check_out" if start <= moment else "check_in")
    note = " ".join((note or "").split()) or None
    if note and len(note) > NOTE_MAX:
        raise _invalid(f"Notes are at most {NOTE_MAX} characters", "note")
    record = _record(session, employee_id, day)
    if record is None:
        record = Attendance(employee_id=employee_id, work_date=day, created_at=moment)
        session.add(record)
    record.check_in, record.check_out, record.note = start, end, note
    record.edited_by_admin = True
    record.updated_at = moment
    _commit(session, employee.name)
    return {"employee": employee_json(employee), "record": record_json(record)}


def delete_record(session: Session, employee_id: int, day: date) -> None:
    employee = _employee(session, employee_id)
    record = _record(session, employee_id, day)
    if record is None:
        raise TeamError("NOT_FOUND", f"{employee.name} has no attendance on {day.isoformat()}", 404)
    session.delete(record)
    session.commit()


def month_summary(session: Session, year: int, month: int, moment: datetime) -> dict:
    """Per employee: each day's times, days present, minutes worked and days left open
    (checked in, never checked out, on a day that is over)."""
    first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    today = ist_day(moment)
    records = session.scalars(
        select(Attendance).where(Attendance.work_date >= first, Attendance.work_date <= last)
    ).all()
    by_employee: dict[int, list[Attendance]] = {}
    for r in records:
        by_employee.setdefault(r.employee_id, []).append(r)
    employees = session.scalars(
        select(Employee)
        .where(Employee.active.is_(True) | Employee.id.in_(list(by_employee) or [-1]))
        .order_by(func.lower(Employee.name), Employee.id)
    ).all()
    rows = []
    for e in employees:
        days = sorted(by_employee.get(e.id, []), key=lambda r: r.work_date)
        worked = [m for m in (minutes_worked(r) for r in days) if m is not None]
        rows.append(
            {
                "employee": employee_json(e),
                "days_present": len(days),
                "minutes": sum(worked),
                "open_days": sum(1 for r in days if r.check_out is None and r.work_date < today),
                "days": {r.work_date.isoformat(): record_json(r) for r in days},
            }
        )
    return {
        "month": f"{year:04d}-{month:02d}",
        "first": first.isoformat(),
        "last": last.isoformat(),
        "today": today.isoformat(),
        "rows": rows,
    }
