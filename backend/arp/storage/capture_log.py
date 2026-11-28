"""Append-only capture-log reader for local document captures."""

from __future__ import annotations

from pathlib import Path

from arp.core.jsonl_io import read_jsonl
from arp.schemas.discovery import CaptureRecord

CAPTURE_LOG = "_captures.jsonl"


def latest_capture(documents_dir: Path, content_key: str) -> CaptureRecord | None:
    # ponytail: linear scan of the capture log, index by content_key if it grows past ~100k rows
    log = documents_dir / CAPTURE_LOG
    if not log.exists():
        return None
    rows = [r for r in read_jsonl(log) if r.get("content_key") == content_key]
    return CaptureRecord(**rows[-1]) if rows else None
