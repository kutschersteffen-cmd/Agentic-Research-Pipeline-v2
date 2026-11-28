"""Tests for Alembic configuration, linear revision chain, `0002` migration, and `arp db` commands."""

from __future__ import annotations

from datetime import UTC, datetime
from io import StringIO

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, make_url, pool, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

import arp.db.models as db_models
import arp.storage.postgres_models as storage_postgres_models
from arp.cli.db import db_app
from arp.db.migrations import ALEMBIC_DIR, ALEMBIC_INI, alembic_config, current_revision, stamp_head, upgrade_head
from arp.db.postgres_schema import ensure_schema, ensure_schema_on_connection, schema_report
from arp.storage.postgres_models import Base, SignalItemModel, SignalScanModel

BASELINE_REV = "0001_baseline"
HEAD_REV = "0002_signal_store_desk_uploads"
M2_TABLES = {"signal_items", "signal_scans", "desk_uploads"}


def test_alembic_config_and_baseline_script_metadata():
    assert ALEMBIC_INI.is_file()
    assert ALEMBIC_DIR.is_dir()

    dsn = "postgresql+psycopg://user:p%40ss@localhost/arp"
    cfg = alembic_config(dsn)
    assert cfg.attributes["dsn"] == dsn

    script = ScriptDirectory.from_config(cfg)
    heads = script.get_heads()
    assert len(heads) == 1
    assert heads == [HEAD_REV]
    assert len(HEAD_REV) <= 32

    head_script = script.get_revision(HEAD_REV)
    assert head_script is not None
    assert head_script.down_revision == BASELINE_REV

    baseline_script = script.get_revision(BASELINE_REV)
    assert baseline_script is not None
    assert baseline_script.down_revision is None

    # Re-export parity: models live canonically in db/postgres_models and are re-exported by storage/postgres_models.
    assert SignalItemModel.__module__.endswith(".db.postgres_models")
    assert SignalScanModel.__module__.endswith(".db.postgres_models")
    assert storage_postgres_models.SignalItemModel is SignalItemModel
    assert storage_postgres_models.SignalScanModel is SignalScanModel
    assert "SignalItemModel" in storage_postgres_models.__all__
    assert "SignalScanModel" in storage_postgres_models.__all__

    tables = set(Base.metadata.tables.keys())
    assert {"companies", "runs", "fields", "desk_chats", "desk_scope", "desk_turns"} <= tables
    assert tables >= M2_TABLES

    # Offline SQL generation must succeed without connecting to Postgres and emit both revisions' DDL.
    buf = StringIO()
    offline_cfg = alembic_config(dsn)
    offline_cfg.output_buffer = buf
    command.upgrade(offline_cfg, "head", sql=True)
    sql = buf.getvalue()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "CREATE TABLE" in sql and BASELINE_REV in sql
    assert HEAD_REV in sql
    for marker in (
        "signal_items",
        "signal_scans",
        "desk_uploads",
        "ix_signal_items_item_at",
        "ix_signal_scans_finished_at",
        "ix_desk_uploads_chat_id",
        "ix_desk_uploads_created_at",
        "ADD COLUMN IF NOT EXISTS fetch_failures",
    ):
        assert marker in sql


