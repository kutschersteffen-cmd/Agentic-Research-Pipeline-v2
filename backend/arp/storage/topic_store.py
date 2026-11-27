from __future__ import annotations

import json
from pathlib import Path

from arp.db.json_document_repo import JsonDocumentRepo
from arp.schemas.emerging_themes import EmergingThemeCandidate, LineageEvent, TopicCluster
from arp.storage.atomic_io import atomic_write_text, read_text_utf8
from arp.storage.jsonl_io import append_jsonl, read_jsonl
from arp.storage.safe_path import safe_id


class TopicStateStore:
    """Persistence for the Emerging Themes Scanner's period-over-period state:
    backed by Postgres `app_documents` when `dsn` is provided, or by local JSON/JSONL
    files under `topics_dir` otherwise.
    """

    def __init__(self, topics_dir: Path | None = None, *, dsn: str | None = None) -> None:
        if topics_dir is None and not dsn:
            raise ValueError("TopicStateStore requires either topics_dir or dsn")
        self.topics_dir = topics_dir
        self.periods_dir = topics_dir / "periods" if topics_dir is not None else None
        self.lineage_dir = topics_dir / "lineage" if topics_dir is not None else None
        self._periods_repo = JsonDocumentRepo(dsn, "topic_periods") if dsn else None
        self._lineage_repo = JsonDocumentRepo(dsn, "topic_lineage") if dsn else None
        self._candidates_repo = JsonDocumentRepo(dsn, "topic_candidates") if dsn else None

    def _period_path(self, period: str) -> Path:
        assert self.periods_dir is not None
        return self.periods_dir / f"{safe_id(period, label='period')}.json"

    def _lineage_path(self, period: str) -> Path:
        assert self.lineage_dir is not None
        return self.lineage_dir / f"{safe_id(period, label='period')}.jsonl"

    def candidates_path(self) -> Path:
        assert self.topics_dir is not None
        return self.topics_dir / "candidates.jsonl"

    def save_period(self, period: str, clusters: list[TopicCluster]) -> None:
        key = safe_id(period, label="period")
        dumped = [c.model_dump(mode="json") for c in clusters]
        if self._periods_repo is not None:
            self._periods_repo.put(key, {"clusters": dumped})
            return
        path = self._period_path(period)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(dumped, indent=2))

    def load_period(self, period: str) -> list[TopicCluster] | None:
        key = safe_id(period, label="period")
        if self._periods_repo is not None:
            doc = self._periods_repo.get(key)
            if doc is None:
                return None
            return [TopicCluster.model_validate(row) for row in doc.get("clusters", [])]
        path = self._period_path(period)
        if not path.exists():
            return None
        return [TopicCluster.model_validate(row) for row in json.loads(read_text_utf8(path))]

    def list_periods(self) -> list[str]:
        if self._periods_repo is not None:
            return self._periods_repo.list_keys()
        assert self.periods_dir is not None
        if not self.periods_dir.exists():
            return []
        return sorted(p.stem for p in self.periods_dir.glob("*.json"))

    def latest_period_before(self, period: str) -> str | None:
        """The most recent saved period strictly before `period`, for
        lineage linking -- periods sort lexicographically because callers
        are expected to use ISO date/week keys."""
        earlier = [p for p in self.list_periods() if p < period]
        return earlier[-1] if earlier else None

    def save_lineage_events(self, period: str, events: list[LineageEvent]) -> None:
        key = safe_id(period, label="period")
        dumped = [event.model_dump(mode="json") for event in events]
        if self._lineage_repo is not None:
            self._lineage_repo.put(key, {"events": dumped})
            return
        path = self._lineage_path(period)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for row in dumped:
                f.write(json.dumps(row) + "\n")

    def load_lineage_events(self, period: str) -> list[LineageEvent]:
        """Used by scoring.py::compute_persistence to walk a cluster's
        GROWTH chain back through periods older than the one currently
        being scored (the current period's own events are passed in
        directly by the caller, since they haven't been saved yet at
        scoring time)."""
        if self._lineage_repo is not None:
            doc = self._lineage_repo.get(safe_id(period, label="period")) or {}
            raw_rows = doc.get("events", [])
        else:
            raw_rows = read_jsonl(self._lineage_path(period))
        events = []
        for row in raw_rows:
            try:
                events.append(LineageEvent.model_validate(row))
            except ValueError:  # a decodable row that is not a LineageEvent
                continue
        return events

    def load_recent_periods(self, before: str, n: int) -> list[list[TopicCluster]]:
        """The n saved periods strictly before `before`, each period's
        clusters as saved -- the trailing baseline scoring.py::compute_velocity
        uses for a BIRTH cluster with no prior self to compare against."""
        periods = sorted(p for p in self.list_periods() if p < before)[-n:]
        return [self.load_period(p) or [] for p in periods]

    def append_candidate(self, candidate: EmergingThemeCandidate) -> None:
        payload = candidate.model_dump(mode="json")
        if self._candidates_repo is not None:
            self._candidates_repo.update("all", lambda cur: {"candidates": [*(cur or {}).get("candidates", []), payload]})
            return
        append_jsonl(self.candidates_path(), payload)

    def list_candidates(self) -> list[EmergingThemeCandidate]:
        if self._candidates_repo is not None:
            doc = self._candidates_repo.get("all") or {}
            raw_rows = doc.get("candidates", [])
        else:
            raw_rows = read_jsonl(self.candidates_path())
        candidates = []
        for row in raw_rows:
            try:
                candidates.append(EmergingThemeCandidate.model_validate(row))
            except ValueError:  # a decodable row that is not a candidate
                continue
        return candidates
