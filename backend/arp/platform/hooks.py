"""Decoupled runtime hooks between discovery event refresh and the extraction pipeline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

CreateExtractionFn = Callable[..., str]
ExecuteExtractionFn = Callable[..., Awaitable[str]]

_extraction_runner: tuple[CreateExtractionFn, ExecuteExtractionFn] | None = None


def register_extraction_runner(create_fn: CreateExtractionFn, execute_fn: ExecuteExtractionFn) -> None:
    """Register the extraction run creator and executor for event-driven refresh."""
    global _extraction_runner
    _extraction_runner = (create_fn, execute_fn)


def get_extraction_runner() -> tuple[CreateExtractionFn, ExecuteExtractionFn]:
    """Return the registered `(create_extraction_run, execute_extraction_run)` pair."""
    if _extraction_runner is None:
        raise RuntimeError("Extraction runner not registered; call arp.runtime.container.wire() at startup.")
    return _extraction_runner
