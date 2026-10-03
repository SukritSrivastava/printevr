"""Invoice HTTP routes (BRD-cart-invoice 8.4), mounted under /api.

Every /api/invoices route needs `Authorization: Bearer <staff token>`. Without
STAFF_PASSCODE (or SECRET_KEY, or the invoice config) they answer 503
INVOICING_DISABLED and the calculator carries on as before.

Quotations, Non-GST invoices and GST invoices share these routes; the ones that read a stored
document take `?series=quotation|non_gst|gst` (default non_gst, the original invoices).

Without DATABASE_URL (the default on Vercel) invoices aren't stored: POST /api/invoices
still renders and returns the PDF, the client supplies the Bill No, and the routes that
read stored invoices answer 503 STORAGE_DISABLED.
"""
import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from ..catalogue import Catalogue
from ..settings import Settings
from . import auth, gst, mailer, service
from .config import InvoiceConfig
from .models import InvoiceCreate, PaymentCreate, StaffLogin
from .service import InvoiceError, Rendered
from .store import Store

log = logging.getLogger("printevr.invoice")

EXPOSED_HEADERS = [
    "Content-Disposition", "X-Bill-No", "X-Invoice-Status", "X-Document-Series", "X-Job-Id", "X-Designer", "X-Assigned-At",
]
LOGIN_ATTEMPTS_PER_MINUTE = 5


def pdf_response(r: Rendered, status: int = 200) -> Response:
    headers = {
        "Content-Disposition": f"attachment; filename=\"{r.filename}\"; filename*=UTF-8''{quote(r.filename)}",
        "X-Bill-No": str(r.bill_no),
        "X-Invoice-Status": r.status,
        "X-Document-Series": r.series,
        "Cache-Control": "no-store",
    }
    if r.job:
        # The designer goes in headers only, never on the PDF. Names are percent-encoded (UTF-8).
        headers["X-Job-Id"] = str(r.job["id"])
        headers["X-Designer"] = quote(r.job["designer_name"] or "")
        headers["X-Assigned-At"] = r.job["assigned_at"]
    return Response(content=r.pdf, status_code=status, media_type="application/pdf", headers=headers)


