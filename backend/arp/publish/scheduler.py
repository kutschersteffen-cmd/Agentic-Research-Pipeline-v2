"""Daily in-process job: re-ground sample and parser-change reground (E74)."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from arp.config import Settings
from arp.db.session import require_dsn
from arp.orchestration.interval_scheduler import IntervalScheduler
from arp.orchestration.reground import reground_if_parser_changed
from arp.publish.facts import Fact, PublishStore, ts_now
from arp.publish.gate import reground, sample
from arp.publish.reader import facts_as_of
from arp.storage.jsonl_io import append_jsonl

logger = logging.getLogger(__name__)


class PublishingScheduleConfig(BaseModel):
    enabled: bool = False
    interval_hours: int = 24
    last_run_at: str | None = None
    last_reground_day: str | None = None
    last_results: dict = Field(default_factory=dict)


def _today() -> date:
    return datetime.now(UTC).date()


def due_jobs(today: date, config: PublishingScheduleConfig) -> list[str]:
    return ["reground"] if config.last_reground_day != today.isoformat() else []


def reground_sample(
    facts: list[Fact], *, n: int, day: str, blob_store, content_store, fuzzy_threshold: float, log_path: Path
) -> list[dict]:
    rows = []
    for f in sample(facts, n, seed=day):
        result = reground(f, blob_store=blob_store, content_store=content_store, fuzzy_threshold=fuzzy_threshold)
        if result != "ok":
            logger.warning("Re-ground of fact %s: %s", f.fact_id, result)
        rows.append({"day": day, "fact_id": f.fact_id, "result": result})
    for r in rows:
        append_jsonl(log_path, r)
    return rows


class PublishingScheduler(IntervalScheduler):
    config_cls = PublishingScheduleConfig
    job_id = "publishing-schedule"

    def __init__(self, settings: Settings, portfolio_store, run_store) -> None:
        super().__init__(settings.publish_state_dir)
        self.settings = settings
        self.portfolio_store = portfolio_store
        self.run_store = run_store

    def _default_config(self) -> PublishingScheduleConfig:
        return PublishingScheduleConfig(enabled=self.settings.publishing_schedule_enabled)

    def _facts(self):
        store = PublishStore(require_dsn(self.settings))
        return lambda a: facts_as_of(store, a)

    def _reground(self, today: date) -> tuple[str, str]:
        from arp.ingestion.indexing_config import IndexingConfig
        from arp.retrieval.content_store_factory import content_store_for
        from arp.storage.document_blob_store import blob_store_for

        s = self.settings
        facts = self._facts()(ts_now())
        rows = reground_sample(
            facts, n=s.reground_sample_size, day=today.isoformat(),
            blob_store=blob_store_for(IndexingConfig.from_settings(s)), content_store=content_store_for(s),
            fuzzy_threshold=s.grounding_fuzzy_threshold, log_path=s.publish_state_dir / "reground.jsonl",
        )
        bad = [r["fact_id"] for r in rows if r["result"] != "ok"]
        if bad:
            return "drift", f"{len(bad)} of {len(rows)} not ok: {', '.join(bad[:5])}"
        return "ok", f"{len(rows)} sampled, 0 not ok"

    async def _run(self, config: PublishingScheduleConfig) -> None:
        today = _today()
        try:  # every tick; a no-op unless the parser version changed (E51)
            report = await asyncio.to_thread(
                reground_if_parser_changed, self.run_store, settings=self.settings
            )
            if report is not None:
                config.last_results["parser_reground"] = {"status": "ok", "detail": str(report)}
        except Exception as exc:  # noqa: BLE001 - never stops the other jobs
            logger.exception("Parser re-ground failed")
            config.last_results["parser_reground"] = {"status": "failed", "detail": str(exc)[:500]}
        for job in due_jobs(today, config):
            try:
                status, detail = await asyncio.to_thread(self._reground, today)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Publishing job %s failed", job)
                status, detail = "failed", str(exc)[:500]
            config.last_results[job] = {"status": status, "detail": detail}
            if status in ("ok", "drift"):
                config.last_reground_day = today.isoformat()
        config.last_run_at = ts_now()
