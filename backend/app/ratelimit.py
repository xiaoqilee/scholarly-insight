"""Upstream rate limiters.

Both hand out time slots `interval` apart. A caller reserves the next slot,
then sleeps until it, so the lock is never held while waiting.
"""
from __future__ import annotations

import asyncio
import time

from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from .models import RateLimit


class ProcessLimiter:
    """In-memory. Correct only when a single process talks to arXiv."""

    def __init__(self, interval_s: float):
        self.interval_s = interval_s
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            slot = max(now, self._next)
            self._next = slot + self.interval_s
        if slot > now:
            await asyncio.sleep(slot - now)


class DbLimiter:
    """Shared across workers and instances: one atomic UPDATE reserves a slot."""

    _RESERVE = text(
        "UPDATE rate_limits "
        "SET next_at = (CASE WHEN next_at > :now THEN next_at ELSE :now END) + :iv "
        "WHERE name = :name RETURNING next_at"
    )

    def __init__(self, sessionmaker: async_sessionmaker, interval_s: float, name: str = "arxiv"):
        self.sm = sessionmaker
        self.interval_s = interval_s
        self.name = name

    async def ensure(self) -> None:
        async with self.sm() as s:
            if await s.scalar(select(RateLimit.name).where(RateLimit.name == self.name)):
                return
            try:
                await s.execute(insert(RateLimit).values(name=self.name, next_at=0.0))
                await s.commit()
            except IntegrityError:  # another worker created it first
                await s.rollback()

    async def acquire(self) -> None:
        now = time.time()
        async with self.sm() as s:
            next_at = (
                await s.execute(self._RESERVE, {"now": now, "iv": self.interval_s, "name": self.name})
            ).scalar_one()
            await s.commit()
        slot = next_at - self.interval_s
        wait = slot - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
