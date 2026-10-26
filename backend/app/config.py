"""Runtime settings, overridable with environment variables."""
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    arxiv_base_url: str = os.getenv("ARXIV_BASE_URL", "https://export.arxiv.org/api/query")
    # arXiv asks clients to wait ~3s between consecutive calls.
    arxiv_min_interval_s: float = float(os.getenv("ARXIV_MIN_INTERVAL_S", "3.0"))
    arxiv_timeout_s: float = float(os.getenv("ARXIV_TIMEOUT_S", "20"))
    # "db" shares one limiter across every worker/instance via the database.
    # "process" is in-memory only (fine for a single uvicorn worker).
    rate_limiter: str = os.getenv("RATE_LIMITER", "db")

    # Results fetched per arXiv call. Pages are sliced out of these windows,
    # so paging through 5 pages of 20 costs one upstream call, not five.
    window_size: int = int(os.getenv("WINDOW_SIZE", "100"))
    # arXiv publishes once a day; cached data is fresh until the next midnight here.
    refresh_tz: str = os.getenv("REFRESH_TZ", "America/New_York")
    # Past freshness, serve stale data instantly and refresh in the background
    # for up to this long. Older than this: fetch before responding.
    stale_max_s: int = int(os.getenv("STALE_MAX_S", str(7 * 86400)))
    # In-process LRU in front of the database (per worker).
    l1_windows: int = int(os.getenv("L1_WINDOWS", "512"))
    # Detail lookups that miss arrive within this window are sent as one id_list call.
    batch_window_ms: int = int(os.getenv("BATCH_WINDOW_MS", "25"))
    max_ids_per_call: int = 100
    # Per-client budget for our own API (sliding window), protects arXiv quota.
    client_rate_limit: int = int(os.getenv("CLIENT_RATE_LIMIT", "120"))
    client_rate_window_s: float = float(os.getenv("CLIENT_RATE_WINDOW_S", "60"))
    # Articles loaded into the autocomplete index at startup (most recent first).
    suggest_preload: int = int(os.getenv("SUGGEST_PRELOAD", "20000"))

    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./scholarly_insight.db")
    max_page_size: int = 100
    max_offset: int = 30000  # arXiv hard limit on start + max_results
    user_agent: str = os.getenv("USER_AGENT", "ScholarlyInsight/0.2 (student project; NYU)")

    def __post_init__(self):
        if self.max_offset % self.window_size or self.window_size < self.max_page_size:
            raise ValueError("WINDOW_SIZE must divide 30000 and be >= max page size (100)")
        if self.rate_limiter not in {"db", "process"}:
            raise ValueError("RATE_LIMITER must be 'db' or 'process'")


settings = Settings()
