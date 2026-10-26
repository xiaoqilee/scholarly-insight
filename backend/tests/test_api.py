import httpx

from tests.conftest import aid, fixture

DAY = 86400


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_search_maps_filters_to_arxiv(client, fake):
    r = client.get("/api/search", params={
        "author": "Ada Lovelace", "category": "cs.DB",
        "date_from": "2026-01-01", "date_to": "2026-10-23",
        "sort_by": "submittedDate", "page": 3, "page_size": 10,
    })
    assert r.status_code == 200, r.text
    p = fake.params()
    assert p["search_query"] == (
        'au:"Ada Lovelace" AND cat:cs.DB AND submittedDate:[202601010000 TO 202610232359]'
    )
    assert (p["start"], p["max_results"], p["sortBy"]) == ("0", "100", "submittedDate")
    body = r.json()
    assert body["total_results"] == 250 and body["page"] == 3 and body["total_pages"] == 25
    assert (body["source"], body["cached"], body["stale"]) == ("arxiv", False, False)
    assert [a["arxiv_id"] for a in body["results"]] == [aid(n) for n in range(20, 30)]
    assert "summary" not in body["results"][0]  # list view stays light


def test_paging_and_repeat_hit_l1(client, fake):
    for page in (1, 2, 3, 1):
        r = client.get("/api/browse/cs.DB", params={"page": page})
    assert r.json()["source"] == "l1" and r.headers["X-Cache"] == "l1"
    assert r.headers["Cache-Control"].startswith("public, max-age=")
    assert len(fake.requests) == 1
    stats = client.get("/api/stats").json()
    assert stats["arxiv_calls_this_worker"] == 1 and stats["l1_hits"] == 3
    assert stats["hit_rate"] == 0.75 and stats["articles_stored"] == 100


def test_stale_response_headers(client, fake, clock):
    client.get("/api/browse/cs.DB")
    clock.advance(DAY + 60)
    r = client.get("/api/browse/cs.DB")
    assert r.json()["stale"] is True and r.headers["Cache-Control"] == "no-cache"


def test_gzip(client):
    r = client.get("/api/browse/cs.DB", params={"page_size": 100}, headers={"Accept-Encoding": "gzip"})
    assert r.headers["content-encoding"] == "gzip" and len(r.json()["results"]) == 100


def test_search_requires_a_filter(client, fake):
    assert client.get("/api/search").status_code == 422 and not fake.requests


def test_search_validation(client, fake):
    assert client.get("/api/search", params={"q": "x", "page_size": 500}).status_code == 422
    assert client.get("/api/search", params={"q": "x", "sort_by": "citations"}).status_code == 422
    assert client.get("/api/search", params={"q": "x", "date_from": "2026-13-01"}).status_code == 422
    r = client.get("/api/search", params={"q": "x", "date_from": "2026-05-01", "date_to": "2026-01-01"})
    assert r.status_code == 422
    assert client.get("/api/search", params={"title": '""'}).status_code == 422
    assert not fake.requests


def test_deep_paging_rejected(client, fake):
    r = client.get("/api/search", params={"q": "x", "page": 2000, "page_size": 20})
    assert r.status_code == 422 and not fake.requests


def test_browse_archive_and_unknown(client, fake):
    assert client.get("/api/browse/cs").status_code == 200
    assert fake.params()["search_query"] == "cat:cs.*"
    assert (fake.params()["sortBy"], fake.params()["sortOrder"]) == ("submittedDate", "descending")
    assert client.get("/api/browse/cs.FAKE").status_code == 404


def test_article_details_after_browse(client, fake):
    client.get("/api/browse/cs.DB")
    r = client.get(f"/api/articles/{aid(5)}v1")  # version suffix ignored
    body = r.json()
    assert r.status_code == 200 and body["source"] == "db" and len(fake.requests) == 1
    art = body["article"]
    assert art["summary"] == f"Abstract of {aid(5)}."
    assert art["pdf_url"] == f"https://arxiv.org/pdf/{aid(5)}v1"
    assert art["published"].endswith(("Z", "+00:00"))


def test_article_details_fetch_by_id_list(client, fake):
    r = client.get("/api/articles/hep-ex/0307015")  # old-style id with slash
    assert r.status_code == 200 and r.json()["source"] == "arxiv"
    p = fake.params()
    assert p["id_list"] == "hep-ex/0307015" and "search_query" not in p


def test_article_not_found(client, fake):
    fake.missing = {"2501.99999"}
    assert client.get("/api/articles/2501.99999").status_code == 404


def test_bad_article_id(client, fake):
    assert client.get("/api/articles/not-an-id").status_code == 422 and not fake.requests


def test_arxiv_error_becomes_400(client, fake):
    fake.body, fake.status = fixture("error_feed.xml"), 400
    r = client.get("/api/search", params={"q": "x"})
    assert r.status_code == 400 and "incorrect id format" in r.json()["detail"]


