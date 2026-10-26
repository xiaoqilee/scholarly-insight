"""Scholarly Insight backend: search, browse and article details over arXiv."""
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from math import ceil
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from sqlalchemy import func, select

from . import db as db_module
from .arxiv_client import (
    ArxivClient,
    ArxivError,
    ArxivRequest,
    ArxivUnavailable,
    build_search_query,
    parse_arxiv_id,
)
from .categories import ALL_CODES, CATEGORIES
from .config import settings
from .dsa.rate_window import SlidingWindowLimiter
from .models import Article, CacheWindow
from .ratelimit import DbLimiter, ProcessLimiter
from .schemas import ArticleDetail, ArticleSummary, Detail, Page
from .service import ArticleService

SortBy = Literal["relevance", "submittedDate", "lastUpdatedDate"]
SortOrder = Literal["ascending", "descending"]


async def build_service(
    database_url: str = settings.database_url,
    rate_limiter: str = settings.rate_limiter,
    interval_s: float = settings.arxiv_min_interval_s,
    http=None,
    **service_kwargs,
) -> ArticleService:
    engine = db_module.make_engine(database_url)
    await db_module.init_db(engine)
    sm = db_module.make_sessionmaker(engine)
    if rate_limiter == "db":
        limiter = DbLimiter(sm, interval_s)
        await limiter.ensure()
    else:
        limiter = ProcessLimiter(interval_s)
    svc = ArticleService(
        ArxivClient(limiter, http=http), sm, sqlite=db_module.is_sqlite(database_url), **service_kwargs
    )
    svc.engine = engine
    await svc.load_index()
    return svc


@asynccontextmanager
async def lifespan(app: FastAPI):
    factory = getattr(app.state, "service_factory", None) or build_service
    app.state.service = await factory()
    if not hasattr(app.state, "client_limiter"):
        app.state.client_limiter = SlidingWindowLimiter(settings.client_rate_limit, settings.client_rate_window_s)
    yield
    await app.state.service.aclose()
    await app.state.service.engine.dispose()


app = FastAPI(
    title="Scholarly Insight API",
    version="0.2.0",
    description="Search and browse arXiv metadata. "
    "Thank you to arXiv for use of its open access interoperability.",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@app.middleware("http")
async def per_client_rate_limit(request: Request, call_next):
    """Sliding-window queue per client IP on /api/* (see dsa/rate_window)."""
    limiter = getattr(request.app.state, "client_limiter", None)
    if limiter is not None and request.url.path.startswith("/api/"):
        client = request.client.host if request.client else "unknown"
        allowed, retry = limiter.check(client, time.monotonic())
        if not allowed:
            return JSONResponse(
                {"detail": "too many requests, slow down"}, status_code=429,
                headers={"Retry-After": str(max(1, int(retry + 0.999)))},
            )
    return await call_next(request)


def service(request: Request) -> ArticleService:
    return request.app.state.service


def _cache_headers(response: Response, svc: ArticleService, source: str, expires_at: float) -> None:
    """Let browsers/CDNs reuse fresh responses; never let them cache stale ones."""
    ttl = int(expires_at - svc.clock())
    if source == "stale" or ttl <= 0:
        response.headers["Cache-Control"] = "no-cache"
    else:
        response.headers["Cache-Control"] = f"public, max-age={min(ttl, 3600)}"
    response.headers["X-Cache"] = source


async def _run(svc, response, search_query, page, page_size, sort_by, sort_order) -> Page:
    start = (page - 1) * page_size
    if start + page_size > settings.max_offset:
        raise HTTPException(422, f"arXiv cannot page past {settings.max_offset} results")
    try:
        base = ArxivRequest(search_query=search_query, sort_by=sort_by, sort_order=sort_order)
        res = await svc.search(base, start, page_size)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except ArxivError as e:
        raise HTTPException(400, f"arXiv rejected the query: {e}")
    except ArxivUnavailable as e:
        raise HTTPException(502, str(e))
    _cache_headers(response, svc, res.source, res.expires_at)
    capped = min(res.total, settings.max_offset)
    return Page(
        total_results=res.total,
        page=page,
        page_size=page_size,
        total_pages=ceil(capped / page_size) if capped else 0,
        source=res.source,
        cached=res.source != "arxiv",
        stale=res.source == "stale",
        query=search_query,
        results=[ArticleSummary.model_validate(a) for a in res.articles],
    )


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/api/search", response_model=Page, summary="Search by keyword, author, category and date")
async def search(
    response: Response,
    q: str | None = Query(None, description="Keywords across all fields"),
    query: str | None = Query(
        None, description='Boolean query, e.g. (transformer OR "state space") AND author:gu NOT title:survey',
        max_length=500,
    ),
    title: str | None = None,
    author: str | None = Query(None, examples=["Yann LeCun"]),
    abstract: str | None = None,
    category: str | None = Query(None, examples=["cs.DB"]),
    date_from: date | None = Query(None, description="Submitted on or after (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Submitted on or before (YYYY-MM-DD)"),
    sort_by: SortBy = "relevance",
    sort_order: SortOrder = "descending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=settings.max_page_size),
    svc: ArticleService = Depends(service),
):
    try:
        sq = build_search_query(
            q=q, title=title, author=author, abstract=abstract,
            category=category, date_from=date_from, date_to=date_to, advanced=query,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))
    svc.record_query(query or q or title or author or abstract or category or sq)
    return await _run(svc, response, sq, page, page_size, sort_by, sort_order)