def test_alembic_upgrade_from_unversioned_and_fresh_database(pg):
    # 1. Start from unversioned state by dropping alembic_version if present.
    admin_eng = create_engine(pg, poolclass=pool.NullPool, isolation_level="AUTOCOMMIT")
    fresh_db = "arp_alembic_fresh_test"
    fresh_dsn = make_url(pg).set(database=fresh_db).render_as_string(hide_password=False)
    try:
        with admin_eng.connect() as conn:
            conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
        assert current_revision(pg) is None

        runner = CliRunner()
        res_unver = runner.invoke(db_app, ["current"])
        assert res_unver.exit_code == 0, res_unver.output
        assert "unversioned" in res_unver.output

        # 2. Run full migration chain against a brand-new isolated Postgres database on a caller-supplied connection.
        with admin_eng.connect() as conn:
            conn.execute(text(f"DROP DATABASE IF EXISTS {fresh_db} WITH (FORCE)"))
            conn.execute(text(f"CREATE DATABASE {fresh_db}"))
        try:
            fresh_eng = create_engine(fresh_dsn, poolclass=pool.NullPool)
            try:
                with fresh_eng.connect() as conn:
                    cfg = alembic_config(fresh_dsn)
                    cfg.attributes["connection"] = conn
                    command.upgrade(cfg, "head")
                    insp = inspect(conn)
                    created = set(insp.get_table_names())
                    assert {
                        "companies",
                        "runs",
                        "fields",
                        "desk_chats",
                        "desk_scope",
                        "desk_turns",
                        "alembic_version",
                    } <= created
                    assert created >= M2_TABLES
                    assert {ix["name"] for ix in insp.get_indexes("signal_items")} >= {"ix_signal_items_item_at"}
                    assert {ix["name"] for ix in insp.get_indexes("signal_scans")} >= {"ix_signal_scans_finished_at"}
                    assert {ix["name"] for ix in insp.get_indexes("desk_uploads")} >= {
                        "ix_desk_uploads_chat_id",
                        "ix_desk_uploads_created_at",
                    }
            finally:
                fresh_eng.dispose()
            assert current_revision(fresh_dsn) == HEAD_REV
            report = schema_report(fresh_dsn)
            assert report["current"] is True
            assert report["drift"] == []
        finally:
            with admin_eng.connect() as conn:
                conn.execute(text(f"DROP DATABASE IF EXISTS {fresh_db} WITH (FORCE)"))
    finally:
        admin_eng.dispose()

    # 3. Full CLI & programmatic upgrade/idempotency/stamp round-trip on the main test DB.
    upgrade_head(pg)
    assert current_revision(pg) == HEAD_REV

    upgrade_head(pg)
    assert current_revision(pg) == HEAD_REV

    stamp_head(pg)
    assert current_revision(pg) == HEAD_REV

    runner = CliRunner()
    for args in (["current"], ["upgrade"], ["stamp-head"]):
        res = runner.invoke(db_app, args)
        assert res.exit_code == 0, res.output
        assert HEAD_REV in res.output


def test_alembic_upgrade_from_0001_baseline_and_downgrade_roundtrip(pg):
    # Simulate an existing 0001_baseline database that does not yet have any of the 0002 tables.
    command.stamp(alembic_config(pg), BASELINE_REV)
    engine = create_engine(pg, poolclass=pool.NullPool)
    try:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS desk_uploads"))
            conn.execute(text("DROP TABLE IF EXISTS signal_scans"))
            conn.execute(text("DROP TABLE IF EXISTS signal_items"))
        assert current_revision(pg) == BASELINE_REV

        with engine.connect() as conn:
            existing = set(inspect(conn).get_table_names())
            assert not (M2_TABLES & existing)

        # Upgrade 0001_baseline -> 0002_signal_store_desk_uploads.
        upgrade_head(pg)
        assert current_revision(pg) == HEAD_REV

        with engine.connect() as conn:
            insp = inspect(conn)
            assert set(insp.get_table_names()) >= M2_TABLES

            item_cols = {c["name"]: c for c in insp.get_columns("signal_items")}
            assert set(item_cols) == {
                "content_hash",
                "source",
                "source_type",
                "title",
                "text",
                "url",
                "raw_entity_names",
                "published_at",
                "published_at_is_estimated",
                "item_at",
                "first_seen_at",
                "last_seen_at",
            }
            assert item_cols["published_at"]["nullable"] is True
            assert item_cols["item_at"]["nullable"] is False
            assert insp.get_pk_constraint("signal_items")["constrained_columns"] == ["content_hash"]
            assert {ix["name"] for ix in insp.get_indexes("signal_items")} >= {"ix_signal_items_item_at"}

            scan_cols = {c["name"]: c for c in insp.get_columns("signal_scans")}
            assert set(scan_cols) == {
                "scan_id",
                "kind",
                "run_id",
                "started_at",
                "finished_at",
                "items_fetched",
                "items_new",
                "fetch_failures",
                "lag_hours",
                "unclustered_share",
            }
            assert scan_cols["run_id"]["nullable"] is True
            assert scan_cols["fetch_failures"]["nullable"] is True
            assert scan_cols["lag_hours"]["nullable"] is True
            assert scan_cols["unclustered_share"]["nullable"] is True
            assert insp.get_pk_constraint("signal_scans")["constrained_columns"] == ["scan_id"]
            assert {ix["name"] for ix in insp.get_indexes("signal_scans")} >= {"ix_signal_scans_finished_at"}

            upload_cols = {c["name"]: c for c in insp.get_columns("desk_uploads")}
            assert set(upload_cols) == {
                "id",
                "chat_id",
                "owner_id",
                "filename",
                "stored_path",
                "size_bytes",
                "sha256",
                "status",
                "error",
                "full_text",
                "page_breaks",
                "detected_company_id",
                "detection",
                "saved_company_id",
                "saved_doc_type",
                "saved_at",
                "created_at",
            }
            assert upload_cols["id"].get("identity") is not None
            assert insp.get_pk_constraint("desk_uploads")["constrained_columns"] == ["id"]
            fks = insp.get_foreign_keys("desk_uploads")
            assert any(
                fk["referred_table"] == "desk_chats"
                and fk["constrained_columns"] == ["chat_id"]
                and fk["referred_columns"] == ["id"]
                for fk in fks
            )
            assert {ix["name"] for ix in insp.get_indexes("desk_uploads")} >= {
                "ix_desk_uploads_chat_id",
                "ix_desk_uploads_created_at",
            }

        report = schema_report(pg)
        assert report["current"] is True
        assert report["drift"] == []

        # Re-running upgrade_head is a no-op.
        upgrade_head(pg)
        assert current_revision(pg) == HEAD_REV

        # Downgrade to 0001_baseline drops all 3 tables cleanly.
        command.downgrade(alembic_config(pg), BASELINE_REV)
        assert current_revision(pg) == BASELINE_REV
        with engine.connect() as conn:
            assert not (M2_TABLES & set(inspect(conn).get_table_names()))

        # Re-upgrade back to head recreates all 3 tables cleanly with zero drift.
        upgrade_head(pg)
        assert current_revision(pg) == HEAD_REV
        report_after = schema_report(pg)
        assert report_after["current"] is True
        assert report_after["drift"] == []
    finally:
        engine.dispose()
        ensure_schema(pg)


