"""Tests for Alembic configuration, baseline migration, and `arp db` migration commands."""

from __future__ import annotations

from alembic.script import ScriptDirectory
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


def test_alembic_upgrade_and_cli_roundtrip(pg):
    upgrade_head(pg)
    assert current_revision(pg) == "0001_baseline"

    # Idempotent re-run leaves head intact.
    upgrade_head(pg)
    assert current_revision(pg) == "0001_baseline"

    stamp_head(pg)
    assert current_revision(pg) == "0001_baseline"

    runner = CliRunner()
    res_cur = runner.invoke(db_app, ["current"])
    assert res_cur.exit_code == 0, res_cur.output
    assert "0001_baseline" in res_cur.output

    res_up = runner.invoke(db_app, ["upgrade"])
    assert res_up.exit_code == 0, res_up.output
    assert "0001_baseline" in res_up.output

    res_stamp = runner.invoke(db_app, ["stamp-head"])
    assert res_stamp.exit_code == 0, res_stamp.output
    assert "0001_baseline" in res_stamp.output
