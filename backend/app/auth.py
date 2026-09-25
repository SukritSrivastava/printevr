"""Site password: one shared password, exchanged for a signed session cookie.

The token is "<expiry>.<hmac>" signed with a key derived from the password (and
SESSION_SECRET, if set), so changing the password signs everyone out. No server-side
session store is needed, which suits serverless hosting.
"""
import hashlib
import hmac
import time

COOKIE_NAME = "printevr_session"

# Paths that work without a session: the login flow itself, and the uptime check.
PUBLIC_PATHS = {"/api/login", "/api/logout", "/api/session", "/api/health"}


def _key(password: str, secret: str) -> bytes:
    return hashlib.sha256(f"printevr-session\0{secret}\0{password}".encode()).digest()


def password_matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


def issue_token(password: str, secret: str, days: int, now: float | None = None) -> str:
    expires = int((now if now is not None else time.time()) + days * 86400)
    sig = hmac.new(_key(password, secret), str(expires).encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}"


def token_valid(token: str | None, password: str, secret: str, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, sig = token.split(".", 1)
    if not expires.isdigit():
        return False
    expected = hmac.new(_key(password, secret), expires.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    return int(expires) > (now if now is not None else time.time())
