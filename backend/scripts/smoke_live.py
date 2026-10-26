"""Hit the REAL arXiv API through our client. Run before the demo:

    python -m scripts.smoke_live

Takes ~10s because of the 3s politeness delay between calls.
"""
import asyncio
from datetime import date

from app.arxiv_client import ArxivClient, ArxivRequest, build_search_query
from app.ratelimit import ProcessLimiter


async def main():
    client = ArxivClient(ProcessLimiter(3.0))
    checks = [
        ("browse cs.DB newest", ArxivRequest(
            search_query=build_search_query(category="cs.DB"),
            max_results=100, sort_by="submittedDate")),
        ("author + date range", ArxivRequest(
            search_query=build_search_query(author="Yann LeCun", date_from=date(2020, 1, 1)),
            max_results=5, sort_by="submittedDate")),
        ("boolean query", ArxivRequest(
            search_query=build_search_query(advanced='(transformer OR "state space") NOT title:survey',
                                            category="cs.LG"),
            max_results=5)),
        ("detail by id", ArxivRequest(id_list=("1706.03762",), max_results=1)),
    ]
    ok = True
    for label, req in checks:
        try:
            feed = await client.fetch(req)
            first = feed.articles[0] if feed.articles else None
            print(f"[ok] {label}: total={feed.total_results} returned={len(feed.articles)} "
                  f"first={first.arxiv_id + ' ' + first.title[:50] if first else None}")
            ok &= bool(first)
        except Exception as e:  # noqa: BLE001
            ok = False
            print(f"[FAIL] {label}: {e}")
    await client.aclose()
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
