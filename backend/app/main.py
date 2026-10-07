"""HTTP routes (BRD section 7).

Public responses carry no exception text, tracebacks, file paths or environment details:
/api/health says only ok/error, and the details (load errors, why invoicing is off, schema
and rate-limit state) are on GET /api/admin/status behind X-Admin-Token, and in the log.
"""
import hmac
import ipaddress
import json
import logging
import threading
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from . import auth, migrations
from .audit import describe as audit_describe
from .audit import service as audit_service
from .invoice import auth as staff_auth
from .team import auth as team_auth
from .catalogue import Catalogue
from .designers.routes import PATHS as DESIGNER_PATHS
from .designers.routes import create_router as designer_router
from .errors import error, install_handlers
from .loader import LoaderError, load
from .models import CalculateRequest, LoginRequest
from .production.routes import PATHS as PRODUCTION_PATHS
from .production.routes import create_router as production_router
from .invoice import config as invoice_config
from .invoice.from_quote import quote_with_drafts
from .invoice.store import SchemaNotReady
from .invoice.routes import EXPOSED_HEADERS, LOGIN_ATTEMPTS_PER_MINUTE as STAFF_LOGINS_PER_MINUTE
from .invoice.routes import create_router as invoice_router
from .quote import QuoteError
from .ratelimit import DatabaseRateLimiter, MemoryRateLimiter
from .settings import Settings, get_settings
from .team.routes import PATHS as TEAM_PATHS
from .team.routes import create_router as team_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("printevr.api")
calc_log = logging.getLogger("printevr.calc")

LOGIN_ATTEMPTS_PER_MINUTE = 10
DATA_NOT_LOADED_MESSAGE = "The price sheet failed to load. The operator can find the reason in the server log."
AUTH_NOT_CONFIGURED_MESSAGE = "Sign-in isn't set up on this server yet"


