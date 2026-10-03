"""Production jobs, per-product stage progress, and production employees.

A production job belongs to one issued invoice (Non-GST or GST, by bill number). The invoice
holds the customer, the amount and the products (app/products.py), so the job stores only its
assigned employee and, per product and stage, a vendor, a Completed tick and whether the work
was sent to the vendor and picked up. A product's current stage is its first stage not ticked
Completed; a job is complete when every product is.

Before products had their own stages, progress was kept for the whole order
(production_stage_progress). Migration 0007 moved it onto the product of single-product
orders; for orders with several products it is shown read-only as `order_record`.
"""
from datetime import datetime, timezone

from sqlalchemy import delete, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..designers.service import DesignerError as ProductionError
from ..designers.service import utc_iso
from ..invoice.store import ROW_CLASSES
from ..products import products as invoice_products
from .models import (
    JOB_SERIES, NAME_MAX, STAGES, TABLES, VENDOR_MAX, ItemProgress, ProductionEmployee, ProductionJob, StageProgress,
)

STAGES_JSON = [{"value": k, "label": v} for k, v in STAGES.items()]
PROGRESS_FIELDS = ("completed", "sent_to_vendor", "received")


def tables_ready(engine) -> bool:
    have = set(inspect(engine).get_table_names())
    return all(t in have for t in TABLES)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _not_found(what: str, id_: int) -> ProductionError:
    return ProductionError("NOT_FOUND", f"{what} {id_} doesn't exist", 404)


# ---------- employees ----------

def employee_json(e: ProductionEmployee) -> dict:
    return {"id": e.id, "name": e.name}


def list_employees(session: Session) -> list[dict]:
    return [employee_json(e) for e in session.scalars(select(ProductionEmployee).order_by(ProductionEmployee.id))]


def add_employee(session: Session, name: str) -> dict:
    """Spaces are squeezed; a name already on the list (any capitalisation) is refused."""
    name = " ".join(name.split())
    if not name:
        raise ProductionError("VALIDATION_ERROR", "Enter a name", 422, {"field": "name"})
    if len(name) > NAME_MAX:
        raise ProductionError("VALIDATION_ERROR", f"Names are at most {NAME_MAX} characters", 422, {"field": "name"})
    taken = session.scalar(select(ProductionEmployee).where(func.lower(ProductionEmployee.name) == name.lower()))
    if taken is not None:
        raise ProductionError("NAME_TAKEN", f"{taken.name} is already on the list", 409, {"field": "name"})
    employee = ProductionEmployee(name=name, created_at=_now())
    session.add(employee)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProductionError("NAME_TAKEN", f"{name} was just added - refresh and try again", 409) from None
    return employee_json(employee)


def _check_employee(session: Session, employee_id: int | None) -> None:
    if employee_id is not None and session.get(ProductionEmployee, employee_id) is None:
        raise _not_found("Employee", employee_id)


def _names(session: Session) -> dict[int, str]:
    return {e.id: e.name for e in session.scalars(select(ProductionEmployee))}


# ---------- jobs ----------

def _invoices(session: Session, jobs: list[ProductionJob]) -> dict[tuple[str, int], object]:
    """The invoice row behind each job, by (series, bill_no). A missing one was deleted."""
    out: dict[tuple[str, int], object] = {}
    for series in JOB_SERIES:
        numbers = {j.bill_no for j in jobs if j.series == series}
        if numbers:
            row = ROW_CLASSES[series]
            for r in session.scalars(select(row).where(row.bill_no.in_(numbers))):
                out[(series, r.bill_no)] = r
    return out


def _item_progress(session: Session, job_ids: list[int]) -> dict[int, dict[int, dict[int, ItemProgress]]]:
    """job_id -> line_no -> stage -> row."""
    out: dict[int, dict[int, dict[int, ItemProgress]]] = {i: {} for i in job_ids}
    if job_ids:
        for p in session.scalars(select(ItemProgress).where(ItemProgress.job_id.in_(job_ids))):
            out[p.job_id].setdefault(p.line_no, {})[p.stage] = p
    return out


