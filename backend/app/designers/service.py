"""Designer rotation, design jobs and the workload view.

Assignment (ensure_job) runs inside the transaction that saves the invoice:
  1. a job for this invoice already exists -> return it, the rotation doesn't move;
  2. lock rotation_state (SELECT ... FOR UPDATE), pick the next active designer after the one
     who got the last job, wrapping to the first; inactive designers are skipped;
  3. insert the job and its first history row, move the pointer.
Concurrent invoices wait on that lock in turn, so the rotation never skips or repeats. If the
invoice is rolled back, the rotation move goes with it.
"""
import logging
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import case, delete, func, inspect, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..products import products as invoice_products
from .models import (
    ITEM_TABLES, JOB_SERIES, NAME_MAX, PENDING_STATUSES, STATUSES, SUMMARY_MAX, VENDOR_MAX, Designer, DesignItem,
    DesignItemHistory, DesignJob, JobStatusHistory, RotationState,
)
from .schema import db_now

log = logging.getLogger("printevr.designers")


class DesignerError(Exception):
    def __init__(self, code: str, message: str, http_status: int, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


def _not_found(what: str, id_: int) -> DesignerError:
    return DesignerError("NOT_FOUND", f"{what} {id_} doesn't exist", 404)


def utc_iso(value: datetime | None) -> str | None:
    """SQLite hands back naive UTC; Postgres gives aware datetimes. Both go out as UTC ISO."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


# ---------- rotation ----------

def _pick(designers: list[Designer], last_order: int) -> Designer | None:
    """The first active designer after last_order, wrapping round; None if nobody is active."""
    active = sorted((d for d in designers if d.active), key=lambda d: d.rotation_order)
    if not active:
        return None
    return next((d for d in active if d.rotation_order > last_order), active[0])


def peek_next(session: Session) -> Designer | None:
    """Who the next job goes to, without assigning anything."""
    state = session.get(RotationState, 1)
    return _pick(list(session.scalars(select(Designer))), state.last_order if state else 0)


def find_job(session: Session, series: str, bill_no: int) -> DesignJob | None:
    return session.scalar(select(DesignJob).where(DesignJob.series == series, DesignJob.bill_no == bill_no))


def summarize_items(lines: list) -> str:
    """'Rigid box ×350; Mailer bag ×1000; +2 more', within SUMMARY_MAX. Add-on rows are left out."""
    parts = [f"{line.title} ×{Decimal(line.quantity).normalize():f}" for line in lines if line.source not in ("addon", "customisation")]
    text = ""
    for i, part in enumerate(parts):
        more = f"; +{len(parts) - i} more"
        candidate = part if not text else f"{text}; {part}"
        if len(candidate) > SUMMARY_MAX or (i < len(parts) - 1 and len(candidate) + len(more) > SUMMARY_MAX):
            return (text + more) if text else part[: SUMMARY_MAX - 1] + "…"
        text = candidate
    return text


def ensure_job(
    session: Session, series: str, bill_no: int, customer_name: str, invoice_total: Decimal, items_summary: str
) -> DesignJob:
    """The job for this invoice, creating and assigning it if there is none. Doesn't commit."""
    if series not in JOB_SERIES:
        raise ValueError(f"{series} documents don't become design jobs")
    existing = find_job(session, series, bill_no)
    if existing is not None:
        return existing
    state = session.scalar(select(RotationState).where(RotationState.id == 1).with_for_update())
    if state is None:
        raise RuntimeError("rotation_state has no row: run the migrations")
    # Checked again under the lock: another request may have made this job while we waited.
    existing = find_job(session, series, bill_no)
    if existing is not None:
        return existing
    designer = _pick(list(session.scalars(select(Designer))), state.last_order)
    now = db_now(session)
    job = DesignJob(
        series=series,
        bill_no=bill_no,
        customer_name=customer_name[:60],
        invoice_total=invoice_total,
        items_summary=items_summary[:SUMMARY_MAX],
        designer_id=designer.id if designer else None,
        assignment_seq=state.seq + 1 if designer else None,
        assigned_at=now,
        status=1,
        updated_at=now,
    )
    session.add(job)
    if designer is not None:
        state.last_order = designer.rotation_order
        state.seq += 1
    session.flush()
    session.add(JobStatusHistory(job_id=job.id, old_status=None, new_status=1, changed_at=db_now(session)))
    session.flush()
    session.refresh(job)
    log.info("job %s for %s %s -> %s", job.id, series, bill_no, designer.name if designer else "unassigned")
    return job


def delete_jobs_for_invoice(session: Session, series: str, bill_no: int) -> None:
    """A deleted invoice leaves nothing behind. The rotation doesn't move back."""
    job = find_job(session, series, bill_no)
    if job is not None:
        session.execute(delete(JobStatusHistory).where(JobStatusHistory.job_id == job.id))
        if items_ready(session):
            session.execute(delete(DesignItemHistory).where(DesignItemHistory.job_id == job.id))
            session.execute(delete(DesignItem).where(DesignItem.job_id == job.id))
        session.delete(job)


# ---------- designers ----------

def designer_json(d: Designer) -> dict:
    return {"id": d.id, "name": d.name, "active": d.active, "rotation_order": d.rotation_order}


def _clean_name(name: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise DesignerError("VALIDATION_ERROR", "Enter a name", 422, {"field": "name"})
    if len(name) > NAME_MAX:
        raise DesignerError("VALIDATION_ERROR", f"Names are at most {NAME_MAX} characters", 422, {"field": "name"})
    return name


def _name_taken(session: Session, name: str, except_id: int | None = None) -> bool:
    query = select(Designer.id).where(func.lower(Designer.name) == name.lower())
    if except_id is not None:
        query = query.where(Designer.id != except_id)
    return session.scalar(query) is not None


def list_designers(session: Session) -> list[dict]:
    return [designer_json(d) for d in session.scalars(select(Designer).order_by(Designer.rotation_order))]


def add_designer(session: Session, name: str) -> dict:
    name = _clean_name(name)
    if _name_taken(session, name):
        raise DesignerError("NAME_TAKEN", f"There is already a designer called {name}", 409)
    last = session.scalar(select(func.max(Designer.rotation_order))) or 0
    designer = Designer(name=name, active=True, rotation_order=last + 1)
    session.add(designer)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DesignerError("NAME_TAKEN", "That designer was just added - refresh and try again", 409) from None
    return designer_json(designer)


def update_designer(session: Session, designer_id: int, name: str | None, active: bool | None) -> dict:
    designer = session.get(Designer, designer_id)
    if designer is None:
        raise _not_found("Designer", designer_id)
    if name is not None:
        name = _clean_name(name)
        if _name_taken(session, name, except_id=designer_id):
            raise DesignerError("NAME_TAKEN", f"There is already a designer called {name}", 409)
        designer.name = name
    if active is not None:
        designer.active = active
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise DesignerError("NAME_TAKEN", "That name was just taken - refresh and try again", 409) from None
    return designer_json(designer)


# ---------- jobs ----------

def designer_name(session: Session, designer_id: int | None) -> str | None:
    d = session.get(Designer, designer_id) if designer_id is not None else None
    return d.name if d else None


def _names(session: Session) -> dict[int, str]:
    return {d.id: d.name for d in session.scalars(select(Designer))}


def job_json(job: DesignJob, names: dict[int, str]) -> dict:
    return {
        "id": job.id,
        "series": job.series,
        "bill_no": job.bill_no,
        "customer_name": job.customer_name,
        "invoice_total": f"{job.invoice_total:.2f}",
        "items_summary": job.items_summary,
        "designer_id": job.designer_id,
        "designer_name": names.get(job.designer_id) if job.designer_id is not None else None,
        "assigned_at": utc_iso(job.assigned_at),
        "status": job.status,
        "status_label": STATUSES[job.status],
        "pending": job.status in PENDING_STATUSES,
        "vendor_name": job.vendor_name,
        "updated_at": utc_iso(job.updated_at),
    }


def list_jobs(
    session: Session, designer_id: int | None, status: int | None, pending: bool, q: str | None, limit: int
) -> dict:
    query = select(DesignJob)
    if designer_id is not None:
        query = query.where(DesignJob.designer_id == designer_id)
    if status is not None:
        query = query.where(DesignJob.status == status)
    if pending:
        query = query.where(DesignJob.status.in_(sorted(PENDING_STATUSES)))
    if q and q.strip():
        term = q.strip()
        conds = [func.lower(DesignJob.customer_name).contains(term.lower(), autoescape=True)]
        digits = term.lstrip("#")
        if digits.isdigit():
            conds.append(DesignJob.bill_no == int(digits))
        query = query.where(or_(*conds))
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    jobs = list(session.scalars(query.order_by(DesignJob.assigned_at.desc(), DesignJob.id.desc()).limit(limit)))
    names = _names(session)
    out = [job_json(j, names) for j in jobs]
    attach_products(session, jobs, out, names)
    return {"jobs": out, "total": total}


def clean_vendor(value: str | None) -> str | None:
    value = " ".join((value or "").split())
    if len(value) > VENDOR_MAX:
        raise DesignerError(
            "VALIDATION_ERROR", f"Vendor names are at most {VENDOR_MAX} characters", 422, {"field": "vendor_name"}
        )
    return value or None


def update_job(session: Session, job_id: int, changes: dict) -> dict:
    """changes may hold `status` (1-6) and/or `vendor_name` (None or blank clears it)."""
    job = session.get(DesignJob, job_id)
    if job is None:
        raise _not_found("Job", job_id)
    changed = False
    if "status" in changes and changes["status"] != job.status:
        new = changes["status"]
        if new not in STATUSES:
            raise DesignerError("VALIDATION_ERROR", "Status must be 1 to 6", 422, {"field": "status"})
        session.add(JobStatusHistory(job_id=job.id, old_status=job.status, new_status=new, changed_at=db_now(session)))
        job.status = new
        changed = True
    if "vendor_name" in changes:
        vendor = clean_vendor(changes["vendor_name"])
        if vendor != job.vendor_name:
            job.vendor_name = vendor
            changed = True
    if changed:
        job.updated_at = db_now(session)
        session.commit()
        session.refresh(job)
    return job_json(job, _names(session))


def history(session: Session, job_id: int) -> dict:
    job = session.get(DesignJob, job_id)
    if job is None:
        raise _not_found("Job", job_id)
    rows = session.scalars(
        select(JobStatusHistory).where(JobStatusHistory.job_id == job_id).order_by(JobStatusHistory.id)
    )
    names = _names(session)
    out = job_json(job, names)
    attach_products(session, [job], [out], names)
    titles = {p["line_no"]: p["title"] for p in out["products"]}
    product_history = []
    if items_ready(session):
        product_history = [
            {
                "line_no": h.line_no,
                "title": titles.get(h.line_no, f"Product {h.line_no + 1}"),
                "old_status": h.old_status,
                "new_status": h.new_status,
                "new_label": STATUSES[h.new_status],
                "changed_at": utc_iso(h.changed_at),
            }
            for h in session.scalars(
                select(DesignItemHistory).where(DesignItemHistory.job_id == job_id).order_by(DesignItemHistory.id)
            )
        ]
    return {
        "product_history": product_history,
        "job": out,
        "history": [
            {
                "old_status": h.old_status,
                "new_status": h.new_status,
                "new_label": STATUSES[h.new_status],
                "changed_at": utc_iso(h.changed_at),
            }
            for h in rows
        ],
    }


def vendors(session: Session, q: str | None, limit: int = 20) -> list[str]:
    """Vendor names already used, most used first."""
    query = select(DesignJob.vendor_name, func.count()).where(DesignJob.vendor_name.is_not(None))
    if q and q.strip():
        query = query.where(func.lower(DesignJob.vendor_name).contains(q.strip().lower(), autoescape=True))
    query = query.group_by(DesignJob.vendor_name).order_by(func.count().desc(), DesignJob.vendor_name).limit(limit)
    return [name for name, _ in session.execute(query)]


def workload(session: Session, jobs_per_designer: int = 50) -> dict:
    """One entry per designer: pending count, count per stage, oldest pending job, recent jobs."""
    pending = sorted(PENDING_STATUSES)
    counts = session.execute(
        select(DesignJob.designer_id, DesignJob.status, func.count()).group_by(DesignJob.designer_id, DesignJob.status)
    ).all()
    oldest = dict(
        session.execute(
            select(DesignJob.designer_id, func.min(DesignJob.assigned_at))
            .where(DesignJob.status.in_(pending))
            .group_by(DesignJob.designer_id)
        ).all()
    )
    names = _names(session)
    out = []
    designers = list(session.scalars(select(Designer).order_by(Designer.rotation_order)))
    for d in designers:
        by_stage = {str(s): 0 for s in STATUSES}
        for designer_id, status, n in counts:
            if designer_id == d.id:
                by_stage[str(status)] = n
        jobs = session.scalars(
            select(DesignJob)
            .where(DesignJob.designer_id == d.id)
            .order_by(case((DesignJob.status.in_(pending), 0), else_=1), DesignJob.assigned_at.desc(), DesignJob.id.desc())
            .limit(jobs_per_designer)
        )
        out.append(
            {
                **designer_json(d),
                "pending": sum(by_stage[str(s)] for s in pending),
                "by_status": by_stage,
                "oldest_pending_at": utc_iso(oldest.get(d.id)),
                "jobs": [job_json(j, names) for j in jobs],
            }
        )
    unassigned = sum(n for designer_id, status, n in counts if designer_id is None and status in PENDING_STATUSES)
    return {"designers": out, "unassigned_pending": unassigned}


# ---------- products ----------
# A design job's products are the non-add-on lines of its invoice (app/products.py). Each has its
# own designer (None = the order's designer), status and vendor, in design_items; a product
# without a row is at status 1 with the order's designer and no vendor.

def items_ready(session: Session) -> bool:
    """Whether migration 0007's per-product tables are there."""
    have = set(inspect(session.get_bind()).get_table_names())
    return all(t in have for t in ITEM_TABLES)


def _invoice_lines(session: Session, jobs: list[DesignJob]) -> dict[tuple[str, int], list]:
    from ..invoice.store import ROW_CLASSES  # imported here: the invoice package imports this module

    out: dict[tuple[str, int], list] = {}
    for series in JOB_SERIES:
        numbers = {j.bill_no for j in jobs if j.series == series}
        if numbers:
            row = ROW_CLASSES[series]
            for bill_no, lines in session.execute(select(row.bill_no, row.lines).where(row.bill_no.in_(numbers))):
                out[(series, bill_no)] = lines
    return out


def product_json(product: dict, item: DesignItem | None, job: DesignJob, names: dict[int, str]) -> dict:
    own = item.designer_id if item else None
    designer_id = own if own is not None else job.designer_id
    status = item.status if item else 1
    return {
        **product,
        "designer_id": own,
        "designer_name": names.get(designer_id) if designer_id is not None else None,
        "designer_inherited": own is None,
        "status": status,
        "status_label": STATUSES[status],
        "pending": status in PENDING_STATUSES,
        "vendor_name": item.vendor_name if item else None,
        "updated_at": utc_iso(item.updated_at) if item else None,
    }


def attach_products(session: Session, jobs: list[DesignJob], out: list[dict], names: dict[int, str]) -> None:
    """Adds `products` to each job's JSON (empty until migration 0007 has run)."""
    ready = items_ready(session)
    lines = _invoice_lines(session, jobs) if ready else {}
    items: dict[tuple[int, int], DesignItem] = {}
    if ready and jobs:
        for item in session.scalars(select(DesignItem).where(DesignItem.job_id.in_([j.id for j in jobs]))):
            items[(item.job_id, item.line_no)] = item
    for job, data in zip(jobs, out):
        found = invoice_products(lines.get((job.series, job.bill_no)))
        data["products"] = [product_json(p, items.get((job.id, p["line_no"])), job, names) for p in found]


def update_product(session: Session, job_id: int, line_no: int, changes: dict) -> dict:
    """One product's `designer_id` (None = the order's designer), `status` (1-6) and/or
    `vendor_name`. Other products and the order itself are untouched. Answers the whole job."""
    if not items_ready(session):
        raise DesignerError(
            "DESIGNERS_NOT_SET_UP", "The per-product design tables aren't in the database yet: run the migrations", 503
        )
    job = session.get(DesignJob, job_id)
    if job is None:
        raise _not_found("Job", job_id)
    lines = _invoice_lines(session, [job]).get((job.series, job.bill_no))
    if line_no not in [p["line_no"] for p in invoice_products(lines)]:
        raise DesignerError("NOT_FOUND", f"The invoice has no product {line_no}", 404, {"field": "line_no"})
    item = session.get(DesignItem, (job_id, line_no))
    if item is None:
        item = DesignItem(job_id=job_id, line_no=line_no, designer_id=None, status=1, vendor_name=None,
                          updated_at=db_now(session))
        session.add(item)
    changed = False
    if "designer_id" in changes and changes["designer_id"] != item.designer_id:
        if changes["designer_id"] is not None and session.get(Designer, changes["designer_id"]) is None:
            raise _not_found("Designer", changes["designer_id"])
        item.designer_id = changes["designer_id"]
        changed = True
    if "status" in changes and changes["status"] != item.status:
        new = changes["status"]
        if new not in STATUSES:
            raise DesignerError("VALIDATION_ERROR", "Status must be 1 to 6", 422, {"field": "status"})
        session.add(DesignItemHistory(job_id=job_id, line_no=line_no, old_status=item.status, new_status=new,
                                      changed_at=db_now(session)))
        item.status = new
        changed = True
    if "vendor_name" in changes:
        vendor = clean_vendor(changes["vendor_name"])
        if vendor != item.vendor_name:
            item.vendor_name = vendor
            changed = True
    if not changed:
        session.rollback()
    else:
        item.updated_at = db_now(session)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            raise DesignerError("CONFLICT", "Someone else just changed this product - refresh and try again", 409) from None
    names = _names(session)
    out = job_json(job, names)
    attach_products(session, [job], [out], names)
    return out
