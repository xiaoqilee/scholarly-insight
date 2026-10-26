"""Read path between the API and arXiv.

    request -> L1 (per-worker LRU) -> L2 (database) -> arXiv

* Windows: arXiv is called for aligned blocks of `window_size` results; pages
  are sliced out of them, so paging costs one call per window, not per page.
* Freshness: arXiv publishes daily, so data is fresh until the next midnight
  in `refresh_tz`. After that it is served stale (instantly) while one
  background task refreshes it, for up to `stale_max_s`.
* Single-flight: concurrent misses for the same window share one upstream call.
* Batching: detail lookups that miss within a few ms become one id_list call.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .arxiv_client import ArxivClient, ArxivRequest, ArxivUnavailable, ParsedArticle
from .config import settings
from .dsa.lru import LRUCache
from .dsa.search import first_not_newer
from .dsa.topk import top_k
from .models import Article, CacheWindow
from .suggest import SuggestIndex

log = logging.getLogger("scholarly.service")

Source = Literal["l1", "db", "stale", "arxiv"]


def next_refresh(ts: float, tz: str) -> float:
    """Epoch of the first midnight in `tz` strictly after `ts`."""
    local = datetime.fromtimestamp(ts, ZoneInfo(tz))
    midnight = (local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


@dataclass(frozen=True)
class Window:
    total: int
    ids: tuple[str, ...]
    fetched_at: float
    expires_at: float


@dataclass
class SearchResult:
    total: int
    articles: list[Article]
    source: Source  # worst source among the windows used
    expires_at: float


class IdBatcher:
    """Collects detail misses for `delay_s`, then fetches them in one call."""

    def __init__(self, fetch: Callable[[list[str]], Awaitable[dict[str, Article]]],
                 delay_s: float, max_ids: int):
        self._fetch = fetch
        self.delay_s = delay_s
        self.max_ids = max_ids
        self._pending: dict[str, asyncio.Future] = {}
        self._timer: asyncio.Task | None = None
        self.batches_sent = 0

    def load(self, arxiv_id: str) -> asyncio.Future:
        fut = self._pending.get(arxiv_id)
        if fut is not None:
            return fut
        fut = asyncio.get_running_loop().create_future()
        self._pending[arxiv_id] = fut
        if len(self._pending) >= self.max_ids:
            asyncio.ensure_future(self._flush())
        elif self._timer is None:
            self._timer = asyncio.ensure_future(self._after_delay())
        return fut

    async def _after_delay(self):
        await asyncio.sleep(self.delay_s)
        self._timer = None
        await self._flush()

    async def _flush(self):
        batch = dict(list(self._pending.items())[: self.max_ids])
        for k in batch:
            del self._pending[k]
        if not batch:
            return
        if self._pending and self._timer is None:
            self._timer = asyncio.ensure_future(self._after_delay())
        self.batches_sent += 1
        try:
            found = await self._fetch(list(batch))
        except Exception as e:  # noqa: BLE001  (propagate to every waiter)
            for f in batch.values():
                if not f.done():
                    f.set_exception(e)
            return
        for k, f in batch.items():
            if not f.done():
                f.set_result(found.get(k))


def _epoch(dt: datetime) -> float:
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()


def _consume(fut: asyncio.Future) -> None:
    """Retrieve a background task's exception so asyncio doesn't warn."""
    if not fut.cancelled() and fut.exception() is not None:
        log.warning("background refresh failed: %s", fut.exception())


class ArticleService:
    def __init__(
        self,
        client: ArxivClient,
        sessionmaker: async_sessionmaker,
        *,
        sqlite: bool,
        clock: Callable[[], float] = time.time,
        window_size: int = settings.window_size,
        refresh_tz: str = settings.refresh_tz,
        stale_max_s: int = settings.stale_max_s,
        l1_windows: int = settings.l1_windows,
        batch_window_s: float = settings.batch_window_ms / 1000,
    ):
        self.client = client
        self.sm = sessionmaker
        self.clock = clock
        self.window_size = window_size
        self.refresh_tz = refresh_tz
        self.stale_max_s = stale_max_s
        self.l1: LRUCache[str, Window] = LRUCache(l1_windows)  # hash map + linked list
        self.index = SuggestIndex()  # tries for autocomplete
        self.query_counts: dict[str, int] = {}  # hash map feeding the trending heap
        self.batcher = IdBatcher(self._fetch_ids, batch_window_s, settings.max_ids_per_call)
        self._inflight: dict[str, asyncio.Task] = {}
        self._background: set[asyncio.Future] = set()
        # SQLite allows one writer; serialize this process's writes to avoid
        # lock-upgrade failures. Postgres needs no such lock.
        self._write_lock = asyncio.Lock() if sqlite else None
        self.metrics = {k: 0 for k in (
            "l1_hits", "db_hits", "stale_served", "arxiv_windows", "coalesced",
            "background_refreshes", "detail_hits", "detail_batched",
        )}

    # ------------------------------------------------------------ helpers

    def _expiry(self, fetched_at: float) -> float:
        return next_refresh(fetched_at, self.refresh_tz)

    def _spawn(self, fut: asyncio.Future) -> None:
        self._background.add(fut)
        fut.add_done_callback(self._background.discard)
        fut.add_done_callback(_consume)

    def _single_flight(self, key: str, factory: Callable[[], Awaitable[Window]]) -> asyncio.Task:
        task = self._inflight.get(key)
        if task is not None:
            self.metrics["coalesced"] += 1
            return task
        task = asyncio.ensure_future(factory())
        self._inflight[key] = task
        task.add_done_callback(lambda _: self._inflight.pop(key, None))
        return task

    async def _write(self, fn: Callable[[AsyncSession], Awaitable[None]]) -> None:
        """Run a write transaction, retrying briefly on SQLite lock contention."""
        for attempt in range(5):
            try:
                if self._write_lock:
                    async with self._write_lock:
                        await self._write_once(fn)
                else:
                    await self._write_once(fn)
                return
            except (OperationalError, IntegrityError) as e:
                # IntegrityError: another worker inserted the same row first.
                # OperationalError: "database is locked" from another process.
                if attempt == 4:
                    raise
                log.info("retrying write after %s", type(e).__name__)
                await asyncio.sleep(0.05 * (attempt + 1))

    async def _write_once(self, fn):
        async with self.sm() as s:
            await fn(s)
            await s.commit()

    @staticmethod
    async def _upsert_articles(s: AsyncSession, parsed: list[ParsedArticle], now: float) -> list[ParsedArticle]:
        """Insert or update by version-less id. Returns the articles that were new."""
        if not parsed:
            return []
        ids = list({p.arxiv_id for p in parsed})
        rows = {a.arxiv_id: a for a in await s.scalars(select(Article).where(Article.arxiv_id.in_(ids)))}
        new: list[ParsedArticle] = []
        for p in parsed:
            row = rows.get(p.arxiv_id)
            if row is None:
                row = rows[p.arxiv_id] = Article(arxiv_id=p.arxiv_id, latest_version=p.version)
                s.add(row)
                new.append(p)
            row.latest_version = max(p.version, row.latest_version or 1)
            row.title, row.summary, row.authors = p.title, p.summary, p.authors
            row.primary_category, row.categories = p.primary_category, p.categories
            row.published, row.updated = p.published, p.updated
            row.abs_url, row.pdf_url, row.doi = p.abs_url, p.pdf_url, p.doi
            row.journal_ref, row.comment = p.journal_ref, p.comment
            row.fetched_at = now
        return new

    def _index(self, articles) -> None:
        for a in articles:
            self.index.add_article(a.title, (x["name"] for x in a.authors), a.primary_category)

    async def load_index(self, limit: int = settings.suggest_preload) -> int:
        """Warm the autocomplete tries from the database at startup."""
        async with self.sm() as s:
            rows = (await s.execute(
                select(Article.title, Article.authors, Article.primary_category)
                .order_by(Article.published.desc()).limit(limit)
            )).all()
        for title, authors, cat in rows:
            self.index.add_article(title, (x["name"] for x in authors), cat)
        return len(rows)

    async def _load_articles(self, ids: list[str]) -> list[Article]:
        if not ids:
            return []
        async with self.sm() as s:
            rows = {a.arxiv_id: a for a in await s.scalars(select(Article).where(Article.arxiv_id.in_(ids)))}
        return [rows[i] for i in ids if i in rows]

    # ------------------------------------------------------------ windows

    @staticmethod
    def _window_key(query_key: str, start: int) -> str:
        return hashlib.sha256(f"{query_key}&start={start}".encode()).hexdigest()

    async def _fetch_window(self, key: str, query_key: str, base: ArxivRequest, start: int) -> Window:
        req = ArxivRequest(
            search_query=base.search_query, start=start, max_results=self.window_size,
            sort_by=base.sort_by, sort_order=base.sort_order,
        )
        feed = await self.client.fetch(req)
        if not feed.articles and start < feed.total_results:
            # Known arXiv hiccup: an empty page for a range that has results. Retry once.
            feed = await self.client.fetch(req)
            if not feed.articles and start < feed.total_results:
                raise ArxivUnavailable("arXiv returned an empty page; please retry")
        self.metrics["arxiv_windows"] += 1
        now = self.clock()
        win = Window(
            total=feed.total_results,
            ids=tuple(dict.fromkeys(a.arxiv_id for a in feed.articles)),
            fetched_at=now,
            expires_at=self._expiry(now),
        )

        new: list[ParsedArticle] = []

        async def tx(s: AsyncSession):
            new[:] = await self._upsert_articles(s, feed.articles, now)
            await s.merge(CacheWindow(
                key=key, query_key=query_key, window_start=start, total_results=win.total,
                article_ids=list(win.ids), fetched_at=win.fetched_at, expires_at=win.expires_at,
            ))

        await self._write(tx)
        self._index(new)
        self.l1.put(key, win)
        return win

    async def _get_window(self, query_key: str, base: ArxivRequest, start: int) -> tuple[Window, Source]:
        key = self._window_key(query_key, start)
        now = self.clock()

        win, source = self.l1.get(key), "l1"
        if win is None:
            async with self.sm() as s:
                row = await s.get(CacheWindow, key)
            if row is not None:
                win = Window(row.total_results, tuple(row.article_ids), row.fetched_at, row.expires_at)
                self.l1.put(key, win)
                source = "db"

        def refresh():
            return self._fetch_window(key, query_key, base, start)

        if win is not None and now < win.expires_at:
            self.metrics["l1_hits" if source == "l1" else "db_hits"] += 1
            return win, source
        if win is not None and now < win.fetched_at + self.stale_max_s:
            if key not in self._inflight:
                self.metrics["background_refreshes"] += 1
            self._spawn(self._single_flight(key, refresh))
            self.metrics["stale_served"] += 1
            return win, "stale"
        task = self._single_flight(key, refresh)
        # shield: a client disconnect must not cancel work other requests share.
        return await asyncio.shield(task), "arxiv"

    # ------------------------------------------------------------ public

    def record_query(self, label: str) -> None:
        self.query_counts[label] = self.query_counts.get(label, 0) + 1
        if len(self.query_counts) > 10_000:  # bound memory: keep the 5,000 most frequent
            self.query_counts = dict(top_k(self.query_counts, 5_000))

    def trending(self, k: int) -> list[tuple[str, int]]:
        return top_k(self.query_counts, k)  # size-k min-heap, O(n log k)

    async def new_since(self, category_query: str, since: float, limit: int) -> tuple[int, bool, list[Article]]:
        """Papers submitted after `since`, from the newest window: binary search, no extra call."""
        base = ArxivRequest(search_query=category_query, sort_by="submittedDate", sort_order="descending")
        res = await self.search(base, 0, self.window_size)
        stamps = [_epoch(a.published) for a in res.articles]  # sorted newest first
        n = first_not_newer(stamps, since)
        more = n == len(stamps) and res.total > len(stamps)
        return n, more, res.articles[: min(n, limit)]

    async def search(self, base: ArxivRequest, start: int, size: int) -> SearchResult:
        """Return results [start, start+size) for base's query and sort."""
        query_key = f"q={base.search_query}&sortBy={base.sort_by}&sortOrder={base.sort_order}"
        w = self.window_size
        first, last = start // w, (start + size - 1) // w
        got = await asyncio.gather(*(self._get_window(query_key, base, i * w) for i in range(first, last + 1)))
        ids = [i for win, _ in got for i in win.ids]
        offset = start - first * w
        page_ids = list(dict.fromkeys(ids[offset: offset + size]))
        rank = {"l1": 0, "db": 1, "stale": 2, "arxiv": 3}
        return SearchResult(
            total=got[0][0].total,
            articles=await self._load_articles(page_ids),
            source=max((src for _, src in got), key=rank.__getitem__),
            expires_at=min(win.expires_at for win, _ in got),
        )

    async def _fetch_ids(self, ids: list[str]) -> dict[str, Article]:
        feed = await self.client.fetch(ArxivRequest(id_list=tuple(ids), max_results=len(ids)))
        now = self.clock()

        new: list[ParsedArticle] = []

        async def tx(s: AsyncSession):
            new[:] = await self._upsert_articles(s, feed.articles, now)

        await self._write(tx)
        self._index(new)
        found = {a.arxiv_id for a in feed.articles}
        rows = await self._load_articles([i for i in ids if i in found])
        return {a.arxiv_id: a for a in rows}

    async def get_article(self, arxiv_id: str) -> tuple[Article | None, Source]:
        async with self.sm() as s:
            row = await s.get(Article, arxiv_id)
        now = self.clock()
        if row is not None:
            if now < self._expiry(row.fetched_at):
                self.metrics["detail_hits"] += 1
                return row, "db"
            self._spawn(self.batcher.load(arxiv_id))  # refresh in background
            self.metrics["stale_served"] += 1
            return row, "stale"
        self.metrics["detail_batched"] += 1
        return await asyncio.shield(self.batcher.load(arxiv_id)), "arxiv"

    async def drain(self) -> None:
        """Wait for background refreshes (used by tests and on shutdown)."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)

    async def aclose(self) -> None:
        for fut in list(self._background):
            fut.cancel()
        await asyncio.gather(*list(self._background), return_exceptions=True)
        await self.client.aclose()
