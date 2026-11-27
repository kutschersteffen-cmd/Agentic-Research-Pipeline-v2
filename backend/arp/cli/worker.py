"""CLI entrypoint for the dedicated background worker process."""

from __future__ import annotations

import asyncio

import typer

from arp.worker.main import run_worker

worker_app = typer.Typer(help="Dedicated background worker for schedulers and the plan worker.")


@worker_app.command("run")
def worker_run(
    retry_seconds: float = typer.Option(5.0, min=0.1, help="Seconds between leader-lock retries while in standby."),
) -> None:
    """Run all scheduled background jobs and the plan worker under a Postgres advisory lock."""
    asyncio.run(run_worker(retry_seconds=retry_seconds))
