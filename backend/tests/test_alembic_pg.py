"""Tests for Alembic configuration, baseline migration, and `arp db` migration commands."""

from __future__ import annotations

from io import StringIO

from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, pool, text
from typer.testing import CliRunner

import arp.db.models  # noqa: F401 - register ORM models
from arp.cli.db import db_app
from arp.db.migrations import ALEMBIC_DIR, ALEMBIC_INI, alembic_config, current_revision, stamp_head, upgrade_head
from arp.storage.postgres_models import Base


def test_alembic_config_and_baseline_script_metadata():
    assert ALEMBIC_INI.is_file()
    assert ALEMBIC_DIR.is_dir()

    dsn = "postgresql+psycopg://user:p%40ss@localhost/arp"
    cfg = alembic_config(dsn)
    assert cfg.attributes["dsn"] == dsn

    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == ["0001_baseline"]

    tables = set(Base.metadata.tables.keys())
    assert {"companies", "runs", "fields", "desk_chats", "desk_scope", "desk_turns"} <= tables

    # Offline SQL generation must succeed without connecting to Postgres.
    buf = StringIO()
    offline_cfg = alembic_config(dsn)
    offline_cfg.output_buffer = buf
    command.upgrade(offline_cfg, "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE TABLE" in sql and "0001_baseline" in sql


def test_alembic_upgrade_from_unversioned_and_fresh_schema(pg):
    # 1. Start from unversioned state by dropping alembic_version if present.
    eng = create_engine(pg, poolclass=pool.NullPool)
    try:
        with eng.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        assert current_revision(pg) is None

        runner = CliRunner()
        res_unver = runner.invoke(db_app, ["current"])
        assert res_unver.exit_code == 0, res_unver.output
        assert "unversioned" in res_unver.output

        # 2. Run 0001_baseline against a completely fresh scratch Postgres schema on a caller-supplied connection.
        scratch = "alembic_fresh_test"
        with eng.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {scratch} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {scratch}"))
            conn.commit()
        try:
            with eng.connect() as conn:
                conn.execute(text(f"SET search_path TO {scratch}, public"))
                conn.commit()
                cfg = alembic_config(pg)
                cfg.attributes["connection"] = conn
                command.upgrade(cfg, "head")
                created = set(inspect(conn).get_table_names(schema=scratch))
                assert {"companies", "runs", "fields", "desk_chats", "desk_scope", "desk_turns", "alembic_version"} <= created
        finally:
            with eng.begin() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {scratch} CASCADE"))
    finally:
        eng.dispose()

    # 3. Full CLI & programmatic upgrade/idempotency/stamp round-trip on the main test DB.
    upgrade_head(pg)
    assert current_revision(pg) == "0001_baseline"

    upgrade_head(pg)
    assert current_revision(pg) == "0001_baseline"

    stamp_head(pg)
    assert current_revision(pg) == "0001_baseline"

    runner = CliRunner()
    for args in (["current"], ["upgrade"], ["stamp-head"]):
        res = runner.invoke(db_app, args)
        assert res.exit_code == 0, res.output
        assert "0001_baseline" in res.output