def _order_progress(session: Session, job_ids: list[int]) -> dict[int, dict[int, StageProgress]]:
    out: dict[int, dict[int, StageProgress]] = {i: {} for i in job_ids}
    if job_ids:
        for p in session.scalars(select(StageProgress).where(StageProgress.job_id.in_(job_ids))):
            out[p.job_id][p.stage] = p
    return out


def current_stage(rows: dict) -> int | None:
    """The first stage not ticked Completed, or None when every stage is."""
    return next((s for s in STAGES if not (s in rows and rows[s].completed)), None)


def stage_json(stage: int, p) -> dict:
    return {
        "stage": stage,
        "label": STAGES[stage],
        "vendor_name": p.vendor_name if p else None,
        "completed": bool(p and p.completed),
        "sent_to_vendor": bool(p and p.sent_to_vendor),
        "received": bool(p and p.received),
        "updated_at": utc_iso(p.updated_at) if p else None,
    }


def progress_json(rows: dict) -> dict:
    current = current_stage(rows)
    return {
        "current_stage": current,
        "current_label": STAGES[current] if current else None,
        "complete": current is None,
        "completed_count": sum(1 for s in STAGES if s in rows and rows[s].completed),
        "stages": [stage_json(s, rows.get(s)) for s in STAGES],
    }


def job_json(job: ProductionJob, invoice, names: dict[int, str], items: dict, order_rows: dict) -> dict:
    found = invoice is not None
    products = [{**p, **progress_json(items.get(p["line_no"], {}))} for p in (invoice_products(invoice.lines) if found else [])]
    done = sum(1 for p in products if p["complete"])
    # The whole-order record kept from before per-product tracking, where it couldn't be moved
    # onto a single product: shown read-only, never copied to the products.
    record = None
    if order_rows and len(products) != 1:
        record = progress_json(order_rows)
        record["stages"] = [s for s in record["stages"] if s["completed"] or s["vendor_name"] or s["sent_to_vendor"] or s["received"]]
    return {
        "id": job.id,
        "series": job.series,
        "bill_no": job.bill_no,
        "invoice_found": found,
        "customer_name": invoice.business_name if found else None,
        "invoice_total": f"{invoice.payable:.2f}" if found else None,
        "products": products,
        "products_complete": done,
        "complete": bool(products) and done == len(products),
        "order_record": record,
        "employee_id": job.employee_id,
        "employee_name": names.get(job.employee_id) if job.employee_id is not None else None,
        "created_at": utc_iso(job.created_at),
        "updated_at": utc_iso(job.updated_at),
    }


def _one_json(session: Session, job: ProductionJob) -> dict:
    invoice = _invoices(session, [job]).get((job.series, job.bill_no))
    return job_json(job, invoice, _names(session), _item_progress(session, [job.id])[job.id],
                    _order_progress(session, [job.id])[job.id])


def vendors(session: Session, limit: int = 50) -> list[str]:
    """Vendor names already used on any product's stage, most used first (suggestions)."""
    query = (
        select(ItemProgress.vendor_name, func.count())
        .where(ItemProgress.vendor_name.is_not(None))
        .group_by(ItemProgress.vendor_name)
        .order_by(func.count().desc(), ItemProgress.vendor_name)
        .limit(limit)
    )
    return [name for name, _ in session.execute(query)]


def list_jobs(session: Session) -> dict:
    jobs = list(session.scalars(select(ProductionJob).order_by(ProductionJob.created_at.desc(), ProductionJob.id.desc())))
    ids = [j.id for j in jobs]
    invoices = _invoices(session, jobs)
    names = _names(session)
    items = _item_progress(session, ids)
    orders = _order_progress(session, ids)
    return {
        "jobs": [job_json(j, invoices.get((j.series, j.bill_no)), names, items[j.id], orders[j.id]) for j in jobs],
        "stages": STAGES_JSON,
        "vendors": vendors(session),
    }


