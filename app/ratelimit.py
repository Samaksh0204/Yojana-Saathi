"""In-memory sliding-window rate limiter (per process; use Redis if you run several instances)."""
import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, per_minute: int, max_keys: int = 50_000) -> None:
        self.per_minute = per_minute
        self.max_keys = max_keys
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > self.max_keys:  # forget idle keys so memory stays bounded
                self._hits = {k: w for k, w in self._hits.items() if w and now - w[-1] <= 60}
            window = self._hits.setdefault(key, deque())
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= self.per_minute:
                return False
            window.append(now)
            return True
