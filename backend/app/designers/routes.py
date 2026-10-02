"""Designer Assignment HTTP routes, mounted under /api.

Same protection as the Invoices page: the site password, then the staff passcode (when the
server has one). They need the database: without DATABASE_URL they answer 503
STORAGE_DISABLED, and before the migrations have run, 503 DESIGNERS_NOT_SET_UP.
"""
from typing import Callable

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from . import service
from .service import DesignerError

PATHS = ("/api/designers", "/api/jobs", "/api/workload", "/api/rotation", "/api/vendors")


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DesignerCreate(_Body):
    name: str = Field(max_length=200)


class DesignerUpdate(_Body):
    name: str | None = Field(default=None, max_length=200)
    active: bool | None = None


class JobUpdate(_Body):
    status: int | None = Field(default=None, ge=1, le=4, strict=True)
    vendor_name: str | None = Field(default=None, max_length=500)


def create_router(get_store: Callable, error: Callable[..., JSONResponse]) -> APIRouter:
    router = APIRouter(prefix="/api")

    def run(action: Callable):
        store = get_store()
        if store is None:
            return error("STORAGE_DISABLED", "Jobs aren't saved on this server (no DATABASE_URL)", 503)
        if not store.designers_available():
            return error(
                "DESIGNERS_NOT_SET_UP", "The designer tables aren't in the database yet: run the migrations", 503
            )
        try:
            with store.session() as s:
                return action(s)
        except DesignerError as exc:
            return error(exc.code, exc.message, exc.http_status, exc.details)

    @router.get("/designers")
    def get_designers():
        return run(lambda s: {"designers": service.list_designers(s)})

    @router.post("/designers", status_code=201)
    def post_designer(body: DesignerCreate):
        return run(lambda s: service.add_designer(s, body.name))

    @router.patch("/designers/{designer_id}")
    def patch_designer(designer_id: int, body: DesignerUpdate):
        return run(lambda s: service.update_designer(s, designer_id, body.name, body.active))

    @router.get("/jobs")
    def get_jobs(
        designer: int | None = None,
        status: int | None = Query(default=None, ge=1, le=4),
        pending: bool = False,
        q: str | None = Query(default=None, max_length=60),
        limit: int = Query(default=200, ge=1, le=500),
    ):
        return run(lambda s: service.list_jobs(s, designer, status, pending, q, limit))

    @router.patch("/jobs/{job_id}")
    def patch_job(job_id: int, body: JobUpdate):
        changes = body.model_dump(include=body.model_fields_set)
        if changes.get("status", 0) is None:
            return error("VALIDATION_ERROR", "Status must be 1 to 4", 422, {"field": "status"})
        return run(lambda s: service.update_job(s, job_id, changes))

    @router.get("/jobs/{job_id}/history")
    def get_history(job_id: int):
        return run(lambda s: service.history(s, job_id))

    @router.get("/workload")
    def get_workload():
        return run(service.workload)

    @router.get("/rotation/next")
    def get_next():
        def action(s):
            d = service.peek_next(s)
            return {"designer": service.designer_json(d) if d else None}

        return run(action)

    @router.get("/vendors")
    def get_vendors(q: str | None = Query(default=None, max_length=80)):
        return run(lambda s: {"vendors": service.vendors(s, q)})

    return router