class DataStore:
    """Holds the last good catalogue; a failed reload keeps it."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.catalogue: Catalogue | None = None
        self.load_error: str | None = None
        self._lock = threading.Lock()

    def reload(self) -> Catalogue:
        with self._lock:
            started = time.perf_counter()
            catalogue = load(self.settings.data_file, self.settings.config_file)
            self.catalogue = catalogue
            self.load_error = None
            log.info("Catalogue loaded in %.0f ms", (time.perf_counter() - started) * 1000)
            return catalogue


def shared_limits(settings: Settings) -> bool:
    """Whether login limits are counted in the database (shared by every instance)."""
    if settings.rate_limit_backend == "auto":
        url = settings.database_url or ""
        return url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://"))
    return settings.rate_limit_backend == "database" and bool(settings.database_url)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = DataStore(settings)
    limiter = MemoryRateLimiter(settings.rate_limit_per_minute, settings.rate_limit_max_keys)
    try:
        store.reload()
    except LoaderError as exc:
        store.load_error = str(exc)
        log.error("PRICE DATA NOT LOADED: %s", exc)

    # Invoice settings; the calculator keeps working if this file is broken.
    try:
        invoice_cfg = invoice_config.load(settings.invoice_config_file)
        unit_plurals = invoice_cfg.unit_plurals
    except invoice_config.InvoiceConfigError as exc:
        invoice_cfg, unit_plurals = None, {}
        log.error("INVOICE CONFIG NOT LOADED: %s", exc)

    app = FastAPI(title="Printevr Pricing API", version="2.1")
    install_handlers(app)
    app.state.store = store
    app.state.limiter = limiter
    app.state.limits_shared = shared_limits(settings)

    def limits_engine():
        """The invoice database's engine for the shared login limits (None: count in memory).
        Errors propagate: DatabaseRateLimiter logs them and falls back to memory."""
        db = app.state.invoices["get_store"]()
        return db.engine if db is not None else None

    def login_limiter(scope: str, per_minute: int):
        memory = MemoryRateLimiter(per_minute, settings.rate_limit_max_keys)
        if not app.state.limits_shared:
            return memory
        return DatabaseRateLimiter(scope, per_minute, limits_engine, fallback=memory)

    site_login_limiter = login_limiter("site_login", LOGIN_ATTEMPTS_PER_MINUTE)

    def ip(request: Request) -> str:
        return client_ip(request, settings)

    def signed_in(request: Request) -> bool:
        if settings.site_password is None:
            return not settings.require_password
        return auth.token_valid(request.cookies.get(auth.COOKIE_NAME), settings.site_password, settings.session_secret)

    @app.middleware("http")
    async def require_session(request: Request, call_next):
        path = request.url.path
        # /api/admin/* has its own token; the login flow and health check are open.
        if not path.startswith("/api/") or path in auth.PUBLIC_PATHS or path.startswith("/api/admin/"):
            return await call_next(request)
        if settings.site_password is None and settings.require_password:
            return error("AUTH_NOT_CONFIGURED", AUTH_NOT_CONFIGURED_MESSAGE, 503)
        if not signed_in(request):
            return error("UNAUTHENTICATED", "Enter the password to continue", 401)
        return await call_next(request)

    def https(request: Request) -> bool:
        if settings.trust_proxy_headers and request.headers.get("x-forwarded-proto"):
            return request.headers["x-forwarded-proto"].split(",")[0].strip() == "https"
        return request.url.scheme == "https"

    @app.get("/api/session")
    def session(request: Request):
        return {
            "authenticated": signed_in(request),
            "password_required": settings.site_password is not None or settings.require_password,
        }

    @app.post("/api/login")
    def login(body: LoginRequest, request: Request):
        if settings.site_password is None:
            if settings.require_password:
                return error("AUTH_NOT_CONFIGURED", AUTH_NOT_CONFIGURED_MESSAGE, 503)
            return {"status": "ok"}
        if not site_login_limiter.allow(ip(request)):
            return error("RATE_LIMITED", "Too many attempts - wait a minute and try again", 429)
        if not auth.password_matches(body.password, settings.site_password):
            log.warning("Failed login from %s", ip(request))
            return error("WRONG_PASSWORD", "That password isn't right", 401)
        response = JSONResponse({"status": "ok"})
        response.set_cookie(
            auth.COOKIE_NAME,
            auth.issue_token(settings.site_password, settings.session_secret, settings.session_days),
            max_age=settings.session_days * 86400,
            httponly=True,
            secure=https(request),
            samesite="lax",
            path="/",
        )
        return response

    @app.post("/api/logout")
    def logout():
        response = JSONResponse({"status": "ok"})
        response.delete_cookie(auth.COOKIE_NAME, path="/")
        return response
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "X-Admin-Token", "Authorization", "X-Team-Admin"],
        expose_headers=EXPOSED_HEADERS,
    )

    staff_login_limiter = login_limiter("staff_login", STAFF_LOGINS_PER_MINUTE)
    app.state.login_limiters = {"site": site_login_limiter, "staff": staff_login_limiter}
    router, app.state.invoices = invoice_router(
        settings,
        invoice_cfg,
        catalogue=lambda: store.catalogue,
        error=error,
        client_ip=ip,
        login_limiter=staff_login_limiter,
    )
    app.include_router(router)
    app.include_router(designer_router(app.state.invoices["get_store"], error, app.state.invoices["storage_error"]))
    app.include_router(production_router(app.state.invoices["get_store"], error, app.state.invoices["storage_error"]))
    team_admin_limiter = login_limiter("team_admin_login", STAFF_LOGINS_PER_MINUTE)
    app.state.login_limiters["team_admin"] = team_admin_limiter
    app.include_router(
        team_router(
            settings,
            app.state.invoices["get_store"],
            error,
            app.state.invoices["storage_error"],
            client_ip=ip,
            login_limiter=team_admin_limiter,
        )
    )
    if settings.site_password is None and settings.require_password:
        log.error("SITE_PASSWORD is not set: every protected route answers 503 AUTH_NOT_CONFIGURED")

    @app.middleware("http")
    async def invoicing_switch(request: Request, call_next):
        # Switched off (503) and staff token (401) are checked before body validation, so
        # neither a disabled server nor a missing token ever answers with field errors.
        path = request.url.path
        if request.method != "OPTIONS":
            if path == "/api/staff/login":
                reason = app.state.invoices["disabled_reason"]()
                if reason:
                    return error("INVOICING_DISABLED", reason, 503)
            elif path.startswith(("/api/invoices", *DESIGNER_PATHS, *PRODUCTION_PATHS, *TEAM_PATHS)):
                blocked = app.state.invoices["guard"](request)
                if blocked:
                    return blocked
        return await call_next(request)

    audit_ready = {"tables": False}

    def write_audit(request: Request, raw: bytes, status: int, headers: dict) -> None:
        """Activity log (Logs tab): one row per change that succeeded. Never fails the request."""
        try:
            store = app.state.invoices["get_store"]()
            if store is None:
                return
            if not audit_ready["tables"]:
                audit_ready["tables"] = audit_service.tables_ready(store.engine)
                if not audit_ready["tables"]:
                    return
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = None
            admin = bool(settings.admin_passcode and settings.secret_key) and team_auth.valid(
                request.headers.get(team_auth.HEADER), settings.secret_key, settings.admin_passcode
            )
            staff = bool(settings.staff_passcode and settings.secret_key) and staff_auth.valid(
                staff_auth.bearer(request.headers.get("authorization")), settings.secret_key, settings.staff_passcode
            )
            with store.session() as s:
                audit_service.record(
                    s,
                    method=request.method,
                    path=request.url.path,
                    query=dict(request.query_params),
                    body=body,
                    status=status,
                    headers=headers,
                    actor_role="admin" if admin else "staff" if staff else "site",
                    ip=ip(request),
                    user_agent=request.headers.get("user-agent"),
                )
        except Exception:
            log.exception("activity log: entry for %s %s not written", request.method, request.url.path)

    @app.middleware("http")
    async def activity_log(request: Request, call_next):
        if not audit_describe.logged(request.method, request.url.path):
            return await call_next(request)
        raw = await request.body()
        response = await call_next(request)
        if response.status_code < 400:
            await run_in_threadpool(write_audit, request, raw, response.status_code, dict(response.headers))
        return response

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_: Request, exc: RequestValidationError):
        problems = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()
        ]
        return error("VALIDATION_ERROR", problems[0]["message"] if problems else "Invalid request", 422, {"errors": problems})

    def catalogue_or_503() -> Catalogue | JSONResponse:
        if store.catalogue is None:
            return error("DATA_NOT_LOADED", DATA_NOT_LOADED_MESSAGE, 503)
        return store.catalogue

    def admin_check(request: Request) -> JSONResponse | None:
        token = request.headers.get("X-Admin-Token", "")
        if not settings.admin_token:
            return error("FORBIDDEN", "This is turned off on this server", 403)
        if not hmac.compare_digest(token.encode(), settings.admin_token.encode()):
            return error("UNAUTHORIZED", "Missing or wrong X-Admin-Token", 401)
        return None

    @app.get("/api/health")
    def health():
        """Public, for uptime checks: only whether the price data is loaded."""
        return {"status": "ok" if store.catalogue else "error"}

    def storage_status() -> dict:
        if not settings.database_url:
            return {"configured": False}
        try:
            db = app.state.invoices["get_store"]()
            return {"configured": True, "ready": True, "pending_migrations": migrations.pending(db.engine)}
        except SchemaNotReady as exc:
            return {"configured": True, "ready": False, "missing": exc.missing}
        except Exception as exc:  # operator-only, but still never the connection string
            return {"configured": True, "ready": False, "error": type(exc).__name__}

    @app.get("/api/admin/status")
    def admin_status(request: Request):
        """Operator only (X-Admin-Token): what /api/health used to show, and why parts are off."""
        denied = admin_check(request)
        if denied:
            return denied
        cat = store.catalogue
        return {
            "status": "ok" if cat else "error",
            "data_loaded_at": cat.loaded_at.isoformat() if cat else None,
            "source_file": cat.source_file if cat else None,
            "load_error": store.load_error,
            "invoice_config_loaded": invoice_cfg is not None,
            "invoicing_disabled": app.state.invoices["disabled_cause"](),
            # Team tab admin (employee list, attendance corrections); None = available.
            "team_admin_disabled": (
                None
                if settings.admin_passcode and settings.secret_key
                else "ADMIN_PASSCODE is not set" if not settings.admin_passcode else "SECRET_KEY is not set"
            ),
            "storage": storage_status(),
            "rate_limits": {"login": "database" if app.state.limits_shared else "memory", "calculate": "memory"},
            "counts": {
                "categories": len(cat.categories),
                "products": len(cat.products),
                "items": len(cat.items),
                "tier_rows": cat.tier_rows,
                "sample_charges": cat.sample_rows,
                "open_flags": cat.open_flag_count,
                "loader_warnings": len(cat.warnings),
            }
            if cat
            else None,
        }

    @app.get("/api/catalog")
    def catalog():
        cat = catalogue_or_503()
        if isinstance(cat, JSONResponse):
            return cat
        return build_catalog(cat)

    @app.post("/api/calculate")
    def calculate_route(body: CalculateRequest, request: Request):
        if not limiter.allow(ip(request)):
            return error("RATE_LIMITED", "Too many quotes - try again in a minute", 429)
        cat = catalogue_or_503()
        if isinstance(cat, JSONResponse):
            return cat
        started = time.perf_counter()
        try:
            result = quote_with_drafts(cat, body, unit_plurals)
        except QuoteError as exc:
            calc_log.info("item=%s qty=%s error=%s", body.item_id or body.product_id, body.quantity, exc.code)
            return error(exc.code, exc.message, exc.http_status, exc.details)
        data = result["data"]
        calc_log.info(
            "item=%s qty=%s status=%s total=%s warnings=%s ms=%.1f",
            data["product"].get("item_id") or data["product"]["id"],
            body.quantity,
            result["status"],
            data.get("totals", {}).get("grand_total", "-"),
            ",".join(w["code"] for w in data.get("warnings", [])) or "-",
            (time.perf_counter() - started) * 1000,
        )
        return result

    @app.post("/api/admin/reload")
    def admin_reload(request: Request):
        denied = admin_check(request)
        if denied:
            return denied
        try:
            cat = store.reload()
        except LoaderError as exc:
            log.error("Reload failed, keeping last good data: %s", exc)
            return error("RELOAD_FAILED", str(exc), 422, {"kept_data_from": _loaded_at(store)})
        return {"status": "ok", "data_loaded_at": cat.loaded_at.isoformat(), "items": len(cat.items)}

    return app


def _peer_trusted(peer: str, trusted: tuple[str, ...]) -> bool:
    if not trusted:
        return True
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for net in trusted:
        try:
            if addr in ipaddress.ip_network(net, strict=False):
                return True
        except ValueError:
            continue
    return False


def client_ip(request: Request, settings: Settings) -> str:
    """The address rate limits key on.

    Forwarded headers are believed only with TRUST_PROXY_HEADERS=1 (on by default on Vercel,
    whose edge overwrites them) and, if TRUSTED_PROXIES is set, only from those peers.
    X-Forwarded-For is read from the right: each trusted proxy appends the address it saw,
    so the entry TRUSTED_PROXY_HOPS from the end is the client and anything further left is
    whatever the client sent. X-Real-IP is used only when there is no X-Forwarded-For.
    """
    peer = request.client.host if request.client else "unknown"
    if not settings.trust_proxy_headers or not _peer_trusted(peer, settings.trusted_proxies):
        return peer
    chain = [p.strip() for h in request.headers.getlist("x-forwarded-for") for p in h.split(",") if p.strip()]
    if chain:
        return chain[-settings.trusted_proxy_hops] if len(chain) >= settings.trusted_proxy_hops else chain[0]
    return request.headers.get("x-real-ip", "").strip() or peer


def _loaded_at(store: DataStore) -> str | None:
    return store.catalogue.loaded_at.isoformat() if store.catalogue else None


def build_catalog(cat: Catalogue) -> dict:
    """Category -> product -> item tree for the dropdowns. Breakpoints only, never prices."""
    categories = []
    for category in cat.categories:
        products = []
        for p in (p for p in cat.products.values() if p.category == category):
            items = [
                {
                    "id": i.id,
                    "size": i.size,
                    "option_1": i.option_1,
                    "option_2": i.option_2,
                    "breakpoints": [{"qty_from": t.qty_from, "label": t.label} for t in i.tiers],
                    "production_time": i.production_time,
                    "has_sample": i.sample_charge is not None,
                }
                for i in p.items
            ]
            first = p.items[0]
            products.append(
                {
                    "id": p.id,
                    "name": p.display_name,
                    "sale_unit": p.sale_unit,
                    "custom_dims": p.custom_dims,
                    "anchor_match": p.anchor_match,
                    "size_label": p.size_label,
                    "option_labels": {
                        key: p.option_labels.get(key, f"Option {key[-1]}")
                        for key in ("option_1", "option_2")
                        if any(i.option(key) for i in p.items)
                    },
                    "yield_factor": p.yield_factor,
                    "micro_uom": p.micro_uom,
                    "micro_unit": p.micro_unit,
                    "micro_approx": p.micro_approx,
                    "min_qty": first.breakpoints[0],
                    "max_qty": p.max_qty,
                    "production_time": first.production_time,
                    "breakpoints": [{"qty_from": t.qty_from, "label": t.label} for t in first.tiers],
                    "addons": [
                        {
                            "id": a.id,
                            "name": a.name,
                            "price": str(a.price) if a.price is not None else None,
                            "basis": a.basis,
                            "from_sheet": a.from_sheet,
                            "percent": str(a.percent) if a.percent is not None else None,
                        }
                        for a in p.addons
                    ],
                    "suggest_more": p.suggest_more,
                    "notes": p.notes,
                    "items": items,
                }
            )
        categories.append({"name": category, "products": products})
    return {
        "loaded_at": cat.loaded_at.isoformat(),
        "show_invoice_billing": cat.show_invoice_billing,
        "categories": categories,
    }


app = create_app()
