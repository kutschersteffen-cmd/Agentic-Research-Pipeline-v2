"""Explicit composition root wiring cross-domain runtime hooks at process startup."""

from __future__ import annotations

from arp.platform.hooks import register_extraction_runner


def wire() -> None:
    """Register cross-domain runtime hooks (idempotent)."""
    from arp.extraction import pipeline as extraction_pipeline

    def _create(*args, **kwargs):
        return extraction_pipeline.create_extraction_run(*args, **kwargs)

    async def _execute(*args, **kwargs):
        return await extraction_pipeline.execute_extraction_run(*args, **kwargs)

    register_extraction_runner(_create, _execute)
