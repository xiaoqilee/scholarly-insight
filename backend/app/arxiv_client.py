"""arXiv API client: query building, rate-limited fetching, Atom parsing."""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Protocol

import httpx

from .config import settings

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "opensearch": "http://a9.com/-/spec/opensearch/1.1/",
    "arxiv": "http://arxiv.org/schemas/atom",
}

SORT_BY = {"relevance", "lastUpdatedDate", "submittedDate"}
SORT_ORDER = {"ascending", "descending"}

# New style: 2401.01234 (4 or 5 digit suffix). Old style: hep-ex/0307015, math.GT/0309136
_ID_RE = re.compile(
    r"^(?P<base>(\d{4}\.\d{4,5})|([a-z\-]+(\.[A-Z]{2})?/\d{7}))(v(?P<ver>\d+))?$"
)
_CATEGORY_RE = re.compile(r"^[a-z\-]+(\.[A-Za-z\-]+)?$")


class ArxivError(Exception):
    """arXiv returned an error entry (bad query, malformed id, ...)."""


class ArxivUnavailable(Exception):
    """Network failure, timeout, non-200, or a transient empty page."""


class Limiter(Protocol):
    async def acquire(self) -> None: ...


# ---------------------------------------------------------------- ids

def parse_arxiv_id(raw: str) -> tuple[str, int | None]:
    """'http://arxiv.org/abs/2401.01234v2' -> ('2401.01234', 2)."""
    s = raw.strip()
    for prefix in ("http://arxiv.org/abs/", "https://arxiv.org/abs/", "arXiv:", "arxiv:"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    m = _ID_RE.match(s)
    if not m:
        raise ValueError(f"not a valid arXiv id: {raw!r}")
    ver = m.group("ver")
    return m.group("base"), int(ver) if ver else None


# ---------------------------------------------------------------- queries

def _term(value: str) -> str:
    """Quote multi-word terms so arXiv treats them as a phrase."""
    v = " ".join(value.replace('"', "").split())
    if not v:
        raise ValueError("empty search term")
    return f'"{v}"' if " " in v else v


def build_search_query(
    *,
    q: str | None = None,
    title: str | None = None,
    author: str | None = None,
    abstract: str | None = None,
    category: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    advanced: str | None = None,
) -> str:
    """Translate our filters into arXiv's search_query grammar (clauses ANDed).

    `advanced` is a boolean expression parsed with a stack (see dsa/query_parser).
    """
    clauses: list[str] = []
    if advanced:
        from .dsa.query_parser import parse_query

        parsed = parse_query(advanced)
        clauses.append(f"({parsed})" if " " in parsed else parsed)
    if q:
        clauses.append(f"all:{_term(q)}")
    if title:
        clauses.append(f"ti:{_term(title)}")
    if author:
        clauses.append(f"au:{_term(author)}")
    if abstract:
        clauses.append(f"abs:{_term(abstract)}")
    if category:
        if not _CATEGORY_RE.match(category):
            raise ValueError(f"invalid category: {category!r}")
        # 'cs' alone matches the whole archive via wildcard.
        clauses.append(f"cat:{category}" if "." in category else f"cat:{category}.*")
    if date_from or date_to:
        if date_from and date_to and date_from > date_to:
            raise ValueError("date_from must be on or before date_to")
        lo = (date_from or date(1991, 1, 1)).strftime("%Y%m%d") + "0000"
        hi = (date_to or date.today()).strftime("%Y%m%d") + "2359"
        clauses.append(f"submittedDate:[{lo} TO {hi}]")
    if not clauses:
        raise ValueError("at least one search filter is required")
    return " AND ".join(clauses)


@dataclass(frozen=True)
class ArxivRequest:
    search_query: str = ""
    id_list: tuple[str, ...] = ()
    start: int = 0
    max_results: int = 10
    sort_by: str = "relevance"
    sort_order: str = "descending"

    def __post_init__(self):
        if self.sort_by not in SORT_BY:
            raise ValueError(f"sort_by must be one of {sorted(SORT_BY)}")
        if self.sort_order not in SORT_ORDER:
            raise ValueError(f"sort_order must be one of {sorted(SORT_ORDER)}")
        if self.start < 0 or self.max_results < 1:
            raise ValueError("start must be >= 0 and max_results >= 1")
        if self.start + self.max_results > settings.max_offset:
            raise ValueError(f"arXiv cannot page past {settings.max_offset} results")

    def params(self) -> dict[str, str]:
        p = {
            "start": str(self.start),
            "max_results": str(self.max_results),
            "sortBy": self.sort_by,
            "sortOrder": self.sort_order,
        }
        if self.search_query:
            p["search_query"] = self.search_query
        if self.id_list:
            p["id_list"] = ",".join(self.id_list)
        return p


# ---------------------------------------------------------------- parsing

@dataclass
class ParsedArticle:
    arxiv_id: str
    version: int
    title: str
    summary: str
    authors: list[dict]
    primary_category: str | None
    categories: list[str]
    published: datetime
    updated: datetime
    abs_url: str
    pdf_url: str | None
    doi: str | None
    journal_ref: str | None
    comment: str | None


@dataclass
class ParsedFeed:
    total_results: int
    start_index: int
    items_per_page: int
    articles: list[ParsedArticle] = field(default_factory=list)


def _text(el, path) -> str | None:
    found = el.find(path, NS)
    if found is None or found.text is None:
        return None
    return " ".join(found.text.split())  # collapse arXiv's hard line wraps


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _https(url: str | None) -> str | None:
    return url.replace("http://", "https://", 1) if url else url


def parse_feed(xml_text: str | bytes) -> ParsedFeed:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ArxivUnavailable(f"unparseable response from arXiv: {e}") from e

    entries = root.findall("atom:entry", NS)
    # Errors come back as a feed with one entry whose id points at /api/errors.
    if len(entries) == 1 and "/api/errors" in (_text(entries[0], "atom:id") or ""):
        raise ArxivError(_text(entries[0], "atom:summary") or "arXiv error")

    feed = ParsedFeed(
        total_results=int(_text(root, "opensearch:totalResults") or 0),
        start_index=int(_text(root, "opensearch:startIndex") or 0),
        items_per_page=int(_text(root, "opensearch:itemsPerPage") or 0),
    )
    for e in entries:
        raw_id = _text(e, "atom:id")
        if not raw_id:
            continue
        base, ver = parse_arxiv_id(raw_id)
        pdf_url, abs_url = None, raw_id
        for link in e.findall("atom:link", NS):
            if link.get("title") == "pdf":
                pdf_url = link.get("href")
            elif link.get("rel") == "alternate":
                abs_url = link.get("href")
        primary = e.find("arxiv:primary_category", NS)
        feed.articles.append(
            ParsedArticle(
                arxiv_id=base,
                version=ver or 1,
                title=_text(e, "atom:title") or "",
                summary=_text(e, "atom:summary") or "",
                authors=[
                    {"name": _text(a, "atom:name"), "affiliation": _text(a, "arxiv:affiliation")}
                    for a in e.findall("atom:author", NS)
                ],
                primary_category=primary.get("term") if primary is not None else None,
                categories=[c.get("term") for c in e.findall("atom:category", NS) if c.get("term")],
                published=_dt(_text(e, "atom:published")),
                updated=_dt(_text(e, "atom:updated")),
                abs_url=_https(abs_url) or "",
                pdf_url=_https(pdf_url),
                doi=_text(e, "arxiv:doi"),
                journal_ref=_text(e, "arxiv:journal_ref"),
                comment=_text(e, "arxiv:comment"),
            )
        )
    return feed


# ---------------------------------------------------------------- client

class ArxivClient:
    def __init__(self, limiter: Limiter, http: httpx.AsyncClient | None = None):
        self._http = http or httpx.AsyncClient(
            timeout=settings.arxiv_timeout_s,
            headers={"User-Agent": settings.user_agent, "Accept-Encoding": "gzip"},
            follow_redirects=True,
            http2=False,
        )
        self.limiter = limiter
        self.calls_made = 0

    async def fetch(self, req: ArxivRequest) -> ParsedFeed:
        await self.limiter.acquire()
        self.calls_made += 1
        try:
            resp = await self._http.get(settings.arxiv_base_url, params=req.params())
        except httpx.HTTPError as e:
            raise ArxivUnavailable(f"arXiv request failed: {e}") from e
        if resp.status_code not in (200, 400):  # 400 carries an Atom error body
            raise ArxivUnavailable(f"arXiv returned HTTP {resp.status_code}")
        return parse_feed(resp.content)

    async def aclose(self) -> None:
        await self._http.aclose()
