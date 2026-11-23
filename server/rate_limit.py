"""Small in-process rate limiter for the single-worker profile site.

The site is served by one Waitress process, so an in-memory sliding window is
enough. If it is ever put behind multiple workers, replace this module with a
Redis-backed limiter and keep the same ``hit`` contract.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> tuple[bool, int]:
        """Record one event. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self._lock:
            events = self._events[key]
            while events and now - events[0] >= window:
                events.popleft()
            if len(events) >= limit:
                retry = max(1, int(window - (now - events[0])) + 1)
                return False, retry
            events.append(now)
            return True, 0

    def reset(self, prefix: str | None = None) -> None:
        with self._lock:
            if prefix is None:
                self._events.clear()
                return
            for key in [k for k in self._events if k.startswith(prefix)]:
                del self._events[key]


LIMITER = RateLimiter()
