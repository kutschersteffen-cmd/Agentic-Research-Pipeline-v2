"""Pure leaf SQLAlchemy Engine cache for Postgres.

Kept separate from `arp.storage.postgres_schema` and `arp.db.session` so low-level
repositories (such as `JsonDocumentRepo`) can open sessions without introducing
import cycles into the schema migration layer.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from arp.errors import NotConfigured

if TYPE_CHECKING:
    from sqlalchemy import Engine


class PostgresExtraNotInstalled(NotConfigured):
    def __init__(self, exc: Exception) -> None:
        super().__init__(
            "sqlalchemy/psycopg/pgvector aren't installed; they are required dependencies: "
            f"pip install -e . Original import error: {exc}"
        )


_CONNECT_TIMEOUT_SECONDS = 10


@lru_cache
def get_engine(dsn: str) -> Engine:
    """One pooled Engine per DSN for the process lifetime."""
    try:
        from sqlalchemy import create_engine
    except ImportError as exc:  # pragma: no cover - exercised only without the optional extra
        raise PostgresExtraNotInstalled(exc) from exc
    from arp.config import get_settings

    settings = get_settings()
    connect_args = {} if "connect_timeout" in dsn else {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}
    return create_engine(
        dsn,
        pool_pre_ping=True,
        connect_args=connect_args,
        pool_size=settings.postgres_pool_size,
        max_overflow=settings.postgres_max_overflow,
    )
