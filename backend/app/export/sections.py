"""Rows for the Google Sheets export (docs/google-sheets-sync.md).

One function per section. Each reads the database only (never writes) and returns flat rows:
dates as ISO strings, amounts and quantities as Decimal (sent as plain JSON numbers by
routes.py). The keys of each row are COLUMNS[section], in that order; the Apps Script in
scripts/google-sheets-sync.gs names the same keys (tests/test_export.py keeps them equal).

Customer and employee contact details, GSTINs, IPs, devices and log details are left out on
purpose (owner's decision, 2026-10-12).

Rows come oldest first in a stable order, so a row added during a sync lands on a later page
instead of shifting the pages already fetched.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..audit import service as audit_service
from ..audit.models import CATEGORIES, AuditEntry
from ..designers import service as designer_service
from ..designers.models import STATUSES, DesignItem, DesignJob
from ..designers.service import utc_iso
from ..invoice.config import InvoiceConfig
from ..invoice.money import line_subtotal
from ..invoice.store import ROW_CLASSES
from ..production import service as production_service
from ..production.models import ItemProgress, ProductionEmployee, ProductionJob
from ..products import products as invoice_products
from ..team import service as team_service
from ..team.models import ROLES, Attendance, Employee

# Invoices only: quotations aren't exported (owner's decision, 2026-10-12).
SERIES = ("non_gst", "gst")
SERIES_LABELS = {"non_gst": "Non-GST", "gst": "GST"}
KIND_LABELS = {"catalogue": "Product", "custom": "Custom", "addon": "Add-on", "customisation": "Customisation"}

COLUMNS: dict[str, tuple[str, ...]] = {
    "invoices": (
        "type", "bill_no", "invoice_date", "business_name", "gst_slab", "line_count", "total", "gst_amount",
        "saving", "payable", "advance_pct", "received", "pending", "status", "payment_count",
        "last_payment_date", "payment_modes", "created_at", "updated_at",
    ),
    "invoice-items": (
        "type", "bill_no", "invoice_date", "business_name", "line_no", "kind", "parent_line_no", "product",
        "specs", "customisations", "quantity", "unit", "unit_price", "catalogue_unit_price", "line_amount",
        "price_edited", "hsn_code",
    ),
    "designer-jobs": (
        "type", "bill_no", "customer", "line_no", "product", "quantity", "unit", "size", "addons", "designer",
        "status_no", "status", "pending", "vendor", "assigned_at", "updated_at",
    ),
    "production": (
        "type", "bill_no", "customer", "line_no", "product", "quantity", "unit", "employee", "stage_no", "stage",
        "stages_done", "complete", "vendor", "created_at", "updated_at",
    ),
    "attendance": (
        "work_date", "employee_id", "employee", "role", "check_in", "check_out", "hours", "still_in", "note",
        "edited_by_admin", "updated_at",
    ),
    "employees": ("id", "name", "role", "joined_on", "active", "created_at", "updated_at"),
    "logs": ("id", "at", "category", "summary", "actor_role", "actor_name", "method", "path", "status"),
}


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _iso_date(value) -> str | None:
    return value.isoformat() if value is not None else None


def _utc(value: datetime) -> datetime:
    """SQLite hands back naive UTC; Postgres gives aware datetimes."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _page(rows: list[dict], offset: int, limit: int) -> tuple[list[dict], bool]:
    return rows[offset:offset + limit], len(rows) > offset + limit


def _spec_text(spec) -> str:
    if not isinstance(spec, dict):
        return ""
    label, value = spec.get("label") or "", spec.get("value") or ""
    return f"{label}: {value}" if label else str(value)


def _size(line: dict) -> str | None:
    """The size the invoice prints first: the emphasised spec, else one labelled Size."""
    specs = [s for s in (line.get("specs") or []) if isinstance(s, dict)]
    for spec in specs:
        if spec.get("emphasis"):
            return spec.get("value")
    for spec in specs:
        if (spec.get("label") or "").lower() == "size":
            return spec.get("value")
    return None


# ---------- invoices ----------

