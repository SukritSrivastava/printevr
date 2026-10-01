"""Create quotations and invoices and record payments (BRD-cart-invoice FR-P7, 8.2, 8.3).

Validate -> re-price catalogue lines -> check payments -> number -> save -> render.
Stored documents are never re-priced: downloads render from the stored JSON.

Three series, each numbered on its own: quotation, non_gst (the Printevr invoice, which
continues the existing invoice numbers) and gst (BASTTA GST invoice).
"""
import logging
import threading
from dataclasses import dataclass
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from ..catalogue import Catalogue
from ..models import CalculateRequest
from ..quote import QuoteError
from . import fmt, gst
from .config import InvoiceConfig
from .from_quote import quote_with_drafts
from .models import CartLine, Customer, InvoiceCreate, InvoiceDocument, Payment, PaymentCreate, TaxLine
from .money import Money, Overpaid, compute, line_subtotal
from .render import doc_advance_pct, doc_components, document_money, render_document
from .store import Store, utcnow

log = logging.getLogger("printevr.invoice")

BILL_NO_RETRIES = 3
# SQLite serialises writers anyway; this keeps "max + 1" and the insert together in one process.
_write_lock = threading.Lock()

BILLING_TYPES = {"non_gst": "without_gst", "gst": "gst", "quotation": "quotation"}
# A quotation has no payment state; this is what its row and download header say instead.
QUOTATION_STATUS = "issued"
NAMES = {"quotation": "Quotation", "non_gst": "Invoice", "gst": "GST invoice"}


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
    # What the email lists: the document as printed and its money.
    doc: InvoiceDocument | None = None
    money: Money | None = None
    series: str = "non_gst"


def _validation(message: str, **details) -> InvoiceError:
    return InvoiceError("VALIDATION_ERROR", message, 422, details)


def _not_found(series: str, bill_no: int) -> InvoiceError:
    return InvoiceError("NOT_FOUND", f"No {NAMES[series].lower()} with number {bill_no}", 404)


def _dec(value) -> Decimal:
    return Decimal(str(value))


def series_start(cfg: InvoiceConfig, series: str) -> int:
    if series == "quotation":
        return int(cfg.quotation["quote_no_start"])
    if series == "gst":
        return int(cfg.gst_invoice["bill_no_start"])
    return cfg.bill_no_start


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


# ---------------------------------------------------------------- checks


def check_request(cfg: InvoiceConfig, body: InvoiceCreate) -> gst.GstSlab | None:
    """What kind of document this is, and that its parts fit together. Returns the GST slab
    for a GST invoice, None for anything else.

    400 INVALID_GST_SLAB: a GST invoice without a (known) slab, or a slab on anything else.
    """
    if body.document_type == "quotation":
        if body.gst_slab:
            raise _slab_error("A GST slab only applies to a GST invoice, not a quotation", cfg)
        if body.print_mode or body.payments:
            raise _validation("A quotation has no paid or unpaid state", field="print_mode")
        return None
    if body.bill_type is None:
        raise _validation("Choose a bill type: Non-GST invoice or GST invoice", field="bill_type")
    if body.print_mode is None:
        raise _validation("Choose Print (Unpaid as of now) or Print (Paid)", field="print_mode")
    if body.print_mode == "unpaid" and body.payments:
        raise _validation("Print (Unpaid as of now) takes no payments", field="payments")
    if body.print_mode == "paid" and not body.payments:
        raise _validation("Print (Paid) needs at least one payment", field="payments")
    if body.bill_type == "non_gst":
        if body.gst_slab:
            raise _slab_error("A GST slab only applies to a GST invoice, not a Non-GST invoice", cfg)
        try:
            Customer.model_validate(body.customer.model_dump())
        except ValidationError as exc:
            fields = sorted({str(e["loc"][0]) for e in exc.errors()})
            raise _validation("Fill in Ship To: business name, address and phone", fields=fields) from None
        return None
    try:
        slab = gst.find_slab(cfg.gst_slabs, body.gst_slab)
    except gst.InvalidGstOption as exc:
        raise _slab_error(str(exc), cfg) from None
    if body.gst is None or not body.gst.buyer.name.strip():
        raise _validation("Enter the buyer's name for the GST invoice", field="gst.buyer.name")
    return slab


