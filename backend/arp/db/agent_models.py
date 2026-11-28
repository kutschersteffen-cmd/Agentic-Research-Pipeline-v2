"""ORM models for Agent explorations and the Agent Board (`agent_explorations`, `agent_board_blocks`, `agent_board_versions`)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from arp.db.postgres_models import Base


class AgentExploration(Base):
    __tablename__ = "agent_explorations"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    question: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # done | failed | timeout
    result: Mapped[object | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[list] = mapped_column(JSONB)  # [{capability_id, args, result_bytes}]
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_ask_id: Mapped[str | None] = mapped_column(Text, ForeignKey("agent_asks.id"), nullable=True)  # Phase 7, D11
    miniapp_html: Mapped[str | None] = mapped_column(Text, nullable=True)  # Phase 5: written by "Show as mini-app"
    miniapp_asks: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)  # its follow-up questions


class AgentBoardBlock(Base):
    __tablename__ = "agent_board_blocks"
    __table_args__ = (Index("ix_agent_board_blocks_board", "thread_kind", "thread_id", "position"),)

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    thread_kind: Mapped[str] = mapped_column(Text)  # plan | exploration
    thread_id: Mapped[str] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(Text)  # note | table | chart | flow
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[object] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer)
    origin: Mapped[str] = mapped_column(Text)  # person | agent
    unverified: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AgentBoardVersion(Base):
    __tablename__ = "agent_board_versions"

    block_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[object] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(Text)
    unverified: Mapped[list] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