def create_router(
    settings: Settings,
    invoice_cfg: InvoiceConfig | None,
    catalogue: Callable[[], Catalogue | None],
    error: Callable[..., JSONResponse],
    client_ip: Callable[[Request], str],
    login_limiter,
) -> tuple[APIRouter, dict]:
    """The router, plus its state dict ({"store": Store | None}; tests reach the database through it)."""
    router = APIRouter(prefix="/api")
    state: dict = {"store": None}
    Series = Literal["non_gst", "gst", "quotation"]

    def slab_settings() -> dict:
        """The GST slabs (grouped for the dropdown) and the GST invoice's field defaults."""
        if invoice_cfg is None:
            return {"gst_slab_groups": [], "seller_state_code": "", "gst_field_defaults": {}}
        return {
            "gst_slab_groups": gst.public_slabs(list(invoice_cfg.gst_slab_groups), invoice_cfg.gst_slabs),
            "seller_state_code": invoice_cfg.seller_state_code,
            "gst_field_defaults": dict(invoice_cfg.gst_invoice["field_defaults"]),
        }

    def hsn_codes() -> dict[str, str]:
        """Each product's HSN code from config/products.yaml (blank until filled in)."""
        cat = catalogue()
        return {p.id: p.hsn_code for p in cat.products.values()} if cat else {}
    lock = threading.Lock()

    def disabled_reason() -> str | None:
        # Without STAFF_PASSCODE there is no separate staff step: the site password alone
        # protects invoicing, so it must be set (invoicing is never open to anyone).
        if not settings.staff_passcode and not settings.site_password:
            return "Invoicing isn't set up on this server (SITE_PASSWORD or STAFF_PASSCODE)"
        if settings.staff_passcode and not settings.secret_key:
            return "Invoicing isn't set up on this server (SECRET_KEY)"
        if invoice_cfg is None:
            return "Invoicing isn't set up on this server (config/invoice.yaml failed to load)"
        return None

    def get_store() -> Store | None:
        if not settings.database_url:
            return None
        with lock:
            if state["store"] is None:
                state["store"] = Store(settings.database_url)
            return state["store"]

    def guard(request: Request) -> JSONResponse | None:
        reason = disabled_reason()
        if reason:
            return error("INVOICING_DISABLED", reason, 503)
        if not settings.staff_passcode:
            return None  # the site-password middleware already checked the session
        token = auth.bearer(request.headers.get("authorization"))
        if not auth.valid(token, settings.secret_key, settings.staff_passcode):
            return error("AUTH_REQUIRED", "Enter the staff passcode to continue", 401)
        return None

    def run(request: Request, action: Callable[[Store | None], object], needs_store: bool = True):
        blocked = guard(request)
        if blocked:
            return blocked
        store = get_store()
        if needs_store and store is None:
            return error("STORAGE_DISABLED", "Invoices aren't saved on this server", 503)
        try:
            return action(store)
        except InvoiceError as exc:
            log.info("invoice error code=%s", exc.code)
            return error(exc.code, exc.message, exc.http_status, exc.details)

    @router.post("/staff/login")
    def staff_login(body: StaffLogin, request: Request):
        reason = disabled_reason()
        if reason:
            return error("INVOICING_DISABLED", reason, 503)
        if not settings.staff_passcode:
            return error("NO_STAFF_PASSCODE", "This server has no staff passcode; the site password is enough", 404)
        if not login_limiter.allow(client_ip(request)):
            return error("RATE_LIMITED", "Too many attempts - wait a minute and try again", 429)
        if not auth.passcode_matches(body.passcode, settings.staff_passcode):
            log.warning("Failed staff login from %s", client_ip(request))
            return error("BAD_PASSCODE", "That passcode isn't right", 401)
        token, expires = auth.issue(settings.secret_key, settings.staff_passcode)
        return {"token": token, "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat()}

    @router.get("/invoice-settings")
    def invoice_settings():
        """Open to the site (no staff token): whether invoicing is on, whether invoices are
        stored, and the money rules for the cart's summary box."""
        reason = disabled_reason()
        return {
            "enabled": reason is None,
            "storage": reason is None and bool(settings.database_url),
            # false: no separate staff passcode; the site password covers invoicing
            "staff_passcode": bool(settings.staff_passcode),
            **slab_settings(),
            "hsn_codes": hsn_codes(),
            "advance_pct": str(invoice_cfg.advance_pct) if invoice_cfg else None,
            # false: printed invoices carry no payment details, so the cart hides the inputs
            # that only fed them (GST "Payment Terms", the split payment).
            "print_payment_details": invoice_cfg.print_payment_details if invoice_cfg else True,
        }

    @router.get("/invoices/next-bill-no")
    def next_bill_no(request: Request):
        # Each series' next number (next_bill_no stays the Non-GST one). The money rules ride
        # along so the cart's summary box uses the same numbers as the PDF.
        def action(store: Store):
            numbers = service.next_numbers(store, invoice_cfg)
            return {
                "next_bill_no": numbers["non_gst"],
                "next": numbers,
                **slab_settings(),
                "advance_pct": str(invoice_cfg.advance_pct),
            }

        return run(request, action)

    @router.post("/invoices")
    def create_invoice(body: InvoiceCreate, request: Request):
        def action(store: Store | None):
            cat = catalogue()
            if cat is None:
                return error("DATA_NOT_LOADED", "Price data failed to load", 503)
            if store is None:
                rendered = service.create_unsaved(cat, invoice_cfg, body)
            else:
                rendered = service.create(store, cat, invoice_cfg, body)
            mailer.send(settings, invoice_cfg, rendered, "new")
            return pdf_response(rendered, 201)

        return run(request, action, needs_store=False)

    @router.get("/invoices")
    def list_invoices(
        request: Request,
        q: str | None = Query(default=None, max_length=60),
        status: Literal["unpaid", "part_paid", "paid", "issued"] | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        series: Series = "non_gst",
    ):
        return run(request, lambda store: service.listing(store, q, status, limit, offset, series))

    @router.get("/invoices/{bill_no}")
    def get_invoice(bill_no: int, request: Request, series: Series = "non_gst"):
        return run(request, lambda store: service.detail(store, bill_no, series))

    @router.get("/invoices/{bill_no}/pdf")
    def get_pdf(bill_no: int, request: Request, series: Series = "non_gst"):
        return run(request, lambda store: pdf_response(service.download(store, invoice_cfg, bill_no, series)))

    @router.post("/invoices/{bill_no}/payments")
    def add_payment(bill_no: int, body: PaymentCreate, request: Request, series: Series = "non_gst"):
        def action(store: Store):
            rendered = service.add_payment(store, invoice_cfg, bill_no, body, series)
            mailer.send(settings, invoice_cfg, rendered, "payment")
            return pdf_response(rendered)

        return run(request, action)

    @router.delete("/invoices/{bill_no}")
    def delete_invoice(bill_no: int, request: Request, series: Series = "non_gst"):
        return run(request, lambda store: service.delete(store, bill_no, series))

    state["disabled_reason"] = disabled_reason
    state["guard"] = guard
    state["get_store"] = get_store
    return router, state
