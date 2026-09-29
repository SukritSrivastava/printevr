"""Staff passcode for invoicing (BRD-cart-invoice FR-P8).

The token is "<expiry>.<hmac>" signed with a key derived from SECRET_KEY and the passcode,
so changing either signs every staff member out. Stateless, which suits serverless hosting.
"""
import hashlib
import hmac
import time

TOKEN_HOURS = 12


def _key(secret: str, passcode: str) -> bytes:
    return hashlib.sha256(f"printevr-staff\0{secret}\0{passcode}".encode()).digest()


def passcode_matches(given: str, expected: str) -> bool:
    return hmac.compare_digest(given.encode(), expected.encode())


def issue(secret: str, passcode: str, now: float | None = None) -> tuple[str, int]:
    expires = int((now if now is not None else time.time()) + TOKEN_HOURS * 3600)
    sig = hmac.new(_key(secret, passcode), f"staff.{expires}".encode(), hashlib.sha256).hexdigest()
    return f"{expires}.{sig}", expires


def valid(token: str | None, secret: str, passcode: str, now: float | None = None) -> bool:
    if not token or "." not in token:
        return False
    expires, sig = token.split(".", 1)
    if not expires.isdigit():
        return False
    expected = hmac.new(_key(secret, passcode), f"staff.{expires}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    return int(expires) > (now if now is not None else time.time())


def bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None