def _invoice_rows(session: Session, columns, offset: int, limit: int) -> tuple[list[tuple[str, object]], bool]:
    """(series, row) for Non-GST invoices then GST invoices, each by bill number, paged."""
    out: list[tuple[str, object]] = []
    skip, want = offset, limit + 1
    for series in SERIES:
        row = ROW_CLASSES[series]
        count = session.scalar(select(func.count()).select_from(row)) or 0
        if skip >= count:
            skip -= count
            continue
        query = select(*(getattr(row, c) for c in columns)).order_by(row.bill_no).offset(skip).limit(want - len(out))
        out += [(series, r) for r in session.execute(query)]
        skip = 0
        if len(out) >= want:
            break
    return out[:limit], len(out) > limit


def _slab_label(cfg: InvoiceConfig | None, key: str | None) -> str | None:
    if not key:
        return None
    if cfg is not None:
        for option in (*cfg.gst_slabs, *cfg.legacy_gst_options):
            if option.key == key:
                return option.label
    return key


def _mode_label(cfg: InvoiceConfig | None, mode: str) -> str:
    modes = (cfg.payment_summary or {}).get("modes", {}) if cfg is not None else {}
    return modes.get(mode, mode.replace("_", " ").upper())


INVOICE_FIELDS = (
    "bill_no", "invoice_date", "business_name", "lines", "payments", "total", "gst_amount", "gst", "saving_amount",
    "payable", "advance_pct", "received", "status", "created_at", "updated_at",
)


def invoices(session: Session, cfg: InvoiceConfig | None, offset: int, limit: int, since=None):
    found, more = _invoice_rows(session, INVOICE_FIELDS, offset, limit)
    rows = []
    for series, r in found:
        payments = [p for p in (r.payments or []) if isinstance(p, dict)]
        modes: list[str] = []
        for p in payments:
            label = _mode_label(cfg, str(p.get("mode") or "upi"))
            if label not in modes:
                modes.append(label)
        dates = sorted(str(p["date"]) for p in payments if p.get("date"))
        advance = r.advance_pct if r.advance_pct is not None else (cfg.advance_pct if cfg is not None else None)
        rows.append({
            "type": SERIES_LABELS[series],
            "bill_no": r.bill_no,
            "invoice_date": _iso_date(r.invoice_date),
            "business_name": r.business_name,
            "gst_slab": _slab_label(cfg, (r.gst or {}).get("option")),
            "line_count": len(r.lines or []),
            "total": r.total,
            "gst_amount": r.gst_amount,
            "saving": r.saving_amount,
            "payable": r.payable,
            "advance_pct": advance.normalize() if advance is not None else None,
            "received": r.received,
            "pending": r.payable - r.received,
            "status": cfg.status_labels.get(r.status, r.status) if cfg is not None else r.status,
            "payment_count": len(payments),
            "last_payment_date": dates[-1] if dates else None,
            "payment_modes": ", ".join(modes) or None,
            "created_at": utc_iso(r.created_at),
            "updated_at": utc_iso(r.updated_at),
        })
    return rows, more


def _all_invoice_lines(session: Session) -> list[tuple[str, object]]:
    out = []
    for series in SERIES:
        row = ROW_CLASSES[series]
        query = select(row.bill_no, row.invoice_date, row.business_name, row.lines).order_by(row.bill_no)
        out += [(series, r) for r in session.execute(query)]
    return out


