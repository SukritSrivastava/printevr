"""Vercel entry point: serves the FastAPI app in backend/ as a Python function.

vercel.json rewrites /api/* here; FastAPI still sees the original path.

Vercel's builder only treats this file as a function if `app` is assigned at the top
level, so keep the `app = ...` line below un-nested.

If the app can't be imported (a missing package or file, a bad environment variable),
Vercel would only say FUNCTION_INVOCATION_FAILED. Instead, every request gets a 503
STARTUP_FAILED with an error id and no internals, and the full traceback goes to the
function logs under that id. A request carrying the right X-Admin-Token header (the
ADMIN_TOKEN variable) also gets the exception and the end of the traceback in the response.
"""
import hmac
import json
import os
import sys
import traceback
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def _is_operator(scope, admin_token: str) -> bool:
    if not admin_token:
        return False
    for name, value in scope.get("headers") or []:
        if name.lower() == b"x-admin-token":
            return hmac.compare_digest(value, admin_token.encode())
    return False


def _startup_failure(exc: Exception):
    trace = traceback.format_exc()
    error_id = uuid.uuid4().hex[:12]
    print(f"PRINTEVR API FAILED TO START [error_id={error_id}]\n{trace}", file=sys.stderr, flush=True)
    admin_token = os.getenv("ADMIN_TOKEN", "").strip()
    public = {
        "status": "error",
        "error": {
            "code": "STARTUP_FAILED",
            "message": f"The server couldn't start. The operator can find the reason in the function logs (ref {error_id}).",
            "details": {"error_id": error_id},
        },
    }
    operator = json.loads(json.dumps(public))
    operator["error"]["details"].update(
        {"exception": f"{type(exc).__name__}: {exc}", "python": sys.version.split()[0], "traceback": trace.splitlines()[-8:]}
    )
    bodies = {False: json.dumps(public).encode(), True: json.dumps(operator).encode()}
    health = json.dumps({"status": "error"}).encode()

    async def failed_app(scope, receive, send):
        if scope["type"] == "lifespan":
            while (await receive())["type"] != "lifespan.shutdown":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
        if scope.get("path") == "/api/health":
            body = health
        else:
            body = bodies[_is_operator(scope, admin_token)]
        await send(
            {"type": "http.response.start", "status": 503, "headers": [(b"content-type", b"application/json")]}
        )
        await send({"type": "http.response.body", "body": body})

    return failed_app


def _load():
    try:
        from app.main import app as fastapi_app

        return fastapi_app
    except Exception as exc:  # only on a broken deployment
        return _startup_failure(exc)


app = _load()
