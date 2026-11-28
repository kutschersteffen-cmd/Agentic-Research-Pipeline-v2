"""Side-artifact file helpers and JSONB-safe normalization for `arp.db.runs` and `arp.db.observations`."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from pathlib import Path

from arp.core.atomic_io import atomic_write_text, read_text_utf8
from arp.core.jsonl_io import append_jsonl, read_jsonl
from arp.core.safe_path import safe_id


def _jsonb_safe(value):
    """What Postgres jsonb can store: NaN/±Infinity become None and NUL is stripped from strings
    (keys too). The file store wrote both; jsonb refuses them, which would fail a whole batch."""
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, dict):
        return {_jsonb_safe(k): _jsonb_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonb_safe(v) for v in value]
    return value


def done_keys_from_rows(result_rows: Iterable[dict], error_rows: Iterable[dict] = ()) -> set[str]:
    """Keys of items not to run again: every result row's `_key`, plus every
    error row a worker stopped for review (`review` set) -- a person decides
    those, so a resume must not redo them."""
    done = {row["_key"] for row in result_rows if row.get("_key")}
    done.update(row["key"] for row in error_rows if row.get("review") and row.get("key"))
    return done


class RunArtifactFiles:
    """Local side-artifact paths for a run (restatements, event logs, snapshots)."""

    def __init__(self, runs_dir: Path) -> None:
        self.runs_dir = runs_dir

    def run_dir(self, run_id: str) -> Path:
        d = self.runs_dir / safe_id(run_id, label="run_id")
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _restatements_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "restatement_candidates.jsonl"

    def _events_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "events.jsonl"

    def _snapshot_path(self, run_id: str, snapshot_id: str) -> Path:
        return self.run_dir(run_id) / "snapshots" / f"{safe_id(snapshot_id, label='snapshot_id')}.json"

    def read_restatements(self, run_id: str) -> list[dict]:
        return read_jsonl(self._restatements_path(run_id))

    def append_restatement(self, run_id: str, row: dict) -> None:
        append_jsonl(self._restatements_path(run_id), row)

    def read_events(self, run_id: str) -> list[dict]:
        return read_jsonl(self._events_path(run_id))

    def append_event(self, run_id: str, row: dict) -> None:
        append_jsonl(self._events_path(run_id), row)

    def read_snapshot(self, run_id: str, snapshot_id: str) -> dict | None:
        path = self._snapshot_path(run_id, snapshot_id)
        if not path.exists():
            return None
        return json.loads(read_text_utf8(path))

    def save_snapshot(self, run_id: str, snapshot_id: str, data: dict) -> None:
        path = self._snapshot_path(run_id, snapshot_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(data, sort_keys=True))
