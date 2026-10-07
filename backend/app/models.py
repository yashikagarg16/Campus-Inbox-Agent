"""Database tables. SQLite locally, PostgreSQL in production (same code).

Schema changes go through Alembic: edit this file, then
    alembic revision --autogenerate -m "what changed"
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool

from .schemas import local_now

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Base(DeclarativeBase):
    pass


class ProfileRow(Base):
    __tablename__ = "profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, onupdate=local_now)


class EmailRow(Base):
    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str | None] = mapped_column(String(500))
    sender: Mapped[str | None] = mapped_column(String(320))
    message_id: Mapped[str | None] = mapped_column(String(500), index=True)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(20), default="paste")  # paste | eml | imap
    raw_text: Mapped[str] = mapped_column(Text)
    cleaned_text: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="received")  # received | extracted | failed
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)

    opportunities: Mapped[list["OpportunityRow"]] = relationship(
        back_populates="email", cascade="all, delete-orphan", order_by="OpportunityRow.position"
    )


class OpportunityRow(Base):
    __tablename__ = "opportunities"

    id: Mapped[int] = mapped_column(primary_key=True)
    email_id: Mapped[int] = mapped_column(ForeignKey("emails.id"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)  # order within a digest email
    company: Mapped[str | None] = mapped_column(String(300))
    role: Mapped[str | None] = mapped_column(String(300))
    deadline: Mapped[datetime | None] = mapped_column(DateTime)
    form_link: Mapped[str | None] = mapped_column(Text)
    extraction: Mapped[dict[str, Any]] = mapped_column(JSON)  # guarded: rejected fields blanked
    issues: Mapped[list[Any]] = mapped_column(JSON, default=list)
    spans: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)

    email: Mapped[EmailRow] = relationship(back_populates="opportunities")
    rules: Mapped[list["RuleRow"]] = relationship(back_populates="opportunity", cascade="all, delete-orphan")
    decisions: Mapped[list["DecisionRow"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", order_by="DecisionRow.id"
    )
    drafts: Mapped[list["DraftRow"]] = relationship(
        back_populates="opportunity", cascade="all, delete-orphan", order_by="DraftRow.id"
    )


class RuleRow(Base):
    __tablename__ = "rules"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    rule_type: Mapped[str] = mapped_column(String(50))
    value: Mapped[Any] = mapped_column(JSON)
    evidence: Mapped[str | None] = mapped_column(Text)
    span_start: Mapped[int | None] = mapped_column(Integer)
    span_end: Mapped[int | None] = mapped_column(Integer)

    opportunity: Mapped[OpportunityRow] = relationship(back_populates="rules")


class DecisionRow(Base):
    """One row per evaluation; the latest is current. Kept as history."""

    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    verdict: Mapped[str] = mapped_column(String(20))
    result: Mapped[dict[str, Any]] = mapped_column(JSON)  # full Decision
    profile_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)

    opportunity: Mapped[OpportunityRow] = relationship(back_populates="decisions")


class DraftRow(Base):
    """An LLM-drafted answer to a form question. Only ever shown to you; never submitted."""

    __tablename__ = "drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved
    warnings: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=local_now, onupdate=local_now)

    opportunity: Mapped[OpportunityRow] = relationship(back_populates="drafts")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event: Mapped[str] = mapped_column(String(50))
    email_id: Mapped[int | None] = mapped_column(ForeignKey("emails.id"), index=True)
    opportunity_id: Mapped[int | None] = mapped_column(ForeignKey("opportunities.id"), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=local_now)


def _is_memory_sqlite(url: str) -> bool:
    return url in ("sqlite://", "sqlite:///:memory:") or ":memory:" in url


def run_migrations(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    cfg.attributes["url_set_by_app"] = True
    command.upgrade(cfg, "head")


def make_sessionmaker(database_url: str, migrate: bool = True) -> sessionmaker:
    kwargs: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if _is_memory_sqlite(database_url):
            kwargs["poolclass"] = StaticPool
    engine: Engine = create_engine(database_url, **kwargs)
    if _is_memory_sqlite(database_url):
        Base.metadata.create_all(engine)  # tests: a fresh throwaway database
    elif migrate:
        run_migrations(database_url)
    return sessionmaker(engine, expire_on_commit=False)