def invoice_items(session: Session, cfg: InvoiceConfig | None, offset: int, limit: int, since=None):
    rows = []
    for series, r in _all_invoice_lines(session):
        lines = [l for l in (r.lines or []) if isinstance(l, dict)]
        positions = {l["id"]: i + 1 for i, l in enumerate(lines) if l.get("id")}
        for i, line in enumerate(lines):
            source = line.get("source") or ""
            kind = KIND_LABELS.get(source, source)
            if source == "customisation" and line.get("charge_basis"):
                kind += " (per order)" if line["charge_basis"] == "per_order" else " (per unit)"
            quantity, unit_price = _dec(line.get("quantity")), _dec(line.get("unit_price"))
            rows.append({
                "type": SERIES_LABELS[series],
                "bill_no": r.bill_no,
                "invoice_date": _iso_date(r.invoice_date),
                "business_name": r.business_name,
                "line_no": i + 1,
                "kind": kind,
                "parent_line_no": positions.get(line.get("parent_id")) if line.get("parent_id") else None,
                "product": line.get("title"),
                "specs": "; ".join(t for t in map(_spec_text, line.get("specs") or []) if t) or None,
                "customisations": "; ".join(t for t in map(_spec_text, line.get("customisations") or []) if t) or None,
                "quantity": quantity,
                "unit": line.get("unit_label"),
                "unit_price": unit_price,
                "catalogue_unit_price": _dec(line.get("catalogue_unit_price")),
                "line_amount": line_subtotal(quantity, unit_price) if quantity is not None and unit_price is not None else None,
                "price_edited": bool(line.get("price_edited")),
                "hsn_code": line.get("hsn_code") or None,
            })
    return _page(rows, offset, limit)


# ---------- designer assignment ----------

def designer_jobs(session: Session, cfg: InvoiceConfig | None, offset: int, limit: int, since=None):
    jobs = list(session.scalars(select(DesignJob).order_by(DesignJob.assigned_at, DesignJob.id)))
    names = designer_service._names(session)
    items_ready = designer_service.items_ready(session)
    lines = designer_service._invoice_lines(session, jobs)
    items: dict[tuple[int, int], DesignItem] = {}
    if items_ready and jobs:
        for item in session.scalars(select(DesignItem)):
            items[(item.job_id, item.line_no)] = item
    rows = []
    for job in jobs:
        stored = list(lines.get((job.series, job.bill_no)) or [])
        for product in invoice_products(stored):
            p = designer_service.product_json(product, items.get((job.id, product["line_no"])), job, names)
            if not items_ready:  # before migration 0007 progress was kept per order
                p.update(status=job.status, status_label=STATUSES[job.status], vendor_name=job.vendor_name,
                         pending=job.status in designer_service.PENDING_STATUSES)
            rows.append({
                "type": SERIES_LABELS.get(job.series, job.series),
                "bill_no": job.bill_no,
                "customer": job.customer_name,
                "line_no": product["line_no"] + 1,
                "product": product["title"],
                "quantity": _dec(product["quantity"]),
                "unit": product["unit_label"],
                "size": _size(stored[product["line_no"]]),
                "addons": ", ".join(product["addons"]) or None,
                "designer": p["designer_name"],
                "status_no": p["status"],
                "status": p["status_label"],
                "pending": p["pending"],
                "vendor": p["vendor_name"],
                "assigned_at": utc_iso(job.assigned_at),
                "updated_at": p["updated_at"] or utc_iso(job.updated_at),
            })
    return _page(rows, offset, limit)


# ---------- production ----------

def production(session: Session, cfg: InvoiceConfig | None, offset: int, limit: int, since=None):
    jobs = list(session.scalars(select(ProductionJob).order_by(ProductionJob.created_at, ProductionJob.id)))
    invoices_by_key = production_service._invoices(session, jobs)
    names = {e.id: e.name for e in session.scalars(select(ProductionEmployee))}
    progress: dict[int, dict[int, dict[int, ItemProgress]]] = {}
    for p in session.scalars(select(ItemProgress)):
        progress.setdefault(p.job_id, {}).setdefault(p.line_no, {})[p.stage] = p
    rows = []
    for job in jobs:
        invoice = invoices_by_key.get((job.series, job.bill_no))
        base = {
            "type": SERIES_LABELS.get(job.series, job.series),
            "bill_no": job.bill_no,
            "customer": invoice.business_name if invoice is not None else None,
        }
        employee = names.get(job.employee_id) if job.employee_id is not None else None
        found = invoice_products(invoice.lines) if invoice is not None else []
        if not found:  # the invoice was deleted, or has no products: still one row for the job
            rows.append({**dict.fromkeys(COLUMNS["production"]), **base, "employee": employee,
                         "created_at": utc_iso(job.created_at), "updated_at": utc_iso(job.updated_at)})
            continue
        for product in found:
            stage_rows = progress.get(job.id, {}).get(product["line_no"], {})
            state = production_service.progress_json(stage_rows)
            current = state["current_stage"]
            latest = max([_utc(job.updated_at), *(_utc(r.updated_at) for r in stage_rows.values())])
            rows.append({
                **base,
                "line_no": product["line_no"] + 1,
                "product": product["title"],
                "quantity": _dec(product["quantity"]),
                "unit": product["unit_label"],
                "employee": employee,
                "stage_no": current,
                "stage": state["current_label"],
                "stages_done": state["completed_count"],
                "complete": state["complete"],
                "vendor": stage_rows[current].vendor_name if current in stage_rows else None,
                "created_at": utc_iso(job.created_at),
                "updated_at": utc_iso(latest),
            })
    return _page(rows, offset, limit)


