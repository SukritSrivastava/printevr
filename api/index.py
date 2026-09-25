"""Vercel entry point: serves the FastAPI app in backend/ as a Python function.

vercel.json rewrites /api/* here; FastAPI still sees the original path.

Vercel's builder only treats this file as a function if `app` is assigned at the top
level, so keep the `app = ...` line below un-nested.

If the app can't be imported (a missing package or file, a bad environment variable),
Vercel would only say FUNCTION_INVOCATION_FAILED. Instead, every request gets a JSON
error naming the exception, and the full traceback goes to the function logs.
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))


def _startup_failure(exc: Exception):
    trace = traceback.format_exc()
    print(f"PRINTEVR API FAILED TO START\n{trace}", file=sys.stderr, flush=True)
    body = json.dumps(
        {
            "status": "error",
            "error": {
                "code": "STARTUP_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"python": sys.version.split()[0], "traceback": trace.splitlines()[-8:]},
            },
        }
    ).encode()

    async def failed_app(scope, receive, send):
        if scope["type"] == "lifespan":
            while (await receive())["type"] != "lifespan.shutdown":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
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
