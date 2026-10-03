"""Production tab HTTP routes, mounted under /api/production.

Same protection as the Invoices and Designer Assignment pages: the site password, then the
staff passcode. They need the database: without DATABASE_URL they answer 503
STORAGE_DISABLED, and before migration 0005 has run, 503 PRODUCTION_NOT_SET_UP.
"""
from typing import Callable, Literal

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError

from ..invoice.store import SchemaNotReady
from . import service
from .service import ProductionError

PATHS = ("/api/production",)


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmployeeCreate(_Body):
    name: str = Field(max_length=200)


class JobCreate(_Body):
    series: Literal["non_gst", "gst"] = "non_gst"
    bill_no: int = Field(ge=1, strict=True)
    employee_id: int | None = None


class JobUpdate(_Body):
    employee_id: int | None = None


class StageUpdate(_Body):
    vendor_name: str | None = Field(default=None, max_length=500)
    completed: bool | None = Field(default=None, strict=True)
    sent_to_vendor: bool | None = Field(default=None, strict=True)
    received: bool | None = Field(default=None, strict=True)


def create_router(
    get_store: Callable, error: Callable[..., JSONResponse], storage_error: Callable[[Exception], JSONResponse]
) -> APIRouter:
    router = APIRouter(prefix="/api/production")
    ready = {"tables": False}

    def run(action: Callable):
        try:
            store = get_store()
            if store is None:
                return error("STORAGE_DISABLED", "Production jobs aren't saved on this server", 503)
            if not ready["tables"]:
                ready["tables"] = service.tables_ready(store.engine)
            if not ready["tables"]:
                return error(
                    "PRODUCTION_NOT_SET_UP", "The production tables aren't in the database yet: run the migrations", 503
                )
            with store.session() as s:
                return action(s)
        except ProductionError as exc:
            return error(exc.code, exc.message, exc.http_status, exc.details)
        except (SchemaNotReady, SQLAlchemyError) as exc:
            return storage_error(exc)

    @router.get("/employees")
    def get_employees():
        return run(lambda s: {"employees": service.list_employees(s)})

    @router.post("/employees", status_code=201)
    def post_employee(body: EmployeeCreate):
        return run(lambda s: service.add_employee(s, body.name))

    @router.get("/jobs")
    def get_jobs():
        return run(service.list_jobs)

    @router.post("/jobs", status_code=201)
    def post_job(body: JobCreate):
        return run(lambda s: service.add_job(s, body.series, body.bill_no, body.employee_id))

    @router.patch("/jobs/{job_id}")
    def patch_job(job_id: int, body: JobUpdate):
        return run(lambda s: service.update_job(s, job_id, body.model_dump(include=body.model_fields_set)))

    @router.patch("/jobs/{job_id}/products/{line_no}/stages/{stage}")
    def patch_product_stage(job_id: int, line_no: int, stage: int, body: StageUpdate):
        changes = body.model_dump(include=body.model_fields_set)
        return run(lambda s: service.update_product_stage(s, job_id, line_no, stage, changes))

    @router.delete("/jobs/{job_id}")
    def remove_job(job_id: int):
        return run(lambda s: service.delete_job(s, job_id))

    return router
