"""Vercel entry point: serves the FastAPI app in backend/ as a Python function.

vercel.json rewrites /api/* here; FastAPI still sees the original path.

If the app can't even be imported (a missing package, a missing file, a Python version
problem), Vercel would only say FUNCTION_INVOCATION_FAILED. Instead, the fallback below
answers every request with a JSON error naming the exception, and prints the full
traceback to the function logs.
"""
import json
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

try:
    from app.main import app  # noqa: F401
except Exception as exc:  # pragma: no cover - only runs on a broken deployment
    _trace = traceback.format_exc()
    print(f"PRINTEVR API FAILED TO START\n{_trace}", file=sys.stderr, flush=True)
    _body = json.dumps(
        {
            "status": "error",
            "error": {
                "code": "STARTUP_FAILED",
                "message": f"{type(exc).__name__}: {exc}",
                "details": {"python": sys.version.split()[0], "traceback": _trace.splitlines()[-8:]},
            },
        }
    ).encode()

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            while (await receive())["type"] != "lifespan.shutdown":
                await send({"type": "lifespan.startup.complete"})
            await send({"type": "lifespan.shutdown.complete"})
            return
        await send(
            {
                "type": "http.response.start",
                "status": 503,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": _body})
