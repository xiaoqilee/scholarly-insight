from datetime import date

import pytest

from app.arxiv_client import (
    ArxivError,
    ArxivRequest,
    build_search_query,
    parse_arxiv_id,
    parse_feed,
)
from tests.conftest import fixture


class TestIds:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("2410.01234", ("2410.01234", None)),
            ("2410.01234v3", ("2410.01234", 3)),
            ("http://arxiv.org/abs/2410.01234v2", ("2410.01234", 2)),
            ("arXiv:0706.0001", ("0706.0001", None)),
            ("hep-ex/0307015v1", ("hep-ex/0307015", 1)),
            ("math.GT/0309136", ("math.GT/0309136", None)),
        ],
    )
    def test_valid(self, raw, expected):
        assert parse_arxiv_id(raw) == expected

    @pytest.mark.parametrize("raw", ["", "1234.1", "not-an-id", "2410.01234vX", "../etc/passwd"])
    def test_invalid(self, raw):
        with pytest.raises(ValueError):
            parse_arxiv_id(raw)


class TestQueryBuilder:
    def test_single_word(self):
        assert build_search_query(q="transformer") == "all:transformer"

    def test_phrase_is_quoted_and_whitespace_normalized(self):
        assert build_search_query(author="  Yann   LeCun ") == 'au:"Yann LeCun"'

    def test_user_quotes_are_stripped(self):
        assert build_search_query(title='"graph neural"') == 'ti:"graph neural"'

    def test_quotes_only_rejected(self):
        with pytest.raises(ValueError):
            build_search_query(title='""')

    def test_combined_filters_are_anded(self):
        sq = build_search_query(
            author="Hinton", category="cs.LG",
            date_from=date(2024, 1, 1), date_to=date(2024, 12, 31),
        )
        assert sq == "au:Hinton AND cat:cs.LG AND submittedDate:[202401010000 TO 202412312359]"

    def test_archive_only_category_uses_wildcard(self):
        assert build_search_query(category="cs") == "cat:cs.*"

    def test_open_ended_date_range(self):
        assert build_search_query(date_from=date(2026, 10, 1)).startswith("submittedDate:[202610010000 TO ")

    def test_rejects_inverted_dates(self):
        with pytest.raises(ValueError):
            build_search_query(date_from=date(2025, 1, 2), date_to=date(2025, 1, 1))

    def test_rejects_empty(self):
        with pytest.raises(ValueError):
            build_search_query()

    def test_rejects_injection_in_category(self):
        with pytest.raises(ValueError):
            build_search_query(category="cs.DB OR all:x")


class TestRequest:
    def test_params(self):
        p = ArxivRequest(search_query="cat:cs.DB", start=20, max_results=10,
                         sort_by="submittedDate").params()
        assert p == {"search_query": "cat:cs.DB", "start": "20", "max_results": "10",
                     "sortBy": "submittedDate", "sortOrder": "descending"}

    def test_paging_limit(self):
        with pytest.raises(ValueError):
            ArxivRequest(search_query="x", start=29_990, max_results=20)

    def test_bad_sort(self):
        with pytest.raises(ValueError):
            ArxivRequest(search_query="x", sort_by="citations")


class TestParser:
    def test_feed_metadata(self):
        feed = parse_feed(fixture("search_feed.xml"))
        assert (feed.total_results, feed.start_index, feed.items_per_page) == (48213, 0, 2)
        assert len(feed.articles) == 2

    def test_entry_fields(self):
        a = parse_feed(fixture("search_feed.xml")).articles[0]
        assert a.arxiv_id == "2410.01234" and a.version == 2
        assert a.title == "Cost-Based Ordering of Semantic Filters in LLM-Powered Query Pipelines"
        assert a.summary.startswith("We study the problem") and "\n" not in a.summary
        assert a.authors == [
            {"name": "Ada Lovelace", "affiliation": "NYU"},
            {"name": "Edgar F. Codd", "affiliation": None},
        ]
        assert a.primary_category == "cs.DB"
        assert a.categories == ["cs.DB", "cs.LG"]
        assert a.pdf_url == "https://arxiv.org/pdf/2410.01234v2"
        assert a.doi == "10.1145/1234567.7654321"
        assert a.journal_ref == "Proc. VLDB 19 (2026)"
        assert a.comment == "14 pages, 6 figures"
        assert a.published.tzinfo is not None and a.updated > a.published

    def test_old_style_id_and_https_upgrade(self):
        a = parse_feed(fixture("search_feed.xml")).articles[1]
        assert a.arxiv_id == "hep-ex/0307015"
        assert a.abs_url.startswith("https://") and a.pdf_url.startswith("https://")
        assert a.doi is None

    def test_error_feed_raises(self):
        with pytest.raises(ArxivError, match="incorrect id format"):
            parse_feed(fixture("error_feed.xml"))