def test_signal_scans_legacy_column_addition_ac41(pg):
    """AC-41: a pre-slice-d `signal_scans` table without `fetch_failures`, `lag_hours`, or `unclustered_share`
    upgrades cleanly via both `ensure_schema_on_connection` and Alembic `0002`, preserving existing rows with zero drift."""
    legacy_ddl = """
        CREATE TABLE signal_scans (
            scan_id VARCHAR PRIMARY KEY,
            kind VARCHAR NOT NULL,
            run_id VARCHAR NULL,
            started_at TIMESTAMPTZ NOT NULL,
            finished_at TIMESTAMPTZ NOT NULL,
            items_fetched JSONB NOT NULL,
            items_new JSONB NOT NULL
        )
    """
    insert_legacy = """
        INSERT INTO signal_scans (scan_id, kind, run_id, started_at, finished_at, items_fetched, items_new)
        VALUES ('scan_legacy_1', 'light', NULL, '2026-11-25T05:00:00+00:00', '2026-11-25T06:00:00+00:00',
                '{"gdelt": 4}'::jsonb, '{"gdelt": 2}'::jsonb)
    """
    engine = create_engine(pg, poolclass=pool.NullPool)
    try:
        # Path A: additive reconciliation via ensure_schema_on_connection (`arp db init-postgres`).
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS signal_scans"))
            conn.execute(text(legacy_ddl))
            conn.execute(text(insert_legacy))
            result = ensure_schema_on_connection(conn)
            assert set(result["columns_added"]) >= {
                "signal_scans.fetch_failures",
                "signal_scans.lag_hours",
                "signal_scans.unclustered_share",
            }
            row = conn.execute(
                text(
                    "SELECT scan_id, fetch_failures, lag_hours, unclustered_share "
                    "FROM signal_scans WHERE scan_id = 'scan_legacy_1'"
                )
            ).one()
            assert row.scan_id == "scan_legacy_1"
            assert row.fetch_failures is None
            assert row.lag_hours is None
            assert row.unclustered_share is None

        report_a = schema_report(pg)
        assert report_a["current"] is True
        assert report_a["drift"] == []

        # Path B: Alembic 0002 upgrade over the same pre-slice-d table.
        command.stamp(alembic_config(pg), BASELINE_REV)
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS signal_scans"))
            conn.execute(text(legacy_ddl))
            conn.execute(text(insert_legacy))

        upgrade_head(pg)
        assert current_revision(pg) == HEAD_REV

        with engine.connect() as conn:
            row_b = conn.execute(
                text(
                    "SELECT scan_id, items_fetched, fetch_failures, lag_hours, unclustered_share "
                    "FROM signal_scans WHERE scan_id = 'scan_legacy_1'"
                )
            ).one()
            assert row_b.scan_id == "scan_legacy_1"
            assert row_b.items_fetched == {"gdelt": 4}
            assert row_b.fetch_failures == {}
            assert row_b.lag_hours == {}
            assert row_b.unclustered_share is None

        report_b = schema_report(pg)
        assert report_b["current"] is True
        assert report_b["drift"] == []
    finally:
        engine.dispose()
        ensure_schema(pg)