def _slab_error(message: str, cfg: InvoiceConfig) -> InvoiceError:
    return InvoiceError("INVALID_GST_SLAB", message, 400, {"field": "gst_slab", "allowed": [s.key for s in cfg.gst_slabs]})


# ---------------------------------------------------------------- helpers


def _product_id(cat: Catalogue, req: CalculateRequest | None) -> str | None:
    if req is None:
        return None
    if req.item_id:
        item = cat.item(req.item_id)
        return item.product_id if item else None
    return req.product_id


def with_hsn(cat: Catalogue, lines: list[CartLine]) -> list[CartLine]:
    """GST invoices: a line without its own HSN code takes its product's (an add-on, its article's)."""
    by_id = {l.id: l for l in lines if l.id}
    out = []
    for line in lines:
        if line.hsn_code is None:
            source = by_id.get(line.parent_id or "") if line.source == "addon" else line
            product = cat.product(_product_id(cat, source.calc_request) or "") if source else None
            line = line.model_copy(update={"hsn_code": (product.hsn_code if product else "") or ""})
        out.append(line)
    return out


def _gst_record(slab: gst.GstSlab | None, m: Money) -> dict | None:
    """What is stored with a GST invoice: the slab chosen and each tax row as issued."""
    if slab is None:
        return None
    taxes = [TaxLine(name=t.name, rate=t.rate, amount=t.amount).model_dump(mode="json") for t in m.taxes]
    return {"option": slab.key, "taxes": taxes}


FULL = Decimal(100)


def advance_for(body: InvoiceCreate) -> Decimal | None:
    """Percent due before printing: the split chosen, else 100 (pay in full). None on a quotation."""
    if body.document_type == "quotation":
        return None
    return body.advance_pct if body.advance_pct is not None else FULL


def _money(doc_lines: list[CartLine], components, advance_pct: Decimal, payments: list) -> Money:
    subtotals = [line_subtotal(l.quantity, l.unit_price) for l in doc_lines]
    try:
        return compute(subtotals, components, advance_pct, [p.amount for p in payments])
    except Overpaid as exc:
        raise InvoiceError(
            "OVERPAID",
            f"Received {fmt.amount(exc.received)} is more than the payable {fmt.amount(exc.payable)}",
            422,
            {"received": str(exc.received), "payable": str(exc.payable)},
        ) from None


def _business_name(series: str, body: InvoiceCreate) -> str:
    if series == "gst" and body.gst is not None:
        return body.gst.buyer.name
    return body.customer.business_name


def _status(series: str, m: Money) -> str:
    return QUOTATION_STATUS if series == "quotation" else m.status


def document(row, series: str = "non_gst") -> InvoiceDocument:
    record = row.gst or {}
    return InvoiceDocument.model_validate(
        {
            "series": series,
            "bill_no": row.bill_no,
            "invoice_date": row.invoice_date,
            "billing_type": row.billing_type if series == "non_gst" else "without_gst",
            "gst_option": record.get("option"),
            "taxes": record.get("taxes") or [],
            "customer": row.customer,
            "gst": getattr(row, "details", None),
            "lines": row.lines,
            "payments": row.payments,
            "saving_amount": row.saving_amount,
            "advance_pct": row.advance_pct,
            "salesperson": getattr(row, "salesperson", None),
        }
    )


def filename(cfg: InvoiceConfig, series: str, bill_no: int, business: str, status: str) -> str:
    if series == "quotation":
        return fmt.filename(cfg.quotation["filename"], bill_no, business, "")
    template = cfg.gst_invoice["filename"] if series == "gst" else cfg.filename
    return fmt.filename(template, bill_no, business, cfg.status_labels[status])


def _rendered(row, cfg: InvoiceConfig, series: str) -> Rendered:
    doc = document(row, series)
    return Rendered(
        bill_no=row.bill_no, status=row.status, filename=filename(cfg, series, row.bill_no, row.business_name, row.status),
        pdf=render_document(doc, cfg), business_name=row.business_name, doc=doc, money=document_money(doc, cfg),
        series=series,
    )


def _event_detail(row) -> dict:
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


