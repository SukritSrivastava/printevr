"""Rate limits: a bounded in-memory limiter, and a shared one kept in the invoice database.

MemoryRateLimiter counts per process. Its memory is bounded: clients idle for a whole window
are swept out once per window, and beyond `max_keys` the least recently seen client is
forgotten (worst case, that client starts counting again). Behind several server instances
(Vercel) each instance counts on its own, so a client can make up to limit × instances tries.

DatabaseRateLimiter makes the login limits hold across instances. It counts in the table
`rate_limit_counters` (migration 0004) in the database DATABASE_URL already points at, so no
new service is needed. It is a sliding-window counter: hits in the current minute plus the
previous minute's hits weighted by how much of it is still inside the last 60 seconds. Every
attempt counts, including those refused while over the limit. Client addresses are stored
only as SHA-256 hashes. If the database can't be used (not migrated yet, unreachable), it
falls back to its own MemoryRateLimiter and logs a warning, so limits still apply per instance.
"""
import hashlib
import logging
import threading
import time
from collections import OrderedDict, deque
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("printevr.ratelimit")

TABLE = "rate_limit_counters"


class MemoryRateLimiter:
    def __init__(self, per_minute: int, max_keys: int = 10_000, window: float = 60.0, clock: Callable[[], float] = time.monotonic):
        self.per_minute = per_minute
        self.max_keys = max_keys
        self.window = window
        self._clock = clock
        self.hits: OrderedDict[str, deque] = OrderedDict()
        self._last_sweep = clock()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self.hits)

    def _sweep(self, now: float) -> None:
        """Drop every client with no hit inside the window."""
        stale = [k for k, q in self.hits.items() if not q or now - q[-1] > self.window]
        for k in stale:
            del self.hits[k]
        self._last_sweep = now

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        now = self._clock()
        with self._lock:
            if now - self._last_sweep > self.window:
                self._sweep(now)
            q = self.hits.get(key)
            if q is None:
                while len(self.hits) >= self.max_keys:
                    self.hits.popitem(last=False)  # least recently seen
                q = self.hits[key] = deque()
            else:
                self.hits.move_to_end(key)
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


def client_hash(scope: str, key: str) -> str:
    return hashlib.sha256(f"{scope}\0{key}".encode()).hexdigest()


class DatabaseRateLimiter:
    """Shared across instances through `engine()`; None from it (or any database error) means
    "use the fallback for this call"."""

    def __init__(
        self,
        scope: str,
        per_minute: int,
        engine: Callable[[], Engine | None],
        fallback: MemoryRateLimiter,
        window: int = 60,
        clock: Callable[[], float] = time.time,
    ):
        self.scope = scope
        self.per_minute = per_minute
        self.window = window
        self.fallback = fallback
        self._engine = engine
        self._clock = clock
        self._last_cleanup = 0
        self._warned_at = 0.0

    def allow(self, key: str) -> bool:
        if self.per_minute <= 0:
            return True
        try:
            engine = self._engine()
            if engine is None:
                return self.fallback.allow(key)
            return self._allow(engine, key)
        except Exception as exc:  # the limiter must never take the login down with it
            now = time.monotonic()
            if now - self._warned_at > 300:  # once per 5 minutes, not per request
                self._warned_at = now
                log.warning("shared rate limit unavailable (%s); counting in this instance only", type(exc).__name__)
            return self.fallback.allow(key)

    def _allow(self, engine: Engine, key: str) -> bool:
        now = self._clock()
        current = int(now // self.window) * self.window
        previous = current - self.window
        who = client_hash(self.scope, key)
        with engine.begin() as conn:
            hits = conn.execute(
                text(
                    f"INSERT INTO {TABLE} (scope, client_key, window_start, hits) VALUES (:scope, :who, :w, 1) "
                    f"ON CONFLICT (scope, client_key, window_start) DO UPDATE SET hits = {TABLE}.hits + 1 "
                    "RETURNING hits"
                ),
                {"scope": self.scope, "who": who, "w": current},
            ).scalar_one()
            before = conn.execute(
                text(f"SELECT hits FROM {TABLE} WHERE scope = :scope AND client_key = :who AND window_start = :w"),
                {"scope": self.scope, "who": who, "w": previous},
            ).scalar() or 0
            if current != self._last_cleanup:  # once per window per instance keeps the table small
                self._last_cleanup = current
                conn.execute(text(f"DELETE FROM {TABLE} WHERE window_start < :old"), {"old": previous})
        weight = 1 - (now - current) / self.window
        return before * weight + hits <= self.per_minute
