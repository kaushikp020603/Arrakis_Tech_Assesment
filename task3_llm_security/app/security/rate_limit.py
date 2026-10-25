"""Guardrail for category 3 (resource exhaustion): per-user sliding-window rate limit.

The second half of the protection (concurrency cap + load shedding) lives in secure_app.py, and the
size limits in body_limit.py and in the request model.
"""
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException

from .. import settings
from .auth import current_user


class SlidingWindowLimiter:
    def __init__(self, limit: int, window: float):
        self.limit, self.window = limit, window
        self.lock = threading.Lock()
        self.hits: dict = defaultdict(deque)

    def hit(self, key: str):
        """Record a request. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.limit:
                return False, int(self.window - (now - q[0])) + 1
            q.append(now)
            return True, 0


_limiter = SlidingWindowLimiter(settings.RATE_LIMIT_PER_MIN, settings.RATE_WINDOW)


def rate_limited_user(user: str = Depends(current_user)) -> str:
    allowed, retry = _limiter.hit(user)
    if not allowed:
        raise HTTPException(429, detail={"detail": "Rate limit exceeded", "code": "E_RATE"},
                            headers={"Retry-After": str(retry)})
    return user
