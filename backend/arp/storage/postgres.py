"""Compatibility re-export; canonical home is `arp.db.postgres`."""

from arp.db.postgres import (
    _CONNECT_TIMEOUT_SECONDS,
    PostgresExtraNotInstalled,
    ensure_schema,
    get_engine,
)

__all__ = [
    "_CONNECT_TIMEOUT_SECONDS",
    "PostgresExtraNotInstalled",
    "ensure_schema",
    "get_engine",
]
