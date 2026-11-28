"""Pure review-state fold and co-sign rule primitives (zero outbound domain imports)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

FINAL_STATES = frozenset({"second_done", "final"})

PUBLIC_KEYS = (
    "item_key",
    "decision",
    "reason_code",
    "role",
    "decided_at",
    "comment",
    "corrected_value",
    "correction_citation",
    "snapshot_id",
    "step",
    "edited_value",
)

LEGACY_COSIGN = {"extraction": {"edit"}}


def cosign_rule(run_type: str) -> set[str]:
    return LEGACY_COSIGN.get(run_type, set())


@dataclass
class ItemState:
    state: str = "pending"
    escalated: bool = False
    first: dict | None = None
    second: dict | None = None
    effective: dict | None = None
    rows: list[dict] = field(default_factory=list)  # every row of the item, oldest first


def _num(v) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def same_value(a, b) -> bool:
    fa, fb = _num(a), _num(b)
    if fa is not None and fb is not None:
        return math.isclose(fa, fb, rel_tol=1e-9)
    return str(a).strip() == str(b).strip()


def _kind(row: dict) -> str | None:
    return "correct" if row.get("decision") == "edit" else row.get("decision")


def _value(row: dict):
    return (row.get("corrected_value") or row.get("edited_value") or {}).get("value")


def agrees(first: dict, second: dict) -> bool:
    if _kind(first) != _kind(second):
        return False
    return _kind(first) != "correct" or same_value(_value(first), _value(second))


def item_state(rows: list[dict], *, cosigned_at: set[str], cosign_required: set[str]) -> ItemState:
    """Fold one item's decision rows, oldest first, into its review state."""
    s = ItemState(rows=list(rows))
    for row in rows:
        step, decision = row.get("step"), row.get("decision")
        if step == "second":
            if s.state != "first_done":  # a stray second review changes nothing
                continue
            ok = s.first is not None and agrees(s.first, row)
            s.state, s.effective, s.second = ("second_done", s.first, row) if ok else ("disagreed", None, row)
        elif step == "resolution":
            s.state, s.effective, s.escalated = "final", row, False
        else:  # "first" or a legacy row (no step): starts a new round
            s.first, s.second, s.effective = row, None, None
            s.escalated = decision == "escalate"
            if s.escalated:
                s.state = "pending"
            elif step == "first":
                s.state = "first_done" if row.get("second_required") else "final"
            elif decision in cosign_required:
                s.state = "second_done" if row.get("decided_at") in cosigned_at else "first_done"
            else:
                s.state = "final"
            if s.state in FINAL_STATES:
                s.effective = row
    return s
