"""Invoice HTTP routes (BRD-cart-invoice 8.4), mounted under /api.

Every /api/invoices route needs `Authorization: Bearer <staff token>`. Without
STAFF_PASSCODE (or SECRET_KEY, a database or the invoice config) they answer
503 INVOICING_DISABLED and the calculator carries on as before.
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
from . import auth, service
from .config import InvoiceConfig
from .models import InvoiceCreate, PaymentCreate, StaffLogin
from .service import InvoiceError, Rendered
from .store import Store

log = logging.getLogger("printevr.invoice")

EXPOSED_HEADERS = ["Content-Disposition", "X-Bill-No", "X-Invoice-Status"]
LOGIN_ATTEMPTS_PER_MINUTE = 5


def pdf_response(r: Rendered, status: int = 200) -> Response:
    return Response(
        content=r.pdf,
        status_code=status,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=\"{r.filename}\"; filename*=UTF-8''{quote(r.filename)}",
            "X-Bill-No": str(r.bill_no),
            "X-Invoice-Status": r.status,
            "Cache-Control": "no-store",
        },
    )


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
    lock = threading.Lock()

    def disabled_reason() -> str | None:
        if not settings.staff_passcode:
            return "Invoicing isn't set up on this server (STAFF_PASSCODE)"
        if not settings.secret_key:
            return "Invoicing isn't set up on this server (SECRET_KEY)"
        if not settings.database_url:
            return "Invoicing isn't set up on this server (DATABASE_URL)"
        if invoice_cfg is None:
            return "Invoicing isn't set up on this server (config/invoice.yaml failed to load)"
        return None

    def get_store() -> Store:
        with lock:
            if state["store"] is None:
                state["store"] = Store(settings.database_url)
            return state["store"]

    def guard(request: Request) -> JSONResponse | None:
        reason = disabled_reason()
        if reason:
            return error("INVOICING_DISABLED", reason, 503)
        token = auth.bearer(request.headers.get("authorization"))
        if not auth.valid(token, settings.secret_key, settings.staff_passcode):
            return error("AUTH_REQUIRED", "Enter the staff passcode to continue", 401)
        return None

    def run(request: Request, action: Callable[[Store], object]):
        blocked = guard(request)
        if blocked:
            return blocked
        try:
            return action(get_store())
        except InvoiceError as exc:
            log.info("invoice error code=%s", exc.code)
            return error(exc.code, exc.message, exc.http_status, exc.details)

    @router.post("/staff/login")
    def staff_login(body: StaffLogin, request: Request):
        reason = disabled_reason()
        if reason:
            return error("INVOICING_DISABLED", reason, 503)
        if not login_limiter.allow(client_ip(request)):
            return error("RATE_LIMITED", "Too many attempts - wait a minute and try again", 429)
        if not auth.passcode_matches(body.passcode, settings.staff_passcode):
            log.warning("Failed staff login from %s", client_ip(request))
            return error("BAD_PASSCODE", "That passcode isn't right", 401)
        token, expires = auth.issue(settings.secret_key, settings.staff_passcode)
        return {"token": token, "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat()}

    @router.get("/invoices/next-bill-no")
    def next_bill_no(request: Request):
        # The money rules ride along so the cart's summary box uses the same numbers as the PDF.
        return run(
            request,
            lambda store: {
                "next_bill_no": service.next_bill_no(store, invoice_cfg),
                "gst_rate": str(invoice_cfg.gst_rate),
                "advance_pct": str(invoice_cfg.advance_pct),
            },
        )

    @router.post("/invoices")
    def create_invoice(body: InvoiceCreate, request: Request):
        def action(store: Store):
            cat = catalogue()
            if cat is None:
                return error("DATA_NOT_LOADED", "Price data failed to load", 503)
            return pdf_response(service.create(store, cat, invoice_cfg, body), 201)

        return run(request, action)

    @router.get("/invoices")
    def list_invoices(
        request: Request,
        q: str | None = Query(default=None, max_length=60),
        status: Literal["unpaid", "part_paid", "paid"] | None = None,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        return run(request, lambda store: service.listing(store, q, status, limit, offset))

    @router.get("/invoices/{bill_no}")
    def get_invoice(bill_no: int, request: Request):
        return run(request, lambda store: service.detail(store, bill_no))

    @router.get("/invoices/{bill_no}/pdf")
    def get_pdf(bill_no: int, request: Request):
        return run(request, lambda store: pdf_response(service.download(store, invoice_cfg, bill_no)))

    @router.post("/invoices/{bill_no}/payments")
    def add_payment(bill_no: int, body: PaymentCreate, request: Request):
        return run(request, lambda store: pdf_response(service.add_payment(store, invoice_cfg, bill_no, body)))

    state["disabled_reason"] = disabled_reason
    state["guard"] = guard
    return router, state
