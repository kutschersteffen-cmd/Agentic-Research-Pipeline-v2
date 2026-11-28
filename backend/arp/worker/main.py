"""Dedicated background worker process (`arp worker run`).

Runs all scheduled background jobs and the autonomous plan worker outside the
FastAPI HTTP process so the API can scale across multiple stateless workers.
A Postgres session-level advisory lock (`pg_try_advisory_lock`) guarantees that
at most one worker instance runs schedulers at a time; standby instances wait
until the lock is released and exit cleanly on SIGTERM/SIGINT.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from arp.api.deps import (
    get_calibration_scheduler,
    get_emerging_themes_scheduler,
    get_portfolio_monitoring_scheduler,
    get_publishing_scheduler,
    get_review_analytics_scheduler,
    get_scheduler,
    get_taxonomy_researcher_scheduler,
)
from arp.api.routers import plans
from arp.config import Settings, get_settings
from arp.db.session import require_cutover, require_postgres
from arp.refine.turns import reap_stale_turns
from arp.research_desk.turn import reap_stale_desk_turns
from arp.runtime.container import wire as wire_runtime
from arp.storage.postgres import _CONNECT_TIMEOUT_SECONDS

wire_runtime()

logger = logging.getLogger(__name__)

# Stable 64-bit Postgres advisory lock key ("ARPW" = 0x41525057).
ADVISORY_LOCK_KEY = 0x41525057


@lru_cache
def _leader_engine(dsn: str) -> Engine:
    """Unpooled engine dedicated to the worker leader lock so closing the connection ends the session."""
    connect_args = {} if "connect_timeout" in dsn else {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}
    return create_engine(dsn, poolclass=NullPool, connect_args=connect_args)


def acquire_leader_lock(conn) -> bool:
    """Attempt a non-blocking session-level Postgres advisory lock."""
    return bool(conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": ADVISORY_LOCK_KEY}).scalar())


def release_leader_lock(conn) -> bool:
    """Release the session-level Postgres advisory lock."""
    return bool(conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": ADVISORY_LOCK_KEY}).scalar())


def _build_schedulers() -> list:
    return [
        get_scheduler(),
        get_taxonomy_researcher_scheduler(),
        get_calibration_scheduler(),
        get_emerging_themes_scheduler(),
        get_portfolio_monitoring_scheduler(),
        get_publishing_scheduler(),
        get_review_analytics_scheduler(),
    ]


def _install_signal_handlers(loop: asyncio.AbstractEventLoop, stop: asyncio.Event) -> None:
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError, RuntimeError):
            loop.add_signal_handler(sig, stop.set)


async def run_worker(
    settings: Settings | None = None,
    *,
    stop_event: asyncio.Event | None = None,
    retry_seconds: float = 5.0,
) -> None:
    """Run the leader-elected background worker until `stop_event` or SIGTERM/SIGINT."""
    cfg = settings or get_settings()
    dsn = require_postgres(cfg)
    require_cutover(cfg)
    cfg.ensure_dirs()

    stop = stop_event or asyncio.Event()
    if stop_event is None:
        _install_signal_handlers(asyncio.get_running_loop(), stop)

    # AUTOCOMMIT + NullPool avoids idle-in-transaction sessions and ensures connection close frees the lock.
    with _leader_engine(dsn).connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        acquired = False
        while not stop.is_set():
            if acquire_leader_lock(conn):
                acquired = True
                break
            logger.info("Another arp worker holds leader lock %s; waiting %.1fs", ADVISORY_LOCK_KEY, retry_seconds)
            with suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=retry_seconds)

        if not acquired:
            return

        logger.info("Acquired arp worker leader lock %s; starting schedulers", ADVISORY_LOCK_KEY)
        started: list = []
        plan_worker: asyncio.Task | None = None
        try:
            now = datetime.now(UTC)
            reap_stale_turns(now=now)
            reap_stale_desk_turns(now=now)

            for sched in _build_schedulers():
                sched.start()
                started.append(sched)
            if cfg.plan_worker_seconds > 0:
                plan_worker = plans.start_plan_worker(cfg)
            await stop.wait()
        finally:
            if plan_worker is not None:
                plan_worker.cancel()
                with suppress(asyncio.CancelledError):
                    await plan_worker
            for sched in reversed(started):
                try:
                    sched.shutdown()
                except Exception:  # noqa: BLE001 - continue shutting down remaining schedulers
                    logger.warning("Scheduler %s failed during shutdown", type(sched).__name__, exc_info=True)
            with suppress(Exception):
                release_leader_lock(conn)
            logger.info("arp worker stopped cleanly")
