"""Admin passcode for the Team tab (employee list, attendance corrections).

A stand-in until role-based login: the token is "<expiry>.<hmac>" signed with a key derived
from SECRET_KEY and ADMIN_PASSCODE, so changing either signs every admin out. It travels in
the X-Team-Admin header, next to the staff token (the Team tab needs both). Role-based login
should replace `is_admin` in routes.py, the one place that decides who is an admin.
"""
import hashlib
import hmac
import time

TOKEN_HOURS = 12
HEADER = "X-Team-Admin"


def _key(secret: str, passcode: str) -> bytes:
    return hashlib.sha256(f"printevr-team-admin\0{secret}\0{passcode}".encode()).digest()


def passcode_matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


def issue(secret: str, passcode: str, now: float | None = None) -> tuple[str, int]:
    expires = int((now if now is not None else time.time()) + TOKEN_HOURS * 3600)
    sig = hmac.new(_key(secret, passcode), f"team-admin.{expires}".encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}", expires


def valid(token: str | None, secret: str, passcode: str, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, sig = token.split(".", 1)
    if not expires.isdigit():
        return False
    expected = hmac.new(_key(secret, passcode), f"team-admin.{expires}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    return int(expires) > (now if now is not None else time.time())