def add_job(session: Session, series: str, bill_no: int, employee_id: int | None) -> dict:
    if series not in JOB_SERIES:
        raise ProductionError("VALIDATION_ERROR", "Only Non-GST and GST invoices go into production", 422, {"field": "series"})
    label = "GST invoice" if series == "gst" else "Invoice"
    row = ROW_CLASSES[series]
    if session.scalar(select(row.id).where(row.bill_no == bill_no)) is None:
        raise ProductionError("INVOICE_NOT_FOUND", f"{label} {bill_no} doesn't exist", 404, {"field": "bill_no"})
    taken = select(ProductionJob.id).where(ProductionJob.series == series, ProductionJob.bill_no == bill_no)
    if session.scalar(taken) is not None:
        raise ProductionError("JOB_EXISTS", f"{label} {bill_no} is already in production", 409, {"field": "bill_no"})
    _check_employee(session, employee_id)
    now = _now()
    job = ProductionJob(series=series, bill_no=bill_no, stage=1, employee_id=employee_id, created_at=now, updated_at=now)
    session.add(job)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProductionError("JOB_EXISTS", f"{label} {bill_no} was just added - refresh", 409) from None
    return _one_json(session, job)


def _job(session: Session, job_id: int) -> ProductionJob:
    job = session.get(ProductionJob, job_id)
    if job is None:
        raise _not_found("Job", job_id)
    return job


def update_job(session: Session, job_id: int, changes: dict) -> dict:
    """changes may hold `employee_id` (None unassigns)."""
    job = _job(session, job_id)
    if "employee_id" in changes and changes["employee_id"] != job.employee_id:
        _check_employee(session, changes["employee_id"])
        job.employee_id = changes["employee_id"]
        job.updated_at = _now()
        session.commit()
    return _one_json(session, job)


def clean_vendor(value: str | None) -> str | None:
    value = " ".join((value or "").split())
    if len(value) > VENDOR_MAX:
        raise ProductionError(
            "VALIDATION_ERROR", f"Vendor names are at most {VENDOR_MAX} characters", 422, {"field": "vendor_name"}
        )
    return value or None


def update_product_stage(session: Session, job_id: int, line_no: int, stage: int, changes: dict) -> dict:
    """One product's one stage: `vendor_name` (None or blank clears it), `completed`,
    `sent_to_vendor`, `received`. Other stages, products and jobs are untouched. Answers the job."""
    if stage not in STAGES:
        raise ProductionError("VALIDATION_ERROR", f"Stage must be 1 to {len(STAGES)}", 422, {"field": "stage"})
    job = _job(session, job_id)
    invoice = _invoices(session, [job]).get((job.series, job.bill_no))
    line_nos = [p["line_no"] for p in invoice_products(invoice.lines)] if invoice is not None else []
    if line_no not in line_nos:
        raise ProductionError("NOT_FOUND", f"The invoice has no product {line_no}", 404, {"field": "line_no"})
    row = session.get(ItemProgress, (job_id, line_no, stage))
    if row is None:
        row = ItemProgress(job_id=job_id, line_no=line_no, stage=stage, vendor_name=None, completed=False,
                           sent_to_vendor=False, received=False, updated_at=_now())
        session.add(row)
    changed = False
    if "vendor_name" in changes:
        vendor = clean_vendor(changes["vendor_name"])
        if vendor != row.vendor_name:
            row.vendor_name = vendor
            changed = True
    for field in PROGRESS_FIELDS:
        if field in changes and changes[field] is not None and bool(changes[field]) != getattr(row, field):
            setattr(row, field, bool(changes[field]))
            changed = True
    if not changed:
        session.rollback()
        return _one_json(session, job)
    now = _now()
    row.updated_at = now
    job.updated_at = now
    session.flush()
    items = _item_progress(session, [job_id])[job_id]
    currents = [current_stage(items.get(n, {})) for n in line_nos]
    open_stages = [c for c in currents if c is not None]
    job.stage = min(open_stages) if open_stages else len(STAGES)  # the column keeps the earliest current stage
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProductionError("CONFLICT", "Someone else just changed this stage - refresh and try again", 409) from None
    return _one_json(session, job)


def delete_job(session: Session, job_id: int) -> dict:
    """Takes a job (and all its stage records) off the production list. The invoice isn't touched."""
    job = _job(session, job_id)
    session.execute(delete(ItemProgress).where(ItemProgress.job_id == job_id))
    session.execute(delete(StageProgress).where(StageProgress.job_id == job_id))
    session.delete(job)
    session.commit()
    return {"deleted": job_id}
