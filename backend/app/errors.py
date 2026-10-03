"""Error responses that never carry internals.

Every error keeps the shape `{"status": "error", "error": {"code", "message", "details"}}`.
Exception text, tracebacks, file paths and environment details go to the server log only,
under a short `error_id` that the response repeats, so a report from staff ("ref 3f9c1a2b")
finds the log line.
"""
import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("printevr.api")


def error(code: str, message: str, status: int, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"status": "error", "error": {"code": code, "message": message, "details": details or {}}},
    )


def new_error_id() -> str:
    return uuid.uuid4().hex[:12]


def internal_error(
    code: str = "INTERNAL_ERROR",
    message: str = "Something went wrong on the server",
    status: int = 500,
    *,
    context: str = "unhandled error",
    exc: BaseException | None = None,
) -> JSONResponse:
    """Log the exception (default: the one being handled) with its traceback, and answer with
    only an error id."""
    error_id = new_error_id()
    log.error("%s [error_id=%s]", context, error_id, exc_info=exc or True)
    return error(code, f"{message} (ref {error_id})", status, {"error_id": error_id})


def install_handlers(app: FastAPI) -> None:
    """Any exception a route doesn't handle answers a JSON 500 with an error id, never its text."""

    @app.exception_handler(Exception)
    async def on_unhandled(request: Request, exc: Exception):
        return internal_error(context=f"{request.method} {request.url.path}", exc=exc)
