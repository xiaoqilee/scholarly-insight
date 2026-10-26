from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class Author(BaseModel):
    name: str | None
    affiliation: str | None = None


class ArticleSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    arxiv_id: str
    latest_version: int
    title: str
    authors: list[Author]
    primary_category: str | None
    published: datetime
    updated: datetime
    abs_url: str
    pdf_url: str | None

    @field_validator("published", "updated")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)  # SQLite drops tz


class ArticleDetail(ArticleSummary):
    summary: str
    categories: list[str]
    doi: str | None
    journal_ref: str | None
    comment: str | None


Source = Literal["l1", "db", "stale", "arxiv"]


class Page(BaseModel):
    total_results: int
    page: int
    page_size: int
    total_pages: int
    source: Source
    cached: bool
    stale: bool
    query: str
    results: list[ArticleSummary]


class Detail(BaseModel):
    source: Source
    cached: bool
    stale: bool
    article: ArticleDetail
