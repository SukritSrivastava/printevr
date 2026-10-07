"""Team tab HTTP routes, mounted under /api/team: the employee list and attendance.

Same protection as the Invoices, Designers and Production pages (the site password, then the
staff passcode, checked in main.py's middleware). On top of that, changing the employee list
and correcting attendance need the admin passcode (X-Team-Admin, see auth.py). Checking in and
out needs only the staff passcode. Without DATABASE_URL every route answers 503
STORAGE_DISABLED, and before migration 0009 has run, 503 TEAM_NOT_SET_UP.
"""
import logging
from datetime import date, datetime, timezone
from typing import Callable, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from ..invoice.store import SchemaNotReady
from ..settings import Settings
from ..audit import service as audit_service
from . import auth, service
from .models import ROLES
from .service import TeamError

log = logging.getLogger("printevr.team")

PATHS = ("/api/team",)
Role = Literal[tuple(ROLES)]  # type: ignore[valid-type]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminLogin(_Body):
    passcode: str = Field(max_length=200)


class EmployeeCreate(_Body):
    name: str = Field(max_length=200)
    role: Role
    phone: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    joined_on: date | None = None


class EmployeeUpdate(_Body):
    name: str | None = Field(default=None, max_length=200)
    role: Role | None = None
    phone: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)
    joined_on: date | None = None


class CheckBody(_Body):
    employee_id: int = Field(ge=1, strict=True)


class RecordBody(_Body):
    check_in: str = Field(pattern=r"^\d{1,2}:\d{2}$")
    check_out: str | None = Field(default=None, pattern=r"^\d{1,2}:\d{2}$")
    note: str | None = Field(default=None, max_length=500)


