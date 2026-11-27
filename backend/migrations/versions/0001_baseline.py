"""Baseline Postgres schema preserving all existing ORM tables (including desk_*).

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0001_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Converge fresh or pre-Alembic databases idempotently to the current ORM schema."""
    bind = op.get_bind()
    dsn = bind.engine.url.render_as_string(hide_password=False)
    from arp.storage.postgres_schema import ensure_schema

    ensure_schema(dsn)


def downgrade() -> None:
    raise NotImplementedError("Cannot downgrade past 0001_baseline; drop the database explicitly if resetting.")
