from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TYPE_CHECKING

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.pool import NullPool

from arp.errors import NotConfigured
from arp.job_runtime.job_manager import JobManager
from arp.storage.postgres import _CONNECT_TIMEOUT_SECONDS
from arp.storage.run_store import RunStore

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class RunBusy(NotConfigured):
    """Another worker already holds this run's lease."""


_LEASE_NS = 0x41525054  # "ARPT": keeps run leases apart from any other advisory lock user
_LEASE = text("SELECT pg_try_advisory_lock(:ns, hashtext(:id))")


@lru_cache
def _lease_engine(dsn: str) -> Engine:
    """No pool: a lease holds its connection for the whole run, which must not use up the app's pool."""
    connect_args = {} if "connect_timeout" in dsn else {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}
    return create_engine(dsn, poolclass=NullPool, connect_args=connect_args)


@contextmanager
def run_lease(run_store: RunStore, run_id: str) -> Iterator[None]:
    """One worker per run, across processes and machines: a Postgres advisory lock on the run id,
    held on its own connection. Raises RunBusy if another session holds it. Freed when the holder
    exits, or when its connection dies, so a crashed worker never leaves a run stuck."""
    # ponytail: a dropped lease connection frees the lease while the worker runs on; a heartbeat that
    # stops the worker is the upgrade path.
    key = {"ns": _LEASE_NS, "id": run_id}
    with _lease_engine(run_store.dsn).connect() as conn:
        got = conn.scalar(_LEASE, key)
        conn.commit()  # the session-level lock outlives the transaction; no transaction stays open
        if not got:
            raise RunBusy(f"Run {run_id} already has a worker")
        # No unlock: closing the unpooled connection ends the session, which frees the lock, and an
        # unlock on a connection that already died would replace the run's own outcome.
        yield


_held: ContextVar[frozenset[str]] = ContextVar("held_runs", default=frozenset())


@contextmanager
def hold_run(run_store: RunStore, run_id: str) -> Iterator[None]:
    """`run_lease`, re-entrant within one task context: a no-op if this
    context already holds the run (a launcher or resume_run that then calls
    the pipeline), else takes the lease and marks it held. Every batch run
    goes through it (run_company_batch, execute_discovery_run), so a second
    worker on the same run raises RunBusy however it was started. The
    outermost holder marks the run failed when its body raises."""
    if run_id in _held.get():
        yield
        return
    with run_lease(run_store, run_id):
        token = _held.set(_held.get() | {run_id})
        try:
            yield
        except Exception as exc:
            _mark_failed(run_store, run_id, exc)
            raise
        finally:
            _held.reset(token)


def traceback_tail(exc: BaseException, limit: int = 8000) -> str:
    """The end of the formatted traceback, where the failing frame and message are."""
    return "".join(traceback.format_exception(exc))[-limit:]


def _mark_failed(run_store: RunStore, run_id: str, exc: Exception) -> None:
    """A crash before the run finished would leave it "running" forever."""
    try:
        JobManager(run_store).finish_run(run_id, error=f"{type(exc).__name__}: {exc}")
    except Exception:  # noqa: BLE001 - the run's own error is the one to raise
        logger.exception("could not mark run %s failed", run_id)
    try:
        run_store.append_event(
            run_id, {"type": "run_failed", "at": datetime.now(UTC).isoformat(), "traceback": traceback_tail(exc)}
        )
    except Exception:  # noqa: BLE001 - the run's own error is the one to raise
        logger.exception("could not record run_failed event for run %s", run_id)


class LocalJobLauncher:
    """Runs a run's job as a background task in this process, under the
    run's lease. `run_store` is a factory so the app's current settings
    decide where `runs/` is at launch time."""

    def __init__(self, run_store: Callable[[], RunStore]) -> None:
        self._run_store = run_store
        self._tasks: set[asyncio.Task] = set()  # strong refs: a running task is never garbage-collected

    def launch(self, run_id: str, job: Callable[[], Awaitable[None]], *, run_store: RunStore | None = None) -> None:
        """`run_store`, when given, is where the lease is taken (the caller's
        own store); otherwise the factory's."""

        async def _leased() -> None:
            try:
                with hold_run(run_store or self._run_store(), run_id):
                    await job()
            except Exception:  # noqa: BLE001 - nobody awaits the task
                logger.exception("Job for run %s failed", run_id)

        task = asyncio.create_task(_leased(), name=run_id)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def drain(self) -> list[str]:
        """Waits for every launched job, including any launched meanwhile, so a
        short-lived caller (a CLI `asyncio.run`) does not cancel them on exit.
        Returns the run ids it waited for."""
        drained: list[str] = []
        while self._tasks:
            tasks = list(self._tasks)
            drained += [t.get_name() for t in tasks]
            await asyncio.gather(*tasks, return_exceptions=True)
            self._tasks.difference_update(tasks)
        return drained


_launcher: LocalJobLauncher | None = None


def get_job_launcher() -> LocalJobLauncher:
    global _launcher
    if _launcher is None:
        from arp.storage.factories import get_run_store

        # ponytail: a cloud_run launcher plugs in here at Cloud switch-on.
        _launcher = LocalJobLauncher(get_run_store)
    return _launcher


_LEASE_GRACE = timedelta(seconds=60)  # a run is launched just after its request returns; its lease comes a moment later


def run_alive(run_store, run_id: str | None) -> bool:
    """A worker holds the run's lease, or the run is too new to have taken it yet. A process restart frees the lease,
    so a run left `detecting` or `drafting` by a restart can be started again (RFP) or reads as failed (theme research)."""
    if not run_id:
        return False
    manifest = run_store.load_manifest(run_id)
    if manifest and datetime.now(UTC) - datetime.fromisoformat(manifest.created_at) < _LEASE_GRACE:
        return True
    try:
        with run_lease(run_store, run_id):
            return False
    except RunBusy:
        return True