def test_upstream_down_becomes_502(client, fake):
    fake.raise_exc = httpx.ConnectTimeout("timed out")
    assert client.get("/api/search", params={"q": "x"}).status_code == 502


def test_upstream_5xx_becomes_502(client, fake):
    fake.status, fake.body = 503, b"unavailable"
    assert client.get("/api/search", params={"q": "x"}).status_code == 502


def test_categories(client):
    r = client.get("/api/categories")
    assert r.json()["cs"]["cs.DB"] == "Databases" and "max-age=86400" in r.headers["Cache-Control"]


def test_openapi_docs(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/search", "/api/browse/{category}", "/api/articles/{arxiv_id}"} <= set(paths)


# ---------------------------------------------------------------- bootcamp-topic endpoints

def test_advanced_query_is_parsed_with_stack(client, fake):
    r = client.get("/api/search", params={
        "query": '(transformer OR "state space") NOT title:survey', "category": "cs.LG",
    })
    assert r.status_code == 200, r.text
    assert fake.params()["search_query"] == (
        '((all:transformer OR all:"state space") ANDNOT ti:survey) AND cat:cs.LG'
    )


def test_advanced_query_errors_are_422_with_position(client, fake):
    r = client.get("/api/search", params={"query": "(graph OR tree"})
    assert r.status_code == 422 and "unmatched '('" in r.json()["detail"]
    assert "character 1" in r.json()["detail"] and not fake.requests


def test_suggest_learns_from_cached_articles(client, fake):
    assert client.get("/api/suggest", params={"prefix": "author of", "kind": "author"}).json()["suggestions"] == []
    client.get("/api/browse/cs.DB")
    before = len(fake.requests)
    r = client.get("/api/suggest", params={"prefix": "author of 2410.0000", "kind": "author", "k": 3}).json()
    assert [s["text"] for s in r["suggestions"]] == [f"Author of {aid(n)}" for n in range(3)]
    cat = client.get("/api/suggest", params={"prefix": "datab", "kind": "category"}).json()
    assert cat["suggestions"][0] == {"text": "cs.DB", "count": 100, "label": "Databases"}
    assert len(fake.requests) == before  # autocomplete never calls arXiv


def test_suggest_index_rebuilt_on_restart(fake, clock, tmp_path):
    from fastapi.testclient import TestClient
    from app.main import app, build_service
    import httpx as _httpx

    async def factory():
        http = _httpx.AsyncClient(transport=_httpx.MockTransport(fake.handler))
        return await build_service(database_url=f"sqlite+aiosqlite:///{tmp_path}/restart.db",
                                   rate_limiter="process", interval_s=0, http=http, clock=clock)

    app.state.service_factory = factory
    try:
        with TestClient(app) as c:
            c.get("/api/browse/cs.DB")
        with TestClient(app) as c:  # new process: tries are warmed from the database
            assert c.get("/api/stats").json()["suggest_index"]["author"] == 100
    finally:
        del app.state.service_factory


def test_trending_uses_topk(client):
    for _ in range(3):
        client.get("/api/browse/cs.LG")
    client.get("/api/browse/cs.DB")
    client.get("/api/search", params={"q": "graphs"})
    client.get("/api/search", params={"q": "graphs"})
    r = client.get("/api/trending", params={"k": 2}).json()
    assert r["trending"] == [{"query": "cs.LG", "count": 3}, {"query": "graphs", "count": 2}]


def test_new_since_uses_binary_search_on_cached_window(client, fake):
    from tests.conftest import published_at

    since = published_at(30).isoformat()  # results 0..29 are newer
    r = client.get("/api/browse/cs.DB/new", params={"since": since, "limit": 5}).json()
    assert (r["new_count"], r["has_more"]) == (30, False)
    assert [a["arxiv_id"] for a in r["results"]] == [aid(n) for n in range(5)]
    p = fake.params()
    assert (p["sortBy"], p["sortOrder"], p["max_results"]) == ("submittedDate", "descending", "100")

    r = client.get("/api/browse/cs.DB/new", params={"since": published_at(500).isoformat()}).json()
    assert (r["new_count"], r["has_more"]) == (100, True)  # whole window is new
    assert len(fake.requests) == 1  # second check reused the cached window
    assert client.get("/api/browse/nope/new", params={"since": since}).status_code == 404


def test_per_client_rate_limit_returns_429(client):
    from app.dsa.rate_window import SlidingWindowLimiter
    client.app.state.client_limiter = SlidingWindowLimiter(limit=3, window_s=60)
    codes = [client.get("/api/categories").status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    r = client.get("/api/categories")
    assert r.status_code == 429 and int(r.headers["Retry-After"]) >= 59
    assert client.get("/health").status_code == 200  # only /api/* is limited
