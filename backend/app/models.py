"""Database schema.

Search/browse/details use: Article, CacheWindow, RateLimit.
User features (weeks 5-7) are modeled now so the schema is stable:
User (Firebase uid), SavedArticle, ReadingHistory, AlertSubscription,
ForumThread, ForumComment.

Cache timestamps are epoch seconds (floats) so expiry math is identical on
SQLite and Postgres.
"""
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Article(Base):
    """Normalized arXiv metadata, keyed by version-less id (e.g. 2401.01234)."""

    __tablename__ = "articles"

    arxiv_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    latest_version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    authors: Mapped[list] = mapped_column(JSON)  # [{"name", "affiliation"}]
    primary_category: Mapped[str | None] = mapped_column(String(32), index=True)
    categories: Mapped[list] = mapped_column(JSON)
    published: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    abs_url: Mapped[str] = mapped_column(String(255))
    pdf_url: Mapped[str | None] = mapped_column(String(255))
    doi: Mapped[str | None] = mapped_column(String(255))
    journal_ref: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[float] = mapped_column(Float)


class CacheWindow(Base):
    """One arXiv call's worth of results (window_size ids) for a query + sort."""

    __tablename__ = "cache_windows"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(query, window_start)
    query_key: Mapped[str] = mapped_column(Text)
    window_start: Mapped[int] = mapped_column(Integer)
    total_results: Mapped[int] = mapped_column(Integer)
    article_ids: Mapped[list] = mapped_column(JSON)
    fetched_at: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[float] = mapped_column(Float, index=True)


class RateLimit(Base):
    """Next free upstream slot, shared by every worker and instance."""

    __tablename__ = "rate_limits"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    next_at: Mapped[float] = mapped_column(Float, default=0.0)


class User(Base):
    __tablename__ = "users"

    uid: Mapped[str] = mapped_column(String(128), primary_key=True)  # Firebase uid
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class SavedArticle(Base):
    __tablename__ = "saved_articles"
    __table_args__ = (UniqueConstraint("user_uid", "arxiv_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_uid: Mapped[str] = mapped_column(ForeignKey("users.uid", ondelete="CASCADE"), index=True)
    arxiv_id: Mapped[str] = mapped_column(ForeignKey("articles.arxiv_id"))
    saved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReadingHistory(Base):
    __tablename__ = "reading_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_uid: Mapped[str] = mapped_column(ForeignKey("users.uid", ondelete="CASCADE"), index=True)
    arxiv_id: Mapped[str] = mapped_column(ForeignKey("articles.arxiv_id"))
    viewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class AlertSubscription(Base):
    """Notify a user about new papers matching a category and/or keyword."""

    __tablename__ = "alert_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_uid: Mapped[str] = mapped_column(ForeignKey("users.uid", ondelete="CASCADE"), index=True)
    category: Mapped[str | None] = mapped_column(String(32), index=True)
    keyword: Mapped[str | None] = mapped_column(String(255))
    channel: Mapped[str] = mapped_column(String(16), default="email")  # email | in_app
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ForumThread(Base):
    __tablename__ = "forum_threads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    arxiv_id: Mapped[str] = mapped_column(ForeignKey("articles.arxiv_id"), index=True)
    author_uid: Mapped[str] = mapped_column(ForeignKey("users.uid"))
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ForumComment(Base):
    __tablename__ = "forum_comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    thread_id: Mapped[int] = mapped_column(ForeignKey("forum_threads.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("forum_comments.id"))
    author_uid: Mapped[str] = mapped_column(ForeignKey("users.uid"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
