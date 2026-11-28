"""Public facade for the Argus bounded context."""

from __future__ import annotations

from arp.argus.flows import FlowStore
from arp.extraction.pipeline import create_extraction_run, execute_extraction_run
from arp.ingestion.xbrl import XbrlFactSource
from arp.job_runtime.review_queue import queue_for_review
from arp.review.decide import bulk_accept, decide
from arp.walkthrough.view import build_walkthrough

DOMAIN_NAME = "argus"

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
