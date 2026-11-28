"""Public facade for the Argus bounded context."""

from __future__ import annotations

from arp.argus.flows import FlowStore
from arp.extraction import pipeline as _extraction_pipeline
from arp.ingestion.xbrl import XbrlFactSource
from arp.job_runtime.review_queue import queue_for_review
from arp.review.decide import bulk_accept, decide
from arp.walkthrough.view import build_walkthrough

DOMAIN_NAME = "argus"


def create_extraction_run(*args, **kwargs):
    """Create a new extraction run via Argus's extraction pipeline."""
    return _extraction_pipeline.create_extraction_run(*args, **kwargs)


async def execute_extraction_run(*args, **kwargs):
    """Execute an extraction run via Argus's extraction pipeline."""
    return await _extraction_pipeline.execute_extraction_run(*args, **kwargs)


__all__ = [
    "DOMAIN_NAME",
    "FlowStore",
    "XbrlFactSource",
    "build_walkthrough",
    "bulk_accept",
    "create_extraction_run",
    "decide",
    "execute_extraction_run",
    "queue_for_review",
]
