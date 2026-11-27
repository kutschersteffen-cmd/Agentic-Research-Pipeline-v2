from __future__ import annotations

from arp.db.engine import (  # noqa: F401
    _CONNECT_TIMEOUT_SECONDS,
    PostgresExtraNotInstalled,
    get_engine,
)


def ensure_schema(dsn: str) -> dict:
    """Brings a database up to what this codebase's Postgres models define
    -- the pgvector extension, missing tables, missing columns, and any
    unapplied schema step -- idempotently, like every other "bring your own
    external store" setup step here (see e.g. DocumentContentStore's
    CREATE TABLE IF NOT EXISTS). Call once per deployment of a schema
    change (`arp db init-postgres`), not per request.

    Lives in arp/storage/postgres_schema.py, which also offers the
    read-only `schema_report` behind `arp db check-postgres`; re-exported
    here because every existing caller imports it from this module.
    """
    from arp.storage.postgres_schema import ensure_schema as _ensure_schema

    return _ensure_schema(dsn)
