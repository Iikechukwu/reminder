"""Per-key fixed-window rate limiter (in-memory)."""
import threading
import time
from typing import Callable


class FixedWindowLimiter:
    """Allow at most `limit` calls per key in each `window_seconds` window.

    Fixed window: the counter resets when the window ends. Simple and cheap, but
    a client can burst up to 2x the limit across a window boundary (the end of
    one window plus the start of the next). A sliding window or token bucket
    smooths that out at the cost of more state.

    State lives in this process's memory: with N API processes the effective
    limit is N x limit, and a restart resets the counters. Fine for one
    instance; use Redis or Postgres counters for a strict multi-instance limit.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.limit = limit
        self.window = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._state: dict[object, tuple[float, int]] = {}  # key -> (window_start, count)

    def check(self, key) -> tuple[bool, int]:
        """Record one call. Returns (allowed, retry_after_seconds)."""
        now = self._clock()
        with self._lock:
            start, count = self._state.get(key, (now, 0))
            if now - start >= self.window:
                start, count = now, 0
            if count >= self.limit:
                return False, max(1, int(start + self.window - now) + 1)
            self._state[key] = (start, count + 1)
            if len(self._state) > 10_000:  # bound memory: drop expired windows
                self._state = {
                    k: v for k, v in self._state.items() if now - v[0] < self.window
                }
            return True, 0
