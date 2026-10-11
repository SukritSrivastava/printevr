"""Read-only export for the Google Sheets sync: GET /api/export/{section}.

Not behind the site password or the staff passcode: the caller is a Google Apps Script, so it
sends `Authorization: Bearer <EXPORT_SECRET>` instead (compared in constant time; never in the
URL). Without EXPORT_SECRET, or with one shorter than SECRET_MIN, the export is off (503).

Answers {"rows": [...], "nextPage": n | null}, paged with ?page=1&pageSize=500 so a response
stays far below Vercel's 4.5 MB. `logs` also takes ?since=<ISO time> (entries after it only).
Nothing is written: the session is never committed, and on Postgres the transaction is
declared READ ONLY, so a bug here can't change data. GET requests aren't in the activity log.
"""
import hmac
import json
import os
from datetime import datetime
from decimal import Decimal
from typing import Callable

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from ..invoice.config import InvoiceConfig
from ..invoice.store import SchemaNotReady
from . import sections

PATH_PREFIX = "/api/export/"
SECRET_ENV = "EXPORT_SECRET"
SECRET_MIN = 32
PAGE_SIZE_MAX = 1000


def secret() -> str:
    return os.getenv(SECRET_ENV, "").strip()


def authorized(header: str | None, expected: str) -> bool:
    scheme, _, token = (header or "").partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(token.strip().encode(), expected.encode())


def _json(value) -> str:
    """JSON with Decimals as plain numbers, written from their digits (never via float)."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return "{" + ",".join(f"{json.dumps(str(k))}:{_json(v)}" for k, v in value.items()) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_json(v) for v in value) + "]"
    return json.dumps(value, ensure_ascii=False)


def create_router(
    get_store: Callable,
    error: Callable[..., JSONResponse],
    storage_error: Callable[[Exception], JSONResponse],
    invoice_cfg: InvoiceConfig | None,
) -> APIRouter:
    router = APIRouter(prefix="/api/export")

    @router.get("/{section}")
    def export(
        section: str,
        request: Request,
        page: int = Query(1, ge=1, le=1_000_000),
        page_size: int = Query(500, alias="pageSize", ge=1, le=PAGE_SIZE_MAX),
        since: datetime | None = None,
    ):
        expected = secret()
        if len(expected) < SECRET_MIN:
            return error("EXPORT_DISABLED", "The export isn't set up on this server", 503)
        if not authorized(request.headers.get("authorization"), expected):
            return error("UNAUTHENTICATED", "A valid export key is required", 401)
        build = sections.SECTIONS.get(section)
        if build is None:
            return error("NOT_FOUND", f"Unknown section. Use one of: {', '.join(sections.SECTIONS)}", 404)
        if since is not None and section != "logs":
            return error("VALIDATION_ERROR", "since is only accepted for logs", 400, {"field": "since"})
        try:
            store = get_store()
            if store is None:
                return error("STORAGE_DISABLED", "Nothing is saved on this server", 503)
            if not sections.ready(section, store):
                return error("NOT_SET_UP", "This section's tables aren't in the database yet", 503)
            with store.session() as s:
                if not store.is_sqlite:
                    s.execute(text("SET TRANSACTION READ ONLY"))
                rows, more = build(s, invoice_cfg, (page - 1) * page_size, page_size, since)
                s.rollback()
        except (SchemaNotReady, SQLAlchemyError) as exc:
            return storage_error(exc)
        body = _json({"rows": rows, "nextPage": page + 1 if more else None})
        return Response(body, media_type="application/json", headers={"Cache-Control": "no-store"})

    return router
