"""Programmatic Alembic migration helpers used by `arp db upgrade` / `arp db current`."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, pool

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"
ALEMBIC_DIR = _BACKEND_ROOT / "migrations"


def alembic_config(dsn: str) -> Config:
    """Build an Alembic Config bound to `dsn` without ConfigParser `%`-interpolation issues."""
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.attributes["dsn"] = dsn
    cfg.attributes["configure_logger"] = False
    return cfg


def upgrade_head(dsn: str) -> None:
    """Apply all pending Alembic migrations up to `head`."""
    command.upgrade(alembic_config(dsn), "head")


def stamp_head(dsn: str) -> None:
    """Stamp an already-initialized database at Alembic `head` without running DDL."""
    command.stamp(alembic_config(dsn), "head")


def current_revision(dsn: str) -> str | None:
    """Return the currently recorded Alembic revision in `alembic_version`, or None."""
    engine = create_engine(dsn, poolclass=pool.NullPool)
    try:
        with engine.connect() as conn:
            return MigrationContext.configure(conn).get_current_revision()
    finally:
        engine.dispose()
