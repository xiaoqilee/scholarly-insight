"""Efficiency guarantees of the read path."""
import asyncio
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import db as db_module
from app.arxiv_client import ArxivRequest, ArxivUnavailable
from app.ratelimit import DbLimiter, ProcessLimiter
from app.service import next_refresh
from tests.conftest import aid

BASE = ArxivRequest(search_query="cat:cs.DB", sort_by="submittedDate")
DAY = 86400


def ids(res):
    return [a.arxiv_id for a in res.articles]


# ---------------------------------------------------------------- windows

async def test_five_pages_cost_one_call(make_svc, fake):
    svc = await make_svc()
    for page in range(5):
        res = await svc.search(BASE, page * 20, 20)
        assert ids(res) == [aid(n) for n in range(page * 20, page * 20 + 20)]
    assert len(fake.requests) == 1
    assert (fake.params()["start"], fake.params()["max_results"]) == ("0", "100")


async def test_next_window_is_aligned(make_svc, fake):
    svc = await make_svc()
    await svc.search(BASE, 120, 20)
    assert fake.params()["start"] == "100"


async def test_page_spanning_two_windows(make_svc, fake):
    svc = await make_svc()
    res = await svc.search(BASE, 90, 30)
    assert ids(res) == [aid(n) for n in range(90, 120)]
    assert sorted(p["start"] for p in map(fake.params, range(2))) == ["0", "100"]


async def test_last_partial_page_and_past_the_end(make_svc, fake):
    svc = await make_svc()
    res = await svc.search(BASE, 240, 20)
    assert ids(res) == [aid(n) for n in range(240, 250)] and res.total == 250
    res = await svc.search(BASE, 300, 20)
    assert ids(res) == [] and res.total == 250
    assert len(fake.requests) == 2  # empty tail is cached, not retried


async def test_sort_order_is_part_of_the_cache_key(make_svc, fake):
    svc = await make_svc()
    await svc.search(BASE, 0, 20)
    await svc.search(ArxivRequest(search_query="cat:cs.DB", sort_by="relevance"), 0, 20)
    assert len(fake.requests) == 2


# ---------------------------------------------------------------- coalescing

async def test_concurrent_identical_misses_share_one_call(make_svc, fake):
    svc = await make_svc()
    fake.delay = 0.1
    results = await asyncio.gather(*(svc.search(BASE, 0, 20) for _ in range(10)))
    assert len(fake.requests) == 1
    assert all(ids(r) == ids(results[0]) for r in results)
    assert svc.metrics["coalesced"] == 9


async def test_concurrent_pages_of_one_window_share_one_call(make_svc, fake):
    svc = await make_svc()
    fake.delay = 0.05
    await asyncio.gather(*(svc.search(BASE, p * 20, 20) for p in range(5)))
    assert len(fake.requests) == 1


async def test_failure_reaches_every_waiter_and_is_not_cached(make_svc, fake):
    svc = await make_svc()
    fake.delay, fake.status, fake.body = 0.05, 503, b"down"
    out = await asyncio.gather(*(svc.search(BASE, 0, 20) for _ in range(3)), return_exceptions=True)
    assert all(isinstance(e, ArxivUnavailable) for e in out) and len(fake.requests) == 1
    fake.body, fake.status = None, 200
    assert len(ids(await svc.search(BASE, 0, 20))) == 20  # retried, not poisoned


# ---------------------------------------------------------------- freshness

async def test_fresh_until_midnight_then_stale_while_revalidate(make_svc, fake, clock):
    svc = await make_svc()
    first = await svc.search(BASE, 0, 20)
    assert first.source == "arxiv"
    assert (await svc.search(BASE, 0, 20)).source == "l1"

    clock.advance(DAY + 60)  # past the next midnight
    fake.delay = 0.3
    t0 = time.perf_counter()
    stale = await svc.search(BASE, 0, 20)
    assert stale.source == "stale" and ids(stale) == ids(first)
    assert time.perf_counter() - t0 < 0.1  # did not wait for arXiv

    await svc.search(BASE, 0, 20)  # second stale read joins the same refresh
    await svc.drain()
    assert len(fake.requests) == 2 and svc.metrics["background_refreshes"] == 1
    assert (await svc.search(BASE, 0, 20)).source == "l1"


