"""Tests for the dedicated Postgres advisory-locked background worker (`arp worker run`)
and stateless FastAPI lifespan."""

from __future__ import annotations

import asyncio

import pytest
from typer.testing import CliRunner

from arp.cli.worker import worker_app
from arp.config import Settings
from arp.worker import main as worker_main


class _FakeResult:
    def __init__(self, value: bool) -> None:
        self._value = value

    def scalar(self) -> bool:
        return self._value


class _FakeConn:
    def __init__(self, lock_results: list[bool]) -> None:
        self._lock_results = list(lock_results)
        self.calls: list[tuple[str, dict]] = []
        self.isolation_level: str | None = None

    def execution_options(self, *, isolation_level: str):
        self.isolation_level = isolation_level
        return self

    def execute(self, stmt, params):
        sql = str(stmt)
        self.calls.append((sql, dict(params)))
        if "pg_try_advisory_lock" in sql:
            return _FakeResult(self._lock_results.pop(0) if self._lock_results else False)
        return _FakeResult(True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    def connect(self) -> _FakeConn:
        return self._conn


class _FakeScheduler:
    def __init__(
        self,
        name: str,
        log: list[str],
        *,
        fail_start: bool = False,
        fail_shutdown: bool = False,
    ) -> None:
        self.name = name
        self.log = log
        self._fail_start = fail_start
        self._fail_shutdown = fail_shutdown

    def start(self) -> None:
        if self._fail_start:
            raise RuntimeError(f"start boom: {self.name}")
        self.log.append(f"start:{self.name}")

    def shutdown(self) -> None:
        self.log.append(f"shutdown:{self.name}")
        if self._fail_shutdown:
            raise RuntimeError(f"shutdown boom: {self.name}")


def _settings(tmp_path, *, plan_worker_seconds: float = 0.5) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        postgres_dsn="postgresql+psycopg://arp:arp@localhost/arp",
        runs_dir=tmp_path / "runs",
        cache_dir=tmp_path / "cache",
        plan_worker_seconds=plan_worker_seconds,
    )


def test_advisory_lock_sql_helpers():
    conn = _FakeConn([True])
    assert worker_main.acquire_leader_lock(conn) is True
    assert worker_main.release_leader_lock(conn) is True
    assert "pg_try_advisory_lock" in conn.calls[0][0]
    assert conn.calls[0][1] == {"key": worker_main.ADVISORY_LOCK_KEY}
    assert "pg_advisory_unlock" in conn.calls[1][0]
    assert conn.calls[1][1] == {"key": worker_main.ADVISORY_LOCK_KEY}


def test_build_schedulers_returns_all_seven(monkeypatch):
    names = [
        "get_scheduler",
        "get_taxonomy_researcher_scheduler",
        "get_calibration_scheduler",
        "get_emerging_themes_scheduler",
        "get_portfolio_monitoring_scheduler",
        "get_publishing_scheduler",
        "get_review_analytics_scheduler",
    ]
    for name in names:
        monkeypatch.setattr(worker_main, name, lambda n=name: n)
    assert worker_main._build_schedulers() == names


def test_install_signal_handlers_registers_sigterm_and_sigint():
    registered: list[int] = []

    class _FakeLoop:
        def add_signal_handler(self, sig, cb):
            registered.append(sig)
            cb()

    stop = asyncio.Event()
    worker_main._install_signal_handlers(_FakeLoop(), stop)
    assert len(registered) == 2
    assert stop.is_set()


@pytest.mark.asyncio
async def test_run_worker_leader_starts_and_shuts_down_cleanly(tmp_path, monkeypatch):
    conn = _FakeConn([True])
    log: list[str] = []
    reaped: list[tuple[str, object]] = []

    monkeypatch.setattr(worker_main, "require_postgres", lambda cfg: cfg.postgres_dsn)
    monkeypatch.setattr(worker_main, "require_cutover", lambda cfg: None)
    monkeypatch.setattr(worker_main, "_leader_engine", lambda dsn: _FakeEngine(conn))
    monkeypatch.setattr(worker_main, "reap_stale_turns", lambda *, now: reaped.append(("refine", now)) or 0)
    monkeypatch.setattr(worker_main, "reap_stale_desk_turns", lambda *, now: reaped.append(("desk", now)) or 0)
    monkeypatch.setattr(
        worker_main,
        "_build_schedulers",
        lambda: [_FakeScheduler("a", log), _FakeScheduler("b", log, fail_shutdown=True)],
    )

    plan_started = asyncio.Event()
    plan_cancelled = False

    async def _fake_plan_loop():
        nonlocal plan_cancelled
        plan_started.set()
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            plan_cancelled = True
            raise

    monkeypatch.setattr(worker_main.plans, "start_plan_worker", lambda cfg: asyncio.create_task(_fake_plan_loop()))

    stop = asyncio.Event()
    task = asyncio.create_task(worker_main.run_worker(_settings(tmp_path), stop_event=stop))
    await plan_started.wait()
    stop.set()
    await task

    assert conn.isolation_level == "AUTOCOMMIT"
    assert [name for name, _ in reaped] == ["refine", "desk"]
    assert all(now is not None for _, now in reaped)
    assert plan_cancelled is True
    assert log == ["start:a", "start:b", "shutdown:b", "shutdown:a"]
    assert any("pg_advisory_unlock" in sql for sql, _ in conn.calls)