def row_summary(row, series: str = "non_gst") -> dict:
    record = row.gst or {}
    return {
        "series": series,
        "bill_no": row.bill_no,
        "invoice_date": row.invoice_date.isoformat(),
        "business_name": row.business_name,
        "billing_type": row.billing_type,
        "gst_slab": record.get("option") if series == "gst" else None,
        "total": format(row.total, "f"),
        "payable": format(row.payable, "f"),
        "received": format(row.received, "f"),
        "status": row.status,
        "version": row.version,
    }


def row_detail(row, series: str = "non_gst") -> dict:
    return {
        **row_summary(row, series),
        "customer": row.customer,
        "lines": row.lines,
        "payments": row.payments,
        "saving_amount": format(row.saving_amount, "f") if row.saving_amount is not None else None,
        "advance_pct": format(row.advance_pct.normalize(), "f") if row.advance_pct is not None else None,
        "gst_amount": format(row.gst_amount, "f"),
        "gst": row.gst,
        "details": getattr(row, "details", None),
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


# ---------------------------------------------------------------- operations


def next_bill_no(store: Store, cfg: InvoiceConfig, series: str = "non_gst") -> int:
    with store.session() as s:
        return store.next_bill_no(s, series_start(cfg, series), series)


def next_numbers(store: Store, cfg: InvoiceConfig) -> dict[str, int]:
    with store.session() as s:
        return {series: store.next_bill_no(s, series_start(cfg, series), series) for series in NAMES}


def _prepare(cat: Catalogue, cfg: InvoiceConfig, body: InvoiceCreate):
    """Checks, re-pricing and money shared by saved and unsaved documents."""
    series = body.series
    slab = check_request(cfg, body)
    lines = reprice(cat, cfg, body.lines)
    if series == "gst":
        lines = with_hsn(cat, lines)
    payments = [Payment(**p.model_dump(exclude={"recorded_at"})) for p in body.payments]
    m = _money(lines, slab.components if slab else (), advance_for(body) or FULL, payments)
    return series, slab, lines, payments, m


def create_unsaved(cat: Catalogue, cfg: InvoiceConfig, body: InvoiceCreate) -> Rendered:
    """No database: the same checks and PDF as create(), but nothing is stored.

    The server can't count numbers without storage, so the client must send one.
    """
    check_request(cfg, body)
    if body.bill_no is None:
        raise _validation(f"Enter a {'Quote No' if body.series == 'quotation' else 'Bill No'}", field="bill_no")
    series, slab, lines, payments, m = _prepare(cat, cfg, body)
    record = _gst_record(slab, m) or {}
    doc = InvoiceDocument(
        series=series,
        bill_no=body.bill_no,
        invoice_date=body.invoice_date,
        gst_option=record.get("option"),
        taxes=record.get("taxes") or [],
        customer=body.customer,
        gst=body.gst if series == "gst" else None,
        lines=lines,
        payments=payments,
        saving_amount=body.saving_amount if body.saving_amount else None,
        advance_pct=advance_for(body),
    )
    business = _business_name(series, body)
    status = _status(series, m)
    log.info(
        "%s rendered (not stored) no=%s lines=%s total=%s gst_slab=%s gst=%s payable=%s received=%s status=%s",
        series, body.bill_no, len(lines), m.total, slab.key if slab else None, m.gst, m.payable, m.received, status,
    )
    return Rendered(
        bill_no=body.bill_no, status=status, filename=filename(cfg, series, body.bill_no, business, status),
        pdf=render_document(doc, cfg), business_name=business, doc=doc, money=document_money(doc, cfg), series=series,
    )


def create(store: Store, cat: Catalogue, cfg: InvoiceConfig, body: InvoiceCreate) -> Rendered:
    series, slab, lines, _, m = _prepare(cat, cfg, body)
    payments = [_payment_json(p) for p in body.payments]
    row_class = store.row_class(series)
    start = series_start(cfg, series)
    label = "Quote No" if series == "quotation" else "Bill No"

    def new_row(bill_no: int):
        now = utcnow()
        extra = {"details": body.gst.model_dump(mode="json")} if series == "gst" else {}
        return row_class(
            bill_no=bill_no,
            invoice_date=body.invoice_date,
            billing_type=BILLING_TYPES[series],
            business_name=_business_name(series, body),
            customer=body.customer.model_dump(mode="json"),
            lines=[l.model_dump(mode="json") for l in lines],
            payments=payments,
            saving_amount=body.saving_amount if body.saving_amount else None,
            total=m.total,
            gst_amount=m.gst,
            gst=_gst_record(slab, m),
            payable=m.payable,
            advance_pct=advance_for(body),
            received=m.received,
            status=_status(series, m),
            version=1,
            created_at=now,
            updated_at=now,
            **extra,
        )

    def taken(s) -> InvoiceError:
        return InvoiceError(
            "BILL_NO_TAKEN", f"{label} {body.bill_no} is already used", 409,
            {"next_bill_no": store.next_bill_no(s, start, series), "series": series},
        )

    with _write_lock:
        row = None
        for _ in range(BILL_NO_RETRIES + 1):
            with store.session() as s:
                if body.bill_no is not None:
                    if store.exists(s, body.bill_no, series):
                        raise taken(s)
                    bill_no = body.bill_no
                else:
                    bill_no = store.next_bill_no(s, start, series)
                candidate = new_row(bill_no)
                s.add(candidate)
                store.mark_issued(s, series, bill_no)
                store.add_event(s, bill_no, "created", _event_detail(candidate), series)
                try:
                    s.commit()
                    row = candidate
                    break
                except IntegrityError:
                    s.rollback()
                    if body.bill_no is not None:
                        raise taken(s) from None
        if row is None:
            raise InvoiceError("BILL_NO_CONFLICT", f"Couldn't assign a {label} - try again", 409)

    log.info(
        "%s created no=%s lines=%s total=%s payable=%s received=%s status=%s",
        series, row.bill_no, len(lines), row.total, row.payable, row.received, row.status,
    )
    return _rendered(row, cfg, series)


def add_payment(store: Store, cfg: InvoiceConfig, bill_no: int, payment: PaymentCreate, series: str = "non_gst") -> Rendered:
    if series == "quotation":
        raise _validation("A quotation has no payments", field="series")
    with _write_lock, store.session() as s:
        row = store.get(s, bill_no, series)
        if row is None:
            raise _not_found(series, bill_no)
        if row.status == "paid":
            raise InvoiceError("ALREADY_PAID", f"{NAMES[series]} {bill_no} is already paid in full", 422)
        doc = document(row, series)
        payments = [*doc.payments, Payment(**payment.model_dump())]
        m = _money(doc.lines, doc_components(doc), doc_advance_pct(doc, cfg), payments)
        row.payments = [*row.payments, _payment_json(payment)]
        row.received = m.received
        row.status = m.status
        row.version += 1
        row.updated_at = utcnow()
        store.add_event(s, bill_no, "payment_added", _event_detail(row), series)
        s.commit()
    log.info("%s payment no=%s received=%s status=%s version=%s", series, bill_no, row.received, row.status, row.version)
    return _rendered(row, cfg, series)


def delete(store: Store, bill_no: int, series: str = "non_gst") -> dict:
    """Removes the document and its events: nothing about it stays in the database.

    Its number is not handed out again (document_counters keeps the highest issued).
    """
    with _write_lock, store.session() as s:
        row = store.get(s, bill_no, series)
        if row is None:
            raise _not_found(series, bill_no)
        store.delete(s, row, series)
        s.commit()
    log.info("%s deleted no=%s", series, bill_no)
    return {"deleted": bill_no, "series": series}


def download(store: Store, cfg: InvoiceConfig, bill_no: int, series: str = "non_gst") -> Rendered:
    with store.session() as s:
        row = store.get(s, bill_no, series)
        if row is None:
            raise _not_found(series, bill_no)
        store.add_event(s, bill_no, "downloaded", {"version": row.version}, series)
        s.commit()
    return _rendered(row, cfg, series)


def detail(store: Store, bill_no: int, series: str = "non_gst") -> dict:
    with store.session() as s:
        row = store.get(s, bill_no, series)
        if row is None:
            raise _not_found(series, bill_no)
        return row_detail(row, series)


def listing(store: Store, q: str | None, status: str | None, limit: int, offset: int, series: str = "non_gst") -> dict:
    with store.session() as s:
        rows, total = store.search(s, q, status, limit, offset, series)
        return {
            "series": series,
            "invoices": [row_summary(r, series) for r in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }
