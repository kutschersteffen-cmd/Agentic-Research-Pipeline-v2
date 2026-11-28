"""Add signal_items, signal_scans (with health metrics), and desk_uploads tables.

Revision ID: 0002_signal_store_desk_uploads
Revises: 0001_baseline
Create Date: 2026-11-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Kept <= 32 chars so it fits Alembic's default `alembic_version.version_num VARCHAR(32)` column.
revision: str = "0002_signal_store_desk_uploads"
down_revision: str | Sequence[str] | None = "0001_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Idempotently create signal_items, signal_scans (incl. slice-d cols), and desk_uploads."""
    op.create_table(
        "signal_items",
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_type", sa.String(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("raw_entity_names", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at_is_estimated", sa.Boolean(), nullable=False),
        sa.Column("item_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("content_hash"),
        if_not_exists=True,
    )
    op.create_index("ix_signal_items_item_at", "signal_items", ["item_at"], unique=False, if_not_exists=True)

    op.create_table(
        "signal_scans",
        sa.Column("scan_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("run_id", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("items_fetched", postgresql.JSONB(), nullable=False),
        sa.Column("items_new", postgresql.JSONB(), nullable=False),
        sa.Column("fetch_failures", postgresql.JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("lag_hours", postgresql.JSONB(), nullable=True, server_default=sa.text("'{}'::jsonb")),
        sa.Column("unclustered_share", sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint("scan_id"),
        if_not_exists=True,
    )
    op.create_index("ix_signal_scans_finished_at", "signal_scans", ["finished_at"], unique=False, if_not_exists=True)
    # Reconcile legacy signal_scans tables created before slice-d health columns existed (AC-41).
    op.execute(
        "ALTER TABLE signal_scans "
        "ADD COLUMN IF NOT EXISTS fetch_failures JSONB DEFAULT '{}'::jsonb, "
        "ADD COLUMN IF NOT EXISTS lag_hours JSONB DEFAULT '{}'::jsonb, "
        "ADD COLUMN IF NOT EXISTS unclustered_share DOUBLE PRECISION"
    )

    op.create_table(
        "desk_uploads",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="reading"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("full_text", sa.Text(), nullable=True),
        sa.Column("page_breaks", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("detected_company_id", sa.Text(), nullable=True),
        sa.Column("detection", sa.Text(), nullable=False, server_default="none"),
        sa.Column("saved_company_id", sa.Text(), nullable=True),
        sa.Column("saved_doc_type", sa.Text(), nullable=True),
        sa.Column("saved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["chat_id"], ["desk_chats.id"]),
        sa.PrimaryKeyConstraint("id"),
        if_not_exists=True,
    )
    op.create_index("ix_desk_uploads_chat_id", "desk_uploads", ["chat_id"], unique=False, if_not_exists=True)
    op.create_index("ix_desk_uploads_created_at", "desk_uploads", ["created_at"], unique=False, if_not_exists=True)


def downgrade() -> None:
    """Drop the tables introduced by revision 0002."""
    op.drop_table("desk_uploads", if_exists=True)
    op.drop_table("signal_scans", if_exists=True)
    op.drop_table("signal_items", if_exists=True)
