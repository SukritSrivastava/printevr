"""Writing and reading the activity log (table audit_log, migration 0010).

`record` runs after a change succeeded and never fails the request: a database problem is
logged and the entry is skipped. Without DATABASE_URL, or before 0010 has run, nothing is
recorded. Times are stored in UTC and shown in IST by the Logs tab.
"""
import json
import logging
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, inspect, or_, select
from sqlalchemy.orm import Session

from ..team.models import IST, Employee
from .describe import describe, details_json
from .models import CATEGORIES, TABLES, AuditEntry

log = logging.getLogger("printevr.audit")

PAGE_MAX = 200


def tables_ready(engine) -> bool:
    have = set(inspect(engine).get_table_names())
    return all(t in have for t in TABLES)


def _employee_name(session: Session, details: dict) -> str | None:
    employee_id = details.get("employee_id")
    if not isinstance(employee_id, int):
        return None
    try:
        return session.scalar(select(Employee.name).where(Employee.id == employee_id))
    except Exception:  # the team tables may not exist yet
        session.rollback()
        return None


def record(
    session: Session,
    *,
    method: str,
    path: str,
    query: dict,
    body,
    status: int,
    headers: dict,
    actor_role: str,
    ip: str | None,
    user_agent: str | None,
    at: datetime | None = None,
) -> AuditEntry:
    category, summary, details = describe(method, path, query, body, headers)
    if "{employee}" in summary:
        name = _employee_name(session, details)
        summary = summary.replace("{employee}", name or f"employee #{details.get('employee_id', '?')}")
        if name:
            details = {**details, "employee": name}
    entry = AuditEntry(
        at=at or datetime.now(timezone.utc),
        actor_role=actor_role,
        actor_name=None,
        category=category,
        summary=summary[:300],
        method=method,
        path=path[:200],
        status=status,
        details=details_json(details) if details else None,
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:200] or None,
    )
    session.add(entry)
    session.commit()
    return entry


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def entry_json(e: AuditEntry) -> dict:
    try:
        details = json.loads(e.details) if e.details else {}
    except ValueError:
        details = {"text": e.details}
    return {
        "id": e.id,
        "at": _iso(e.at),
        "actor_role": e.actor_role,
        "actor_name": e.actor_name,
        "category": e.category,
        "summary": e.summary,
        "method": e.method,
        "path": e.path,
        "status": e.status,
        "details": details,
        "ip": e.ip,
        "user_agent": e.user_agent,
    }


def list_entries(
    session: Session,
    *,
    day_from: date | None = None,
    day_to: date | None = None,
    category: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Newest first. Days are IST and inclusive."""
    query = select(AuditEntry)
    if day_from:
        query = query.where(AuditEntry.at >= datetime.combine(day_from, time(0), IST).astimezone(timezone.utc))
    if day_to:
        query = query.where(AuditEntry.at < datetime.combine(day_to + timedelta(days=1), time(0), IST).astimezone(timezone.utc))
    if category:
        query = query.where(AuditEntry.category == category)
    if search and search.strip():
        like = f"%{search.strip().lower()}%"
        query = query.where(
            or_(func.lower(AuditEntry.summary).like(like), func.lower(func.coalesce(AuditEntry.details, "")).like(like))
        )
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(AuditEntry.at.desc(), AuditEntry.id.desc()).limit(min(limit, PAGE_MAX)).offset(offset))
    return {
        "entries": [entry_json(e) for e in rows],
        "total": total,
        "limit": min(limit, PAGE_MAX),
        "offset": offset,
        "categories": [{"value": k, "label": v} for k, v in CATEGORIES.items()],
    }
