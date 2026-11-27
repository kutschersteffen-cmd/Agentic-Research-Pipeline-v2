"""Baseline Postgres schema preserving all existing ORM tables (including desk_*).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import context, op

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Converge fresh or pre-Alembic databases idempotently to the current ORM schema."""
    bind = op.get_bind()
    if context.is_offline_mode():
        import arp.db.models  # noqa: F401
        from arp.storage.postgres_models import Base

        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        Base.metadata.create_all(bind=bind)
        return

    from arp.storage.postgres_schema import ensure_schema_on_connection

    ensure_schema_on_connection(bind)


def downgrade() -> None:
    raise NotImplementedError("Cannot downgrade past 0001_baseline; drop the database explicitly if resetting.")
