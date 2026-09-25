"""HTTP routes (BRD section 7)."""
import hmac
import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .catalogue import Catalogue
from .loader import LoaderError, load
from .models import CalculateRequest
from .quote import QuoteError, QuoteInput, calculate
from .settings import Settings, get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("printevr.api")
calc_log = logging.getLogger("printevr.calc")


def error(code: str, message: str, status: int, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"status": "error", "error": {"code": code, "message": message, "details": details or {}}},
    )


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


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = time.monotonic()
        with self._lock:
            q = self.hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    store = DataStore(settings)
    limiter = RateLimiter(settings.rate_limit_per_minute)
    try:
        store.reload()
    except LoaderError as exc:
        store.load_error = str(exc)
        log.error("PRICE DATA NOT LOADED: %s", exc)

    app = FastAPI(title="Printevr Pricing API", version="2.1")
    app.state.store = store
    app.state.limiter = limiter
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-Admin-Token"],
    )

    @app.exception_handler(RequestValidationError)
    async def on_validation_error(_: Request, exc: RequestValidationError):
        problems = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]} for e in exc.errors()
        ]
        return error("VALIDATION_ERROR", problems[0]["message"] if problems else "Invalid request", 422, {"errors": problems})

    def catalogue_or_503() -> Catalogue | JSONResponse:
        if store.catalogue is None:
            return error("DATA_NOT_LOADED", "Price data failed to load", 503, {"reason": store.load_error})
        return store.catalogue

    @app.get("/api/health")
    def health():
        cat = store.catalogue
        return {
            "status": "ok" if cat else "error",
            "data_loaded_at": cat.loaded_at.isoformat() if cat else None,
            "source_file": cat.source_file if cat else None,
            "load_error": store.load_error,
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
        if not limiter.allow(client_ip(request, settings.trust_proxy_headers)):
            return error("RATE_LIMITED", "Too many quotes - try again in a minute", 429)
        cat = catalogue_or_503()
        if isinstance(cat, JSONResponse):
            return cat
        started = time.perf_counter()
        try:
            result = calculate(
                cat,
                QuoteInput(
                    product_id=body.product_id,
                    item_id=body.item_id,
                    options=body.options,
                    custom_dimensions=body.custom_dimensions.model_dump() if body.custom_dimensions else None,
                    quantity=body.quantity,
                    addons=body.addons,
                    billing_type=body.billing_type,
                ),
            )
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
        token = request.headers.get("X-Admin-Token", "")
        if not settings.admin_token:
            return error("FORBIDDEN", "Reload is disabled: ADMIN_TOKEN is not set", 403)
        if not hmac.compare_digest(token.encode(), settings.admin_token.encode()):
            return error("UNAUTHORIZED", "Missing or wrong X-Admin-Token", 401)
        try:
            cat = store.reload()
        except LoaderError as exc:
            log.error("Reload failed, keeping last good data: %s", exc)
            return error("RELOAD_FAILED", str(exc), 422, {"kept_data_from": _loaded_at(store)})
        return {"status": "ok", "data_loaded_at": cat.loaded_at.isoformat(), "items": len(cat.items)}

    return app


def client_ip(request: Request, trust_proxy_headers: bool) -> str:
    if trust_proxy_headers:
        forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "")
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


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