async def test_too_old_is_fetched_before_responding(make_svc, fake, clock):
    svc = await make_svc(stale_max_s=2 * DAY)
    await svc.search(BASE, 0, 20)
    clock.advance(3 * DAY)
    assert (await svc.search(BASE, 0, 20)).source == "arxiv"
    assert len(fake.requests) == 2


def test_next_refresh_is_next_eastern_midnight():
    ny = ZoneInfo("America/New_York")
    at = lambda *a: datetime(*a, tzinfo=ny).timestamp()  # noqa: E731
    assert next_refresh(at(2026, 10, 23, 23, 59, 59), "America/New_York") == at(2026, 10, 24)
    assert next_refresh(at(2026, 10, 24, 0, 0, 0), "America/New_York") == at(2026, 10, 25)
    # DST ends 2026-11-01: still lands on local midnight
    assert next_refresh(at(2026, 11, 1, 12), "America/New_York") == at(2026, 11, 2)


# ---------------------------------------------------------------- tiers

async def test_second_worker_reads_shared_db_not_arxiv(make_svc, fake):
    w1, w2 = await make_svc(db="shared"), await make_svc(db="shared")
    await w1.search(BASE, 0, 20)
    res = await w2.search(BASE, 20, 20)
    assert res.source == "db" and len(fake.requests) == 1
    assert (await w2.search(BASE, 20, 20)).source == "l1"


async def test_transient_empty_page_is_retried_once(make_svc, fake):
    svc = await make_svc()
    fake.empty_times = 1
    assert len(ids(await svc.search(BASE, 0, 20))) == 20
    assert len(fake.requests) == 2


async def test_persistent_empty_page_errors_and_is_not_cached(make_svc, fake):
    svc = await make_svc()
    fake.empty_times = 2
    with pytest.raises(ArxivUnavailable):
        await svc.search(BASE, 0, 20)
    assert len(ids(await svc.search(BASE, 0, 20))) == 20


# ---------------------------------------------------------------- details

async def test_details_after_search_need_no_call(make_svc, fake):
    svc = await make_svc()
    await svc.search(BASE, 0, 20)
    row, source = await svc.get_article(aid(7))
    assert row.title == f"Paper {aid(7)}" and source == "db" and len(fake.requests) == 1


async def test_concurrent_detail_misses_are_batched(make_svc, fake):
    svc = await make_svc()
    rows = await asyncio.gather(*(svc.get_article(aid(n)) for n in (1, 2, 3, 2)))
    assert [r.arxiv_id for r, _ in rows] == [aid(1), aid(2), aid(3), aid(2)]
    assert len(fake.requests) == 1
    assert sorted(fake.params()["id_list"].split(",")) == [aid(1), aid(2), aid(3)]


async def test_missing_detail_returns_none(make_svc, fake):
    svc = await make_svc()
    fake.missing = {aid(9)}
    row, _ = await svc.get_article(aid(9))
    assert row is None


async def test_stale_detail_served_then_refreshed(make_svc, fake, clock):
    svc = await make_svc()
    await svc.get_article(aid(1))
    clock.advance(DAY + 60)
    row, source = await svc.get_article(aid(1))
    assert source == "stale" and row is not None
    await svc.drain()
    assert len(fake.requests) == 2
    assert (await svc.get_article(aid(1)))[1] == "db"


# ---------------------------------------------------------------- rate limiting

async def test_process_limiter_spaces_calls():
    lim = ProcessLimiter(0.15)
    stamps = []

    async def call():
        await lim.acquire()
        stamps.append(time.monotonic())

    await asyncio.gather(*(call() for _ in range(4)))
    stamps.sort()
    assert all(b - a >= 0.14 for a, b in zip(stamps, stamps[1:]))


async def test_db_limiter_is_shared_across_workers(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path}/rl.db"
    engines = [db_module.make_engine(url) for _ in range(2)]  # two "workers"
    await db_module.init_db(engines[0])
    limiters = [DbLimiter(db_module.make_sessionmaker(e), 0.15) for e in engines]
    await asyncio.gather(*(lim.ensure() for lim in limiters))
    stamps = []

    async def call(lim):
        await lim.acquire()
        stamps.append(time.time())

    await asyncio.gather(*(call(limiters[i % 2]) for i in range(6)))
    stamps.sort()
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    assert all(g >= 0.13 for g in gaps), gaps
    for e in engines:
        await e.dispose()


async def test_memory_sqlite_rejected():
    with pytest.raises(ValueError):
        db_module.make_engine("sqlite+aiosqlite://")