def create_router(
    settings: Settings,
    get_store: Callable,
    error: Callable[..., JSONResponse],
    storage_error: Callable[[Exception], JSONResponse],
    client_ip: Callable[[Request], str],
    login_limiter,
) -> APIRouter:
    router = APIRouter(prefix="/api/team")

    def clock() -> datetime:
        return service.now_utc()  # looked up per call, so tests can pin the time
    ready = {"tables": False}

    def admin_configured() -> bool:
        return bool(settings.admin_passcode and settings.secret_key)

    if not admin_configured():
        log.warning("Team admin is off: %s", "ADMIN_PASSCODE is not set" if not settings.admin_passcode else "SECRET_KEY is not set")

    def is_admin(request: Request) -> bool:
        """Who may change the employee list and correct attendance. Role-based login replaces this."""
        if not admin_configured():
            return False
        return auth.valid(request.headers.get(auth.HEADER), settings.secret_key, settings.admin_passcode)

    def admin_block(request: Request) -> JSONResponse | None:
        if not admin_configured():
            return error("ADMIN_NOT_CONFIGURED", "Employee changes need an admin passcode on this server. Ask the operator to set one.", 503)
        if not is_admin(request):
            return error("ADMIN_REQUIRED", "Enter the admin passcode to change this", 403)
        return None

    def run(action: Callable, request: Request | None = None):
        if request is not None:
            blocked = admin_block(request)
            if blocked:
                return blocked
        try:
            store = get_store()
            if store is None:
                return error("STORAGE_DISABLED", "Employees and attendance aren't saved on this server", 503)
            if not ready["tables"]:
                ready["tables"] = service.tables_ready(store.engine)
            if not ready["tables"]:
                return error("TEAM_NOT_SET_UP", "The team tables aren't in the database yet: run the migrations", 503)
            with store.session() as s:
                return action(s)
        except TeamError as exc:
            return error(exc.code, exc.message, exc.http_status, exc.details)
        except (SchemaNotReady, SQLAlchemyError) as exc:
            return storage_error(exc)

    def parse_day(value: str | None, field: str = "date") -> date:
        if value is None:
            return service.ist_day(clock())
        try:
            return date.fromisoformat(value)
        except ValueError:
            raise TeamError("VALIDATION_ERROR", "Dates are YYYY-MM-DD", 422, {"field": field}) from None

    @router.get("/settings")
    def team_settings(request: Request):
        return {
            "roles": [{"value": k, "label": v} for k, v in ROLES.items()],
            "admin_configured": admin_configured(),
            "is_admin": is_admin(request),
            "timezone": "Asia/Kolkata",
        }

    @router.post("/admin/login")
    def admin_login(body: AdminLogin, request: Request):
        if not admin_configured():
            return error("ADMIN_NOT_CONFIGURED", "There is no admin passcode on this server. Ask the operator to set one.", 503)
        if not login_limiter.allow(client_ip(request)):
            return error("RATE_LIMITED", "Too many attempts - wait a minute and try again", 429)
        if not auth.passcode_matches(body.passcode, settings.admin_passcode):
            log.warning("Failed team admin login from %s", client_ip(request))
            return error("BAD_PASSCODE", "That admin passcode isn't right", 401)
        token, expires = auth.issue(settings.secret_key, settings.admin_passcode)
        return {"token": token, "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat()}

    # ---------- employees ----------

    @router.get("/employees")
    def get_employees(include_removed: bool = Query(default=False)):
        return run(lambda s: {"employees": service.list_employees(s, include_removed)})

    @router.post("/employees", status_code=201)
    def post_employee(body: EmployeeCreate, request: Request):
        return run(lambda s: service.add_employee(s, body.model_dump()), request)

    @router.patch("/employees/{employee_id}")
    def patch_employee(employee_id: int, body: EmployeeUpdate, request: Request):
        fields = body.model_dump(exclude_unset=True)
        for key in ("name", "role"):
            if key in fields and fields[key] is None:
                return error("VALIDATION_ERROR", f"{key.title()} can't be blank", 422, {"field": key})
        return run(lambda s: service.update_employee(s, employee_id, fields), request)

    @router.delete("/employees/{employee_id}")
    def remove_employee(employee_id: int, request: Request):
        return run(lambda s: service.set_active(s, employee_id, False), request)

    @router.post("/employees/{employee_id}/restore")
    def restore_employee(employee_id: int, request: Request):
        return run(lambda s: service.set_active(s, employee_id, True), request)

    # ---------- attendance ----------

    @router.get("/attendance")
    def get_day(day: str | None = Query(default=None, alias="date")):
        return run(lambda s: service.day_register(s, parse_day(day), clock()))

    @router.get("/attendance/summary")
    def get_month(month: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}$")):
        def action(s):
            today = service.ist_day(clock())
            year, mon = (int(p) for p in month.split("-")) if month else (today.year, today.month)
            if not 1 <= mon <= 12:
                raise TeamError("VALIDATION_ERROR", "Months are YYYY-MM", 422, {"field": "month"})
            return service.month_summary(s, year, mon, clock())

        return run(action)

    @router.post("/attendance/check-in")
    def post_check_in(body: CheckBody):
        return run(lambda s: service.check_in(s, body.employee_id, clock()))

    @router.post("/attendance/check-out")
    def post_check_out(body: CheckBody):
        return run(lambda s: service.check_out(s, body.employee_id, clock()))

    @router.put("/attendance/{employee_id}/{day}")
    def put_record(employee_id: int, day: str, body: RecordBody, request: Request):
        return run(
            lambda s: service.set_record(
                s, employee_id, parse_day(day), body.check_in, body.check_out, body.note, clock()
            ),
            request,
        )

    @router.delete("/attendance/{employee_id}/{day}")
    def delete_record(employee_id: int, day: str, request: Request):
        def action(s):
            service.delete_record(s, employee_id, parse_day(day))
            return {"status": "deleted"}

        return run(action, request)

    # ---------- activity log (Logs tab, admin only) ----------

    @router.get("/logs")
    def get_logs(
        request: Request,
        day_from: str | None = Query(default=None, alias="from"),
        day_to: str | None = Query(default=None, alias="to"),
        category: str | None = Query(default=None, max_length=20),
        q: str | None = Query(default=None, max_length=100),
        limit: int = Query(default=50, ge=1, le=audit_service.PAGE_MAX),
        offset: int = Query(default=0, ge=0),
    ):
        def action(s):
            if not audit_service.tables_ready(s.get_bind()):
                raise TeamError("LOGS_NOT_SET_UP", "The activity log table isn't in the database yet: run the migrations", 503)
            return audit_service.list_entries(
                s,
                day_from=parse_day(day_from, "from") if day_from else None,
                day_to=parse_day(day_to, "to") if day_to else None,
                category=category or None,
                search=q,
                limit=limit,
                offset=offset,
            )

        return run(action, request)

    return router