# ---------- attendance and employees ----------

def attendance(session: Session, cfg: InvoiceConfig | None, offset: int, limit: int, since=None):
    query = (
        select(Attendance, Employee.name, Employee.role)
        .join(Employee, Employee.id == Attendance.employee_id)
        .order_by(Attendance.work_date, Attendance.id)
        .offset(offset)
        .limit(limit + 1)
    )
    found = list(session.execute(query))
    rows = []
    for record, name, role in found[:limit]:
        minutes = team_service.minutes_worked(record)
        rows.append({
            "work_date": _iso_date(record.work_date),
            "employee_id": record.employee_id,
            "employee": name,
            "role": ROLES.get(role, role),
            "check_in": utc_iso(record.check_in),
            "check_out": utc_iso(record.check_out),
            "hours": (Decimal(minutes) / 60).quantize(Decimal("0.01")) if minutes is not None else None,
            "still_in": record.check_out is None,
            "note": record.note,
            "edited_by_admin": record.edited_by_admin,
            "updated_at": utc_iso(record.updated_at),
        })
    return rows, len(found) > limit


def employees(session: Session, cfg: InvoiceConfig | None, offset: int, limit: int, since=None):
    found = list(session.scalars(select(Employee).order_by(Employee.id).offset(offset).limit(limit + 1)))
    rows = [
        {
            "id": e.id,
            "name": e.name,
            "role": ROLES.get(e.role, e.role),
            "joined_on": _iso_date(e.joined_on),
            "active": e.active,
            "created_at": utc_iso(e.created_at),
            "updated_at": utc_iso(e.updated_at),
        }
        for e in found[:limit]
    ]
    return rows, len(found) > limit


# ---------- activity log ----------

def logs(session: Session, cfg: InvoiceConfig | None, offset: int, limit: int, since: datetime | None = None):
    query = select(AuditEntry)
    if since is not None:
        since = _utc(since)
        if session.get_bind().dialect.name == "sqlite":  # stored as naive UTC there
            since = since.replace(tzinfo=None)
        query = query.where(AuditEntry.at > since)
    found = list(session.scalars(query.order_by(AuditEntry.at, AuditEntry.id).offset(offset).limit(limit + 1)))
    rows = [
        {
            "id": e.id,
            "at": utc_iso(e.at),
            "category": CATEGORIES.get(e.category, e.category),
            "summary": e.summary,
            "actor_role": e.actor_role,
            "actor_name": e.actor_name,
            "method": e.method,
            "path": e.path,
            "status": e.status,
        }
        for e in found[:limit]
    ]
    return rows, len(found) > limit


SECTIONS = {
    "invoices": invoices,
    "invoice-items": invoice_items,
    "designer-jobs": designer_jobs,
    "production": production,
    "attendance": attendance,
    "employees": employees,
    "logs": logs,
}


def ready(section: str, store) -> bool:
    """Whether the section's tables exist. The invoice tables always do (the Store checks)."""
    engine = store.engine
    if section == "designer-jobs":
        return store.designers_available()
    if section == "production":
        return production_service.tables_ready(engine)
    if section in ("attendance", "employees"):
        return team_service.tables_ready(engine)
    if section == "logs":
        return audit_service.tables_ready(engine)
    return True