@app.get("/api/browse/{category}", response_model=Page, summary="Newest papers in a category")
async def browse(
    category: str,
    response: Response,
    date_from: date | None = None,
    date_to: date | None = None,
    sort_by: SortBy = "submittedDate",
    sort_order: SortOrder = "descending",
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=settings.max_page_size),
    svc: ArticleService = Depends(service),
):
    if category not in ALL_CODES:
        raise HTTPException(404, f"unknown category {category!r}; see /api/categories")
    try:
        sq = build_search_query(category=category, date_from=date_from, date_to=date_to)
    except ValueError as e:
        raise HTTPException(422, str(e))
    svc.record_query(category)
    return await _run(svc, response, sq, page, page_size, sort_by, sort_order)


@app.get("/api/browse/{category}/new", summary="Papers submitted since a time (binary search)")
async def browse_new(
    category: str,
    since: datetime = Query(..., description="ISO time, e.g. 2026-10-20T00:00:00Z"),
    limit: int = Query(20, ge=1, le=100),
    svc: ArticleService = Depends(service),
):
    if category not in ALL_CODES:
        raise HTTPException(404, f"unknown category {category!r}; see /api/categories")
    ts = (since if since.tzinfo else since.replace(tzinfo=timezone.utc)).timestamp()
    try:
        count, more, rows = await svc.new_since(build_search_query(category=category), ts, limit)
    except ArxivError as e:
        raise HTTPException(400, str(e))
    except ArxivUnavailable as e:
        raise HTTPException(502, str(e))
    return {
        "category": category,
        "since": since.isoformat(),
        "new_count": count,
        "has_more": more,  # every paper in the newest window is newer than `since`
        "results": [ArticleSummary.model_validate(a) for a in rows],
    }


@app.get("/api/suggest", summary="Autocomplete from a trie (no arXiv calls)")
def suggest(
    prefix: str = Query(..., min_length=1, max_length=80),
    kind: Literal["author", "term", "category"] = "term",
    k: int = Query(8, ge=1, le=10),
    svc: ArticleService = Depends(service),
):
    return {"kind": kind, "prefix": prefix, **svc.index.suggest(kind, prefix, k)}


@app.get("/api/trending", summary="Most requested searches on this worker (top-k heap)")
def trending(k: int = Query(5, ge=1, le=50), svc: ArticleService = Depends(service)):
    return {"trending": [{"query": q, "count": c} for q, c in svc.trending(k)]}


@app.get("/api/articles/{arxiv_id:path}", response_model=Detail, summary="Full article details")
async def article(arxiv_id: str, response: Response, svc: ArticleService = Depends(service)):
    try:
        base, _ = parse_arxiv_id(arxiv_id)
        row, source = await svc.get_article(base)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except ArxivError as e:
        raise HTTPException(400, str(e))
    except ArxivUnavailable as e:
        raise HTTPException(502, str(e))
    if row is None:
        raise HTTPException(404, f"article {base} not found")
    _cache_headers(response, svc, source, svc._expiry(row.fetched_at))
    return Detail(
        source=source, cached=source != "arxiv", stale=source == "stale",
        article=ArticleDetail.model_validate(row),
    )


@app.get("/api/categories", summary="Category groups for browse menus")
def categories(response: Response):
    response.headers["Cache-Control"] = "public, max-age=86400"
    return CATEGORIES


@app.get("/api/stats", summary="Cache and upstream usage (for the demo)")
async def stats(svc: ArticleService = Depends(service)):
    async with svc.sm() as s:
        articles = await s.scalar(select(func.count()).select_from(Article))
        windows = await s.scalar(select(func.count()).select_from(CacheWindow))
    m = svc.metrics
    served = m["l1_hits"] + m["db_hits"] + m["stale_served"] + m["detail_hits"]
    upstream = svc.client.calls_made
    return {
        "articles_stored": articles,
        "cached_windows": windows,
        "l1_windows": len(svc.l1),
        "l1_evictions": svc.l1.evictions,
        "suggest_index": svc.index.sizes(),
        "arxiv_calls_this_worker": upstream,
        "served_without_waiting_on_arxiv": served,
        "hit_rate": round(served / (served + upstream), 3) if served + upstream else None,
        **m,
        "window_size": svc.window_size,
        "refresh_tz": svc.refresh_tz,
        "rate_limiter": type(svc.client.limiter).__name__,
        "min_interval_s": svc.client.limiter.interval_s,
    }
