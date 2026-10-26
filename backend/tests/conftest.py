import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.main import app, build_service

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def aid(n: int) -> str:
    return f"2410.{n:05d}"


NEWEST = datetime(2026, 10, 23, tzinfo=timezone.utc)


def published_at(n: int) -> datetime:
    """Result n of a submittedDate-descending query was submitted n hours before NEWEST."""
    return NEWEST - timedelta(hours=n)


def _entry(arxiv_id: str) -> str:
    n = int(arxiv_id.split(".")[1]) if arxiv_id.startswith("2410.") else 0
    ts = published_at(n).strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""<entry>
<id>http://arxiv.org/abs/{arxiv_id}v1</id><title>Paper {arxiv_id}</title>
<updated>{ts}</updated><published>{ts}</published>
<summary>Abstract of {arxiv_id}.</summary>
<link href="http://arxiv.org/abs/{arxiv_id}v1" rel="alternate" type="text/html"/>
<link href="http://arxiv.org/pdf/{arxiv_id}v1" rel="related" type="application/pdf" title="pdf"/>
<arxiv:primary_category term="cs.DB"/><category term="cs.DB"/>
<author><name>Author of {arxiv_id}</name></author></entry>"""


def feed_xml(ids: list[str], total: int, start: int) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/" '
        'xmlns:arxiv="http://arxiv.org/schemas/atom">'
        f"<opensearch:totalResults>{total}</opensearch:totalResults>"
        f"<opensearch:startIndex>{start}</opensearch:startIndex>"
        f"<opensearch:itemsPerPage>{len(ids)}</opensearch:itemsPerPage>"
        + "".join(_entry(i) for i in ids)
        + "</feed>"
    ).encode()


class FakeArxiv:
    """Serves any window of a `total`-result query, or any id_list."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.total = 250
        self.delay = 0.0
        self.status = 200
        self.raise_exc: Exception | None = None
        self.body: bytes | None = None
        self.missing: set[str] = set()
        self.empty_times = 0

    def params(self, i: int = -1) -> dict[str, str]:
        return {k: v[0] for k, v in parse_qs(urlparse(str(self.requests[i].url)).query).items()}

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.raise_exc:
            raise self.raise_exc
        if self.body is not None:
            return httpx.Response(self.status, content=self.body)
        p = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
        if "id_list" in p:
            ids = [i for i in p["id_list"].split(",") if i not in self.missing]
            return httpx.Response(200, content=feed_xml(ids, len(ids), 0))
        start, size = int(p["start"]), int(p["max_results"])
        if self.empty_times:
            self.empty_times -= 1
            ids = []
        else:
            ids = [aid(n) for n in range(start, min(start + size, self.total))]
        return httpx.Response(self.status, content=feed_xml(ids, self.total, start))


class Clock:
    def __init__(self):
        self.t = time.time()

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def fake():
    return FakeArxiv()


@pytest.fixture
def clock():
    return Clock()


@pytest_asyncio.fixture
async def make_svc(tmp_path, fake, clock):
    made = []

    async def _make(db: str = "main", **kw):
        kw.setdefault("rate_limiter", "process")
        kw.setdefault("interval_s", 0)
        kw.setdefault("clock", clock)
        http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        svc = await build_service(database_url=f"sqlite+aiosqlite:///{tmp_path}/{db}.db", http=http, **kw)
        made.append(svc)
        return svc

    yield _make
    for svc in made:
        await svc.aclose()
        await svc.engine.dispose()


@pytest.fixture
def client(fake, clock, tmp_path):
    async def factory():
        http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handler))
        return await build_service(
            database_url=f"sqlite+aiosqlite:///{tmp_path}/api.db",
            rate_limiter="process", interval_s=0, http=http, clock=clock,
        )

    app.state.service_factory = factory
    with TestClient(app) as c:
        yield c
    del app.state.service_factory