@pytest.mark.asyncio
async def test_run_worker_standby_promotes_to_leader_and_skips_disabled_plan_worker(tmp_path, monkeypatch):
    conn = _FakeConn([False, True])
    log: list[str] = []

    monkeypatch.setattr(worker_main, "require_postgres", lambda cfg: cfg.postgres_dsn)
    monkeypatch.setattr(worker_main, "require_cutover", lambda cfg: None)
    monkeypatch.setattr(worker_main, "_leader_engine", lambda dsn: _FakeEngine(conn))
    monkeypatch.setattr(worker_main, "reap_stale_turns", lambda *, now: 0)
    monkeypatch.setattr(worker_main, "reap_stale_desk_turns", lambda *, now: 0)
    monkeypatch.setattr(worker_main, "_build_schedulers", lambda: [_FakeScheduler("a", log)])
    monkeypatch.setattr(
        worker_main.plans,
        "start_plan_worker",
        lambda cfg: (_ for _ in ()).throw(AssertionError("plan_worker should not start when disabled")),
    )

    stop = asyncio.Event()

    async def _stop_after_start():
        while "start:a" not in log:
            await asyncio.sleep(0.01)
        stop.set()

    await asyncio.gather(
        worker_main.run_worker(_settings(tmp_path, plan_worker_seconds=0), stop_event=stop, retry_seconds=0.01),
        _stop_after_start(),
    )

    assert log == ["start:a", "shutdown:a"]
    assert any("pg_advisory_unlock" in sql for sql, _ in conn.calls)


@pytest.mark.asyncio
async def test_run_worker_releases_lock_on_startup_failure(tmp_path, monkeypatch):
    conn = _FakeConn([True])
    log: list[str] = []

    monkeypatch.setattr(worker_main, "require_postgres", lambda cfg: cfg.postgres_dsn)
    monkeypatch.setattr(worker_main, "require_cutover", lambda cfg: None)
    monkeypatch.setattr(worker_main, "_leader_engine", lambda dsn: _FakeEngine(conn))
    monkeypatch.setattr(worker_main, "reap_stale_turns", lambda *, now: 0)
    monkeypatch.setattr(worker_main, "reap_stale_desk_turns", lambda *, now: 0)
    monkeypatch.setattr(
        worker_main,
        "_build_schedulers",
        lambda: [_FakeScheduler("a", log), _FakeScheduler("b", log, fail_start=True)],
    )

    with pytest.raises(RuntimeError, match="start boom: b"):
        await worker_main.run_worker(_settings(tmp_path), stop_event=asyncio.Event())

    assert log == ["start:a", "shutdown:a"]
    assert any("pg_advisory_unlock" in sql for sql, _ in conn.calls)


@pytest.mark.asyncio
async def test_run_worker_standby_skips_schedulers_when_lock_held(tmp_path, monkeypatch):
    conn = _FakeConn([False, False])
    log: list[str] = []

    monkeypatch.setattr(worker_main, "require_postgres", lambda cfg: cfg.postgres_dsn)
    monkeypatch.setattr(worker_main, "require_cutover", lambda cfg: None)
    monkeypatch.setattr(worker_main, "_leader_engine", lambda dsn: _FakeEngine(conn))
    monkeypatch.setattr(worker_main, "_build_schedulers", lambda: [_FakeScheduler("a", log)])

    stop = asyncio.Event()

    async def _stop_soon():
        await asyncio.sleep(0.05)
        stop.set()

    await asyncio.gather(worker_main.run_worker(_settings(tmp_path), stop_event=stop, retry_seconds=0.02), _stop_soon())

    assert log == []
    assert not any("pg_advisory_unlock" in sql for sql, _ in conn.calls)


def test_worker_cli_invokes_run_worker(monkeypatch):
    called: list[float] = []

    async def _fake_run(*, retry_seconds: float = 5.0):
        called.append(retry_seconds)

    monkeypatch.setattr("arp.cli.worker.run_worker", _fake_run)
    res = CliRunner().invoke(worker_app, ["--retry-seconds", "1.5"])
    assert res.exit_code == 0, res.output
    assert called == [1.5]


@pytest.mark.asyncio
async def test_api_lifespan_is_stateless_and_starts_no_schedulers(tmp_path, monkeypatch):
    from arp.api import main as api_main

    settings = Settings(
        anthropic_api_key="unused",
        postgres_dsn="postgresql+psycopg://arp:arp@localhost/arp",
        runs_dir=tmp_path / "runs",
        cache_dir=tmp_path / "cache",
        auth_mode="dev",
        allowed_origins=["http://localhost:5173"],
    )
    monkeypatch.setattr(api_main, "settings_dep", lambda: settings)
    monkeypatch.setattr(api_main, "check_rule_book", lambda: None)
    monkeypatch.setattr(api_main, "check_benchmarks", lambda: None)
    monkeypatch.setattr(api_main, "require_postgres", lambda cfg: cfg.postgres_dsn)
    monkeypatch.setattr(api_main, "require_cutover", lambda cfg: None)
    monkeypatch.setattr(api_main, "_fill_observations", lambda cfg: None)
    monkeypatch.setattr(api_main, "wait_for_fill", lambda: None)
    monkeypatch.setattr(
        api_main.plans,
        "start_plan_worker",
        lambda cfg: (_ for _ in ()).throw(AssertionError("API must not start plan_worker")),
    )

    async with api_main.lifespan(api_main.app):
        assert (tmp_path / "runs").is_dir()