def test_orm_roundtrip_signal_store_and_desk_uploads(pg):
    upgrade_head(pg)
    now = datetime(2026, 11, 28, 12, 0, tzinfo=UTC)
    engine = create_engine(pg, poolclass=pool.NullPool)
    try:
        with Session(engine) as session:
            item = SignalItemModel(
                content_hash="abc123",
                source="gdelt",
                source_type="gdelt",
                title="Grid storage surge",
                text="Battery deployments doubled.",
                url="https://example.com/grid",
                published_at=None,
                published_at_is_estimated=True,
                item_at=now,
                first_seen_at=now,
                last_seen_at=now,
            )
            scan_default = SignalScanModel(
                scan_id="scan_1",
                kind="light",
                run_id=None,
                started_at=now,
                finished_at=now,
            )
            scan_full = SignalScanModel(
                scan_id="scan_2",
                kind="full",
                run_id="run_42",
                started_at=now,
                finished_at=now,
                items_fetched={"gdelt": 10, "edgar_fts": 5},
                items_new={"gdelt": 3, "edgar_fts": 1},
                fetch_failures={"gdelt": 0, "edgar_fts": 1},
                lag_hours={"gdelt": 0.5, "edgar_fts": None},
                unclustered_share=0.25,
            )
            chat = db_models.DeskChat(owner_id="u_analyst", title="Upload test chat")
            session.add_all([item, scan_default, scan_full, chat])
            session.flush()

            upload = db_models.DeskUpload(
                chat_id=chat.id,
                owner_id="u_analyst",
                filename="annual_report.pdf",
                stored_path=f"{chat.id}/1/annual_report.pdf",
                size_bytes=4096,
                sha256="deadbeef",
            )
            session.add(upload)
            session.commit()
            upload_id = upload.id
            chat_id = chat.id

        with Session(engine) as session:
            loaded_item = session.get(SignalItemModel, "abc123")
            assert loaded_item is not None
            assert loaded_item.raw_entity_names == []
            assert loaded_item.published_at is None
            assert loaded_item.published_at_is_estimated is True
            assert loaded_item.item_at == now

            loaded_default_scan = session.get(SignalScanModel, "scan_1")
            assert loaded_default_scan is not None
            assert loaded_default_scan.items_fetched == {}
            assert loaded_default_scan.items_new == {}
            assert loaded_default_scan.fetch_failures == {}
            assert loaded_default_scan.lag_hours == {}
            assert loaded_default_scan.unclustered_share is None

            loaded_full_scan = session.get(SignalScanModel, "scan_2")
            assert loaded_full_scan is not None
            assert loaded_full_scan.run_id == "run_42"
            assert loaded_full_scan.fetch_failures == {"gdelt": 0, "edgar_fts": 1}
            assert loaded_full_scan.lag_hours == {"gdelt": 0.5, "edgar_fts": None}
            assert loaded_full_scan.unclustered_share == 0.25

            loaded_upload = session.get(db_models.DeskUpload, upload_id)
            assert loaded_upload is not None
            assert isinstance(loaded_upload.id, int)
            assert loaded_upload.chat_id == chat_id
            assert loaded_upload.status == "reading"
            assert loaded_upload.page_breaks == []
            assert loaded_upload.detection == "none"
            assert loaded_upload.error is None
            assert loaded_upload.full_text is None
            assert loaded_upload.detected_company_id is None
            assert loaded_upload.saved_company_id is None
            assert loaded_upload.saved_doc_type is None
            assert loaded_upload.saved_at is None
            assert loaded_upload.created_at is not None

        # FK constraint on desk_uploads.chat_id -> desk_chats.id must reject dangling chat_id.
        with Session(engine) as session:
            bad_upload = db_models.DeskUpload(
                chat_id=999_999_999,
                owner_id="u_analyst",
                filename="orphan.pdf",
                stored_path="999999999/1/orphan.pdf",
                size_bytes=128,
                sha256="cafebabe",
            )
            session.add(bad_upload)
            with pytest.raises(IntegrityError):
                session.commit()
    finally:
        engine.dispose()
