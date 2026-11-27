"""Versioned house stewardship configs with four-eyes activation:
- `priority_weights` (Selection Workbench priority scoring)
- `phrase_blocklist` (Outreach Drafting E8 style check)
- `monitoring_rules` (ESG portfolio monitoring triggers)

Stored under `<stewardship_root>/policies/<policy_id>/vN.json` + `activations.jsonl`.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from arp.stewardship import monitoring, style
from arp.stewardship.style import load
from arp.storage.atomic_io import atomic_write_text, read_text_utf8


def _validate_monitoring(graph: dict, sample: dict) -> None:
    if not isinstance(graph, dict) or not graph.get("nodes"):
        raise ValueError("A monitoring policy is a rule graph with nodes and edges")
    try:
        monitoring.evaluate(graph, sample, [])
    except RuntimeError as exc:
        raise ValueError(f"The monitoring rules do not run: {exc}") from exc


def load_priority_weights() -> dict:
    return load("priority_weights.json")


def component_ids() -> list[str]:
    return [c["id"] for c in load_priority_weights()["components"]]


def validate_weights(content: dict, _sample: dict | None = None) -> None:
    comps = content.get("components") if isinstance(content, dict) else None
    if not isinstance(comps, list) or not all(isinstance(c, dict) for c in comps):
        raise ValueError("A priority_weights version lists components: [{id, weight}]")
    ids, known = [c.get("id") for c in comps], component_ids()
    if missing := [i for i in known if i not in ids]:
        raise ValueError(f"Missing components: {', '.join(missing)}")
    if unknown := [str(i) for i in ids if i not in known]:
        raise ValueError(f"Unknown components: {', '.join(unknown)}")
    if twice := sorted(i for i, n in Counter(ids).items() if n > 1):
        raise ValueError(f"Components listed twice: {', '.join(twice)}")
    for c in comps:
        w = c.get("weight")
        if isinstance(w, bool) or not isinstance(w, int) or not 0 <= w <= 100:
            raise ValueError(f"The weight of {c['id']} must be a whole number from 0 to 100")
    if (total := sum(c["weight"] for c in comps)) != 100:
        raise ValueError(f"Weights must add up to 100 (now {total})")


POLICIES: dict[str, dict[str, Callable]] = {
    "monitoring_rules": {"default": monitoring.load_graph, "validate": _validate_monitoring},
    "phrase_blocklist": {"default": style.load_blocklist, "validate": style.validate_blocklist},
    "priority_weights": {"default": load_priority_weights, "validate": validate_weights},
}


class PolicyStore:
    def __init__(self, root: Path) -> None:
        self.root = root / "policies"

    def _spec(self, policy_id: str, key: str) -> Callable:
        fn = POLICIES.get(policy_id, {}).get(key)
        if fn is None:
            raise KeyError(policy_id)
        return fn

    def _dir(self, policy_id: str) -> Path:
        self._spec(policy_id, "default")
        return self.root / policy_id

    def versions(self, policy_id: str) -> list[dict]:
        d = self._dir(policy_id)
        metas = [{"version": 0, "note": "Bundled draft", "created_by": "system", "created_at": None}]
        if d.exists():
            for path in sorted(d.glob("v*.json"), key=lambda p: int(p.stem[1:])):
                metas.append({k: v for k, v in json.loads(read_text_utf8(path)).items() if k != "content"})
        return metas

    def content(self, policy_id: str, version: int) -> dict:
        if version == 0:
            return self._spec(policy_id, "default")()
        path = self._dir(policy_id) / f"v{version}.json"
        if not path.exists():
            raise KeyError(f"{policy_id} v{version}")
        content = json.loads(read_text_utf8(path))["content"]
        if policy_id == "priority_weights":
            have = {c["id"] for c in content["components"]}
            content = {**content, "components": [*content["components"], *({"id": i, "weight": 0} for i in component_ids() if i not in have)]}
        return content

    def activations(self, policy_id: str) -> list[dict]:
        path = self._dir(policy_id) / "activations.jsonl"
        return [json.loads(line) for line in read_text_utf8(path).splitlines() if line.strip()] if path.exists() else []

    def active_version(self, policy_id: str) -> int:
        log = self.activations(policy_id)
        return log[-1]["version"] if log else 0

    def active(self, policy_id: str) -> dict:
        return self.content(policy_id, self.active_version(policy_id))

    def save(self, policy_id: str, content: dict, note: str, created_by: str, sample: dict) -> int:
        if not created_by.strip():
            raise ValueError("A policy version needs created_by")
        self._spec(policy_id, "validate")(content, sample)
        version = max(v["version"] for v in self.versions(policy_id)) + 1
        d = self._dir(policy_id)
        d.mkdir(parents=True, exist_ok=True)
        record = {
            "version": version,
            "note": note,
            "created_by": created_by,
            "created_at": datetime.now(UTC).isoformat(),
            "content": content,
        }
        atomic_write_text(d / f"v{version}.json", json.dumps(record, indent=2, ensure_ascii=False))
        return version

    def activate(self, policy_id: str, version: int, approved_by: str) -> dict:
        if not approved_by.strip():
            raise ValueError("Activating a policy version needs approved_by")
        self.content(policy_id, version)
        meta = next(v for v in self.versions(policy_id) if v["version"] == version)
        if version > 0 and meta["created_by"].strip().lower() == approved_by.strip().lower():
            raise ValueError("Four-eyes rule: a version must be activated by someone other than the person who saved it")
        row = {"version": version, "approved_by": approved_by, "approved_at": datetime.now(UTC).isoformat()}
        log = [*self.activations(policy_id), row]
        atomic_write_text(self._dir(policy_id) / "activations.jsonl", "\n".join(json.dumps(r) for r in log) + "\n")
        return row


class StreamStore:
    """Root directory holder for stewardship state (house settings, triggers, weights, programmes, notes, drafts)."""

    def __init__(self, root: Path) -> None:
        self.root = root
