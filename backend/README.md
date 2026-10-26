# Scholarly Insight: Backend (mid-program)

FastAPI service that searches and browses arXiv. Every hot path is built on a
data structure from the bootcamp, implemented by hand in `app/dsa/` and tested
against a brute-force oracle.

## Run it

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest                        # 122 tests, no network needed (~5s)
python -m scripts.smoke_live  # optional: checks the real arXiv API (~10s)
uvicorn app.main:app --reload # or --workers 4: the rate limiter is shared
```

Open http://localhost:8000/docs for interactive Swagger docs.

## Bootcamp topics in the code

| Week | Topic | Where | Problem it mirrors | Why it is here |
|---|---|---|---|---|
| 1 | Hash maps | single-flight map, id batcher, query counts | Two Sum style lookups | O(1) "is this already in flight?" |
| 1 + 6 | Hash map + linked list | `dsa/lru.py` L1 cache | LC 146 LRU Cache | O(1) get/put/evict for hot windows |
| 2 | Sorting + binary search | `dsa/search.py`, `/api/browse/{cat}/new` | LC 35 Search Insert Position | "how many new since X" in O(log n), no arXiv call |
| 2 | Queue | `dsa/rate_window.py` per-client limiter | LC 933 Number of Recent Calls | stop one client draining our arXiv budget |
| 3 | Strings + trie | `dsa/trie.py`, `/api/suggest` | LC 642 Autocomplete System | O(prefix) suggestions, top-k cached per node |
| 3 | Stack | `dsa/query_parser.py`, `/api/search?query=` | LC 20 / 224 | parse `(a OR b) NOT c`, validate parentheses |
| 4 | Heap | `dsa/topk.py`, `/api/trending` | LC 347 Top K Frequent | O(n log k) trending searches |
| 4 | Greedy | windows + id batcher | Interval cover / bin packing | fewest arXiv calls that cover a request |
| 8 | DP | `dsa/edit_distance.py`, "did you mean" | LC 72 Edit Distance | typo-tolerant author/term suggestions |

## Endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/api/search` | Filters `q`, `title`, `author`, `abstract`, `category`, `date_from`, `date_to`, plus boolean `query`; `sort_by`, `sort_order`, `page`, `page_size` |
| GET | `/api/browse/{category}` | Newest papers in a category (`cs.DB`) or archive (`cs`) |
| GET | `/api/browse/{category}/new?since=` | Count and list of papers submitted after a time |
| GET | `/api/articles/{id}` | Abstract, PDF, DOI. Accepts `2410.01234`, `2410.01234v2`, `hep-ex/0307015` |
| GET | `/api/suggest?prefix=&kind=` | Autocomplete for `author`, `term` or `category` |
| GET | `/api/trending?k=` | Most requested searches |
| GET | `/api/categories` | Category groups for menus |
| GET | `/api/stats` | Cache tiers, hit rate, upstream calls |

### Demo requests

```bash
curl "localhost:8000/api/search?query=(transformer%20OR%20%22state%20space%22)%20NOT%20title:survey&category=cs.LG"
curl "localhost:8000/api/browse/cs.LG?page=2"      # same window as page 1: no arXiv call
curl "localhost:8000/api/suggest?prefix=lec&kind=author"
curl "localhost:8000/api/browse/cs.LG/new?since=2026-10-22T00:00:00Z"
curl "localhost:8000/api/articles/1706.03762"
curl "localhost:8000/api/trending"
curl "localhost:8000/api/stats"
```

## Data fetching strategy

```
request ──> per-client queue limiter ──> L1 LRU (per worker) ──> L2 database ──> arXiv
                                              hit: ~0 ms            hit: ~2 ms     miss: 3 s slot + latency
```

1. **Windows.** arXiv is called for aligned blocks of 100 results; any page is sliced
   from one or two windows. Paging 1 to 5 at 20 per page costs one call, not five.
2. **Single-flight.** Concurrent misses for the same window share one in-flight task
   (hash map of key to task), so 20 users hitting a cold page cost one call.
3. **Freshness tied to arXiv's schedule.** arXiv publishes once a day, so data is fresh
   until the next midnight US Eastern. After that it is served stale instantly while
   one background task refreshes it (stale-while-revalidate, up to 7 days).
4. **Shared rate limiter.** One atomic `UPDATE ... RETURNING` reserves the next 3 s slot
   in the database, so 4 workers or 2 servers still respect arXiv's limit together.
5. **Batched details.** Detail misses within 25 ms are merged into one `id_list` call
   (up to 100 ids). Details for anything already listed are a local read.
6. **Transport.** gzip responses, `Cache-Control` so browsers reuse fresh results,
   `X-Cache` header showing which tier answered.
7. **Correctness.** Version-less ids (v1/v2 never duplicate), arXiv's transient empty
   pages retried once and never cached, errors mapped to 400/404/422/429/502.

## Schema

Used now: `articles`, `cache_windows`, `rate_limits`.
Modeled for weeks 6 to 8: `users` (Firebase uid), `saved_articles`, `reading_history`,
`alert_subscriptions`, `forum_threads`, `forum_comments`.
SQLite (WAL) locally; set `DATABASE_URL=postgresql+asyncpg://...` for deployment
(`pip install asyncpg`).

## Config (env vars)

`ARXIV_MIN_INTERVAL_S` (3.0), `RATE_LIMITER` (db | process), `WINDOW_SIZE` (100),
`REFRESH_TZ` (America/New_York), `STALE_MAX_S` (604800), `L1_WINDOWS` (512),
`BATCH_WINDOW_MS` (25), `CLIENT_RATE_LIMIT` (120 per `CLIENT_RATE_WINDOW_S`=60),
`DATABASE_URL`, `ARXIV_BASE_URL`, `USER_AGENT`.

## Next

- Frontend: search box wired to `/api/suggest`, results, details
- Firebase Auth, saved articles, reading history
- Alerts: daily job per subscription using `/new?since=last_checked`
- Trees and graphs week: related papers by co-author graph (BFS)
- Deploy with Postgres

---
Thank you to arXiv for use of its open access interoperability.
