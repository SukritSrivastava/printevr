"""Create invoices and record payments (BRD-cart-invoice FR-P7, 8.2, 8.3).

Validate -> re-price catalogue lines -> check payments -> bill number -> save -> render.
Stored invoices are never re-priced: downloads render from the stored JSON.
"""
import logging
import threading
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from ..catalogue import Catalogue
from ..quote import QuoteError
from . import fmt, gst
from .config import InvoiceConfig
from .from_quote import quote_with_drafts
from .models import CartLine, InvoiceCreate, InvoiceDocument, Payment, PaymentCreate, TaxLine
from .money import Money, Overpaid, compute, line_subtotal
from .render import doc_components, render
from .store import InvoiceRow, Store, utcnow

log = logging.getLogger("printevr.invoice")

BILL_NO_RETRIES = 3
# SQLite serialises writers anyway; this keeps "max + 1" and the insert together in one process.
_write_lock = threading.Lock()


class InvoiceError(Exception):
    def __init__(self, code: str, message: str, http_status: int, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.details = details or {}


@dataclass
class Rendered:
    bill_no: int
    status: str
    filename: str
    pdf: bytes
    business_name: str = ""


def _validation(message: str, **details) -> InvoiceError:
    return InvoiceError("VALIDATION_ERROR", message, 422, details)


def _dec(value) -> Decimal:
    return Decimal(str(value))


# ---------------------------------------------------------------- re-pricing


def reprice(cat: Catalogue, cfg: InvoiceConfig, lines: list[CartLine]) -> list[CartLine]:
    """Re-quote every catalogue line from its calc_request (FR-P7 2-4).

    Returns the lines with `price_edited` set; raises PRICES_CHANGED or LINE_NOT_PRICEABLE.
    """
    fresh: dict[str, list[dict]] = {}
    changes: list[dict] = []
    ids = [l.id for l in lines if l.id]
    if len(ids) != len(set(ids)):
        raise _validation("Line ids must be unique")

    for line in lines:
        if line.source != "catalogue":
            continue
        if not line.id or line.calc_request is None:
            raise _validation("Catalogue lines need an id and calc_request", line=line.id)
        try:
            result = quote_with_drafts(cat, line.calc_request, cfg.unit_plurals)
        except QuoteError as exc:
            raise InvoiceError(
                "LINE_NOT_PRICEABLE", f"'{line.title}' can't be priced any more: {exc.message}", 422, {"id": line.id}
            ) from None
        if result["status"] != "success":
            raise InvoiceError(
                "LINE_NOT_PRICEABLE", f"'{line.title}' now needs a manual quote", 422, {"id": line.id}
            )
        drafts = result["data"]["invoice_lines"]
        fresh[line.id] = drafts
        main = drafts[0]
        if _dec(main["quantity"]) != line.quantity or _dec(main["catalogue_unit_price"]) != line.catalogue_unit_price:
            changes.append(
                {
                    "id": line.id,
                    "quantity": main["quantity"],
                    "catalogue_unit_price": main["catalogue_unit_price"],
                    "warnings": main["warnings"],
                }
            )

    for line in lines:
        if line.source != "addon":
            continue
        parent = fresh.get(line.parent_id or "")
        if parent is None:
            raise _validation("An add-on line must follow its catalogue line in the same invoice", line=line.id)
        match = next(
            (d for d in parent[1:] if (line.addon_id and d.get("addon_id") == line.addon_id) or d["title"] == line.title),
            None,
        )
        if match is None:
            raise InvoiceError(
                "LINE_NOT_PRICEABLE", f"'{line.title}' is no longer offered with its article", 422, {"id": line.id}
            )
        if _dec(match["catalogue_unit_price"]) != line.catalogue_unit_price:
            changes.append(
                {"id": line.id, "quantity": _plain_qty(line.quantity), "catalogue_unit_price": match["catalogue_unit_price"], "warnings": []}
            )

    if changes:
        raise InvoiceError("PRICES_CHANGED", "Prices changed since these were added", 409, {"lines": changes})

    out = []
    for line in lines:
        edited = line.source != "custom" and line.catalogue_unit_price is not None and line.unit_price != line.catalogue_unit_price
        out.append(line.model_copy(update={"price_edited": edited}))
    return out


def _plain_qty(q: Decimal) -> int | float:
    return int(q) if q == q.to_integral_value() else float(q)


# ---------------------------------------------------------------- helpers


def gst_option(cfg: InvoiceConfig, body: InvoiceCreate) -> gst.GstOption | None:
    """The chosen GST option for With GST billing (400 if missing or unknown); None without GST."""
    if body.billing_type != "with_gst":
        return None
    try:
        return gst.find(cfg.gst_options, body.gst_option)
    except gst.InvalidGstOption as exc:
        raise InvoiceError(
            "INVALID_GST_OPTION", str(exc), 400, {"field": "gst_option", "allowed": [o.key for o in cfg.gst_options]}
        ) from None


def _gst_record(option: gst.GstOption | None, m: Money) -> dict | None:
    """What is stored with the invoice: the option chosen and each tax row as issued."""
    if option is None:
        return None
    taxes = [TaxLine(name=t.name, rate=t.rate, amount=t.amount).model_dump(mode="json") for t in m.taxes]
    return {"option": option.key, "taxes": taxes}


def _money(doc_lines: list[CartLine], components, cfg: InvoiceConfig, payments: list[Payment]) -> Money:
    subtotals = [line_subtotal(l.quantity, l.unit_price) for l in doc_lines]
    try:
        return compute(subtotals, components, cfg.advance_pct, [p.amount for p in payments])
    except Overpaid as exc:
        raise InvoiceError(
            "OVERPAID",
            f"Received {fmt.amount(exc.received)} is more than the payable {fmt.amount(exc.payable)}",
            422,
            {"received": str(exc.received), "payable": str(exc.payable)},
        ) from None


def document(row: InvoiceRow) -> InvoiceDocument:
    record = row.gst or {}
    return InvoiceDocument.model_validate(
        {
            "bill_no": row.bill_no,
            "invoice_date": row.invoice_date,
            "billing_type": row.billing_type,
            "gst_option": record.get("option"),
            "taxes": record.get("taxes") or [],
            "customer": row.customer,
            "lines": row.lines,
            "payments": row.payments,
            "saving_amount": row.saving_amount,
        }
    )


def _rendered(row: InvoiceRow, cfg: InvoiceConfig) -> Rendered:
    pdf = render(document(row), cfg)
    name = fmt.filename(cfg.filename, row.bill_no, row.business_name, cfg.status_labels[row.status])
    return Rendered(bill_no=row.bill_no, status=row.status, filename=name, pdf=pdf, business_name=row.business_name)


def _event_detail(row: InvoiceRow) -> dict:
    return {
        "version": row.version,
        "total": str(row.total),
        "payable": str(row.payable),
        "received": str(row.received),
        "status": row.status,
    }


def _payment_json(p: Payment | PaymentCreate) -> dict:
    data = Payment(**p.model_dump(exclude={"recorded_at"})).model_dump(mode="json")
    data["recorded_at"] = utcnow().isoformat()
    return data


def row_summary(row: InvoiceRow) -> dict:
    return {
        "bill_no": row.bill_no,
        "invoice_date": row.invoice_date.isoformat(),
        "business_name": row.business_name,
        "billing_type": row.billing_type,
        "total": format(row.total, "f"),
        "payable": format(row.payable, "f"),
        "received": format(row.received, "f"),
        "status": row.status,
        "version": row.version,
    }


def row_detail(row: InvoiceRow) -> dict:
    return {
        **row_summary(row),
        "customer": row.customer,
        "lines": row.lines,
        "payments": row.payments,
        "saving_amount": format(row.saving_amount, "f") if row.saving_amount is not None else None,
        "gst_amount": format(row.gst_amount, "f"),
        "gst": row.gst,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


# ---------------------------------------------------------------- operations


def next_bill_no(store: Store, cfg: InvoiceConfig) -> int:
    with store.session() as s:
        return store.next_bill_no(s, cfg.bill_no_start)


def _check_print_mode(body: InvoiceCreate) -> None:
    if body.print_mode == "unpaid" and body.payments:
        raise _validation("Print (Unpaid as of now) takes no payments", field="payments")
    if body.print_mode == "paid" and not body.payments:
        raise _validation("Print (Paid) needs at least one payment", field="payments")


def create_unsaved(cat: Catalogue, cfg: InvoiceConfig, body: InvoiceCreate) -> Rendered:
    """No database: the same checks and PDF as create(), but nothing is stored.

    The server can't count bill numbers without storage, so the client must send one.
    """
    _check_print_mode(body)
    if body.bill_no is None:
        raise _validation("Enter a Bill No", field="bill_no")
    option = gst_option(cfg, body)
    lines = reprice(cat, cfg, body.lines)
    payments = [Payment(**p.model_dump(exclude={"recorded_at"})) for p in body.payments]
    m = _money(lines, option.components if option else (), cfg, payments)
    record = _gst_record(option, m) or {}
    doc = InvoiceDocument(
        bill_no=body.bill_no,
        invoice_date=body.invoice_date,
        billing_type=body.billing_type,
        gst_option=record.get("option"),
        taxes=record.get("taxes") or [],
        customer=body.customer,
        lines=lines,
        payments=payments,
        saving_amount=body.saving_amount if body.saving_amount else None,
    )
    name = fmt.filename(cfg.filename, body.bill_no, body.customer.business_name, cfg.status_labels[m.status])
    log.info(
        "invoice rendered (not stored) bill_no=%s lines=%s total=%s gst_option=%s gst=%s payable=%s received=%s status=%s",
        body.bill_no, len(lines), m.total, option.key if option else None, m.gst, m.payable, m.received, m.status,
    )
    return Rendered(
        bill_no=body.bill_no, status=m.status, filename=name, pdf=render(doc, cfg), business_name=body.customer.business_name
    )


def create(store: Store, cat: Catalogue, cfg: InvoiceConfig, body: InvoiceCreate) -> Rendered:
    _check_print_mode(body)
    option = gst_option(cfg, body)
    lines = reprice(cat, cfg, body.lines)
    m = _money(lines, option.components if option else (), cfg, body.payments)
    payments = [_payment_json(p) for p in body.payments]

    def new_row(bill_no: int) -> InvoiceRow:
        now = utcnow()
        return InvoiceRow(
            bill_no=bill_no,
            invoice_date=body.invoice_date,
            billing_type=body.billing_type,
            business_name=body.customer.business_name,
            customer=body.customer.model_dump(mode="json"),
            lines=[l.model_dump(mode="json") for l in lines],
            payments=payments,
            saving_amount=body.saving_amount if body.saving_amount else None,
            total=m.total,
            gst_amount=m.gst,
            gst=_gst_record(option, m),
            payable=m.payable,
            received=m.received,
            status=m.status,
            version=1,
            created_at=now,
            updated_at=now,
        )

    with _write_lock:
        row = None
        for _ in range(BILL_NO_RETRIES + 1):
            with store.session() as s:
                if body.bill_no is not None:
                    if store.exists(s, body.bill_no):
                        raise InvoiceError(
                            "BILL_NO_TAKEN",
                            f"Bill No {body.bill_no} is already used",
                            409,
                            {"next_bill_no": store.next_bill_no(s, cfg.bill_no_start)},
                        )
                    bill_no = body.bill_no
                else:
                    bill_no = store.next_bill_no(s, cfg.bill_no_start)
                candidate = new_row(bill_no)
                s.add(candidate)
                store.add_event(s, bill_no, "created", _event_detail(candidate))
                try:
                    s.commit()
                    row = candidate
                    break
                except IntegrityError:
                    s.rollback()
                    if body.bill_no is not None:
                        raise InvoiceError(
                            "BILL_NO_TAKEN",
                            f"Bill No {body.bill_no} is already used",
                            409,
                            {"next_bill_no": store.next_bill_no(s, cfg.bill_no_start)},
                        ) from None
        if row is None:
            raise InvoiceError("BILL_NO_CONFLICT", "Couldn't assign a bill number - try again", 409)

    log.info(
        "invoice created bill_no=%s lines=%s total=%s payable=%s received=%s status=%s",
        row.bill_no, len(lines), row.total, row.payable, row.received, row.status,
    )
    return _rendered(row, cfg)


def add_payment(store: Store, cfg: InvoiceConfig, bill_no: int, payment: PaymentCreate) -> Rendered:
    with _write_lock, store.session() as s:
        row = store.get(s, bill_no)
        if row is None:
            raise InvoiceError("NOT_FOUND", f"No invoice with Bill No {bill_no}", 404)
        if row.status == "paid":
            raise InvoiceError("ALREADY_PAID", f"Invoice {bill_no} is already paid in full", 422)
        doc = document(row)
        payments = [*doc.payments, Payment(**payment.model_dump())]
        m = _money(doc.lines, doc_components(doc), cfg, payments)
        row.payments = [*row.payments, _payment_json(payment)]
        row.received = m.received
        row.status = m.status
        row.version += 1
        row.updated_at = utcnow()
        store.add_event(s, bill_no, "payment_added", _event_detail(row))
        s.commit()
    log.info("invoice payment bill_no=%s received=%s status=%s version=%s", bill_no, row.received, row.status, row.version)
    return _rendered(row, cfg)


def delete(store: Store, bill_no: int) -> dict:
    """Removes the invoice and its events: nothing about it stays in the database."""
    with _write_lock, store.session() as s:
        row = store.get(s, bill_no)
        if row is None:
            raise InvoiceError("NOT_FOUND", f"No invoice with Bill No {bill_no}", 404)
        store.delete(s, row)
        s.commit()
    log.info("invoice deleted bill_no=%s", bill_no)
    return {"deleted": bill_no}


def download(store: Store, cfg: InvoiceConfig, bill_no: int) -> Rendered:
    with store.session() as s:
        row = store.get(s, bill_no)
        if row is None:
            raise InvoiceError("NOT_FOUND", f"No invoice with Bill No {bill_no}", 404)
        store.add_event(s, bill_no, "downloaded", {"version": row.version})
        s.commit()
    return _rendered(row, cfg)


def detail(store: Store, bill_no: int) -> dict:
    with store.session() as s:
        row = store.get(s, bill_no)
        if row is None:
            raise InvoiceError("NOT_FOUND", f"No invoice with Bill No {bill_no}", 404)
        return row_detail(row)


def listing(store: Store, q: str | None, status: str | None, limit: int, offset: int) -> dict:
    with store.session() as s:
        rows, total = store.search(s, q, status, limit, offset)
        return {"invoices": [row_summary(r) for r in rows], "total": total, "limit": limit, "offset": offset}
