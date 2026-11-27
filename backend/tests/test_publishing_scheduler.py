from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import date

import pytest

from arp.config import Settings
from arp.publish import scheduler as S
from arp.publish.facts import Fact
from arp.publish.scheduler import PublishingScheduleConfig, PublishingScheduler, due_jobs
from arp.schemas.common import Citation
from arp.storage.document_blob_store import LocalBlobStore
from arp.storage.document_store import DocumentContentStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore
from tests.postgres_helpers import pg_dsn

pytestmark = pytest.mark.usefixtures("pg")


def test_reground_once_per_day():
    day = date(2026, 11, 3)
    assert due_jobs(day, PublishingScheduleConfig()) == ["reground"]
    assert due_jobs(day, PublishingScheduleConfig(last_reground_day="2026-11-03")) == []


def _fact(fid, key):
    cit = Citation(doc_id="d", doc_type="sustainability_report", quote="q", grounded=True, content_key=key,
                   parser_version="p1", span_text="q", char_start=0, char_end=1, match_method="exact")
    return Fact(fact_id=fid, issuer_key="I", issuer_scheme="LEI", field_id="f", period_end="2024-12-31", value=1.0,
                state="approved", citation=cit, source_run_id="r", observed_at="2026-01-01T00:00:00.000000+00:00",
                item_key=fid, version=1, valid_from="2026-01-01T00:00:00.000000+00:00", release_id="rel")


def test_reground_sample_records_results(tmp_path):
    orig = b"original"
    key = hashlib.sha256(orig).hexdigest()
    blobs = LocalBlobStore(tmp_path / "blobs")
    blobs.put(key, orig)
    log = tmp_path / "reground.jsonl"
    rows = S.reground_sample(
        [_fact("a", key), _fact("b", "0" * 64)], n=5, day="2026-11-03", blob_store=blobs,
        content_store=DocumentContentStore(tmp_path / "docs", dsn=pg_dsn()), fuzzy_threshold=0.9, log_path=log,
    )
    assert len(rows) == 2 and len(log.read_text().splitlines()) == 2
    assert [r["result"] for r in rows if r["fact_id"] == "b"] == ["original_missing"]
    assert json.loads(log.read_text().splitlines()[0])["day"] == "2026-11-03"


def test_scheduler_run_records_reground(tmp_path, monkeypatch, pg):
    store, rs = PortfolioStore(tmp_path / "pf"), RunStore(pg, tmp_path / "runs")
    settings = Settings(postgres_dsn=pg, publish_state_dir=tmp_path / "state")
    monkeypatch.setattr(S, "_today", lambda: date(2026, 11, 2))
    sched, config = PublishingScheduler(settings, store, rs), PublishingScheduleConfig(enabled=True)
    monkeypatch.setattr(sched, "_reground", lambda t: ("ok", "0 sampled, 0 not ok"))
    asyncio.run(sched._run(config))
    assert config.last_results["reground"]["status"] == "ok"
    assert config.last_reground_day == "2026-11-02"
    assert config.last_run_at


def test_scheduler_reground_reads_published_facts(tmp_path, pg):
    store, rs = PortfolioStore(tmp_path / "pf"), RunStore(pg, tmp_path / "runs")
    settings = Settings(postgres_dsn=pg, publish_state_dir=tmp_path / "state", document_store_dir=tmp_path / "docs")
    sched = PublishingScheduler(settings, store, rs)
    status, detail = sched._reground(date(2026, 11, 2))
    assert status == "ok" and "0 sampled" in detail


def test_scheduler_run_records_reground_failure(tmp_path, monkeypatch, pg):
    store, rs = PortfolioStore(tmp_path / "pf"), RunStore(pg, tmp_path / "runs")
    settings = Settings(postgres_dsn=pg, publish_state_dir=tmp_path / "state")
    monkeypatch.setattr(S, "_today", lambda: date(2026, 11, 2))
    sched, config = PublishingScheduler(settings, store, rs), PublishingScheduleConfig(enabled=True)
    monkeypatch.setattr(sched, "_reground", lambda _t: (_ for _ in ()).throw(RuntimeError("boom")))
    asyncio.run(sched._run(config))
    assert config.last_results["reground"] == {"status": "failed", "detail": "boom"}
    assert config.last_reground_day is None
