from __future__ import annotations

from collections import defaultdict, deque
from time import monotonic


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def allowed(self, key: str) -> bool:
        now = monotonic()
        events = self._events[key]
        while events and events[0] <= now - self.window_seconds:
            events.popleft()
        return len(events) < self.limit

    def record_failure(self, key: str) -> None:
        self._events[key].append(monotonic())

    def clear(self, key: str) -> None:
        self._events.pop(key, None)


admin_login_limiter = SlidingWindowLimiter(limit=8, window_seconds=15 * 60)
public_submission_limiter = SlidingWindowLimiter(limit=10, window_seconds=15 * 60)
