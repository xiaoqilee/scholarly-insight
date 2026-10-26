"""Per-client sliding-window rate limiter: a queue per client (LeetCode 933).

Each client has a deque of request timestamps. On a new request, pop
timestamps older than the window off the left, then compare the length to
the limit. Each timestamp is pushed and popped once: amortized O(1).

This protects our upstream budget: one script hammering /api/search
cannot starve other users of arXiv calls.
"""
from __future__ import annotations

from collections import deque


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float, max_clients: int = 50_000):
        self.limit = limit
        self.window_s = window_s
        self.max_clients = max_clients
        self._log: dict[str, deque[float]] = {}

    def check(self, client: str, now: float) -> tuple[bool, float]:
        """Returns (allowed, retry_after_seconds)."""
        q = self._log.get(client)
        if q is None:
            if len(self._log) >= self.max_clients:
                self._prune(now)
            q = self._log[client] = deque()
        cutoff = now - self.window_s
        while q and q[0] <= cutoff:
            q.popleft()
        if len(q) >= self.limit:
            return False, q[0] + self.window_s - now
        q.append(now)
        return True, 0.0

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        for c in [c for c, q in self._log.items() if not q or q[-1] <= cutoff]:
            del self._log[c]

    def __len__(self) -> int:
        return len(self._log)
