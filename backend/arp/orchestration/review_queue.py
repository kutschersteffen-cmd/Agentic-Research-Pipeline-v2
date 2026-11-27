from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from arp.review.state import (  # noqa: F401
    FINAL_STATES,
    PUBLIC_KEYS,
    ItemState,
    _kind,
    _num,
    _value,
    agrees,
    cosign_rule,
    item_state,
    same_value,
)
from arp.schemas.common import CompanyRef, now_iso
from arp.schemas.review import ReviewDecision
from arp.storage.run_store import RunStore

if TYPE_CHECKING:  # runtime import would cycle: api.auth -> api.deps -> research.pipeline -> here
    from arp.core.auth import Principal


def queue_for_review(
    run_store: RunStore, run_id: str, item_key: str, payload: dict, *, company: CompanyRef | None = None
) -> None:
    """Append a flagged item (low confidence, ungrounded citation, uncertain
    verdict) to the run's review queue for human sign-off. Never silently
    dropped and never silently included in the trusted output. `company`
    ties the item to its company (item keys cannot: extraction keys lead
    with the issuer key); a payload's own `company_id` wins.
    """
    row = {"item_key": item_key, "queued_at": now_iso(), **payload}
    if company is not None:
        row.setdefault("company_id", company.company_id)
    run_store.append_review_item(run_id, row)


def record_review_decision(
    run_store: RunStore,
    run_id: str,
    item_key: str,
    decision: str,
    reviewer: str | None,
    edited_value: dict | None,
    comment: str | None = None,
    *,
    principal: Principal | None = None,
) -> None:
    """decision: 'approve' | 'edit' | 'reject' | 'escalate'. Decisions are appended, never
    mutated in place, so the review queue keeps a full audit trail; the
    latest decision per item_key wins when results are materialized.

    item_key granularity is entirely up to the caller -- the Theme Builder
    keys at "{company_id}:{activity_id}", the Extraction Engine's per-field
    review keys at "{issuer_key}:{field_id}:{period}" (older runs: bare
    company_id); this function has no opinion
    on it. `comment` is a trailing optional kwarg specifically so existing
    positional call sites (e.g. themes.py) keep working unmodified.
    """
    if principal is not None:
        reviewer = principal.name
    row = {
        "item_key": item_key,
        "decision": decision,
        "reviewer": reviewer,
        "user_id": principal.user_id if principal else None,
        "role": principal.role if principal else None,
        "edited_value": edited_value,
        "comment": comment,
        "decided_at": now_iso(),
    }
    run_store.append_decision_row(run_id, row)


def latest_decisions(run_store: RunStore, run_id: str) -> dict[str, dict]:
    rows = run_store.read_decisions(run_id)
    latest: dict[str, dict] = {}
    for row in rows:
        latest[row["item_key"]] = row  # later rows overwrite earlier ones (JSONL append order)
    return latest


def decision_history(run_store: RunStore, run_id: str, item_key: str) -> list[dict]:
    """Every decision ever recorded for item_key, oldest first -- the full
    audit trail that latest_decisions() collapses to just the last row.
    """
    rows = run_store.read_decisions(run_id)
    return [r for r in rows if r["item_key"] == item_key]


def get_review_queue(run_store: RunStore, run_id: str) -> dict:
    rows = run_store.read_review_queue(run_id)
    decisions = latest_decisions(run_store, run_id)
    pending = [r for r in rows if r["item_key"] not in decisions]
    decided = [{"item": r, "decision": decisions[r["item_key"]]} for r in rows if r["item_key"] in decisions]
    return {"pending": pending, "decided": decided}


def record_cosign(run_store: RunStore, run_id: str, item_key: str, principal: Principal) -> None:
    """Second sign-off on the latest decision for item_key. Bound to that
    decision's decided_at, so any later decision invalidates it."""
    decision = latest_decisions(run_store, run_id).get(item_key)
    if decision is None:
        raise ValueError("nothing to co-sign")
    if decision.get("step"):
        raise ValueError("use a second review")
    if principal.user_id == decision.get("user_id"):  # legacy rows lack user_id: allowed
        raise ValueError("co-sign must be a different person")
    run_store.append_cosign(
        run_id,
        {
            "item_key": item_key,
            "user_id": principal.user_id,
            "name": principal.name,
            "role": principal.role,
            "decision_decided_at": decision["decided_at"],
            "cosigned_at": now_iso(),
        },
    )


def item_states(run_store: RunStore, run_id: str) -> dict[str, ItemState]:
    """Every decided item's state, under the run type's co-sign rule."""
    manifest = run_store.load_manifest(run_id)
    cosign_required = cosign_rule(manifest.run_type if manifest else "")
    rows: dict[str, list[dict]] = defaultdict(list)
    for r in run_store.read_decisions(run_id):
        rows[r["item_key"]].append(r)
    signed: dict[str, set[str]] = defaultdict(set)
    for c in run_store.read_cosigns(run_id):
        signed[c["item_key"]].add(c["decision_decided_at"])
    return {k: item_state(v, cosigned_at=signed[k], cosign_required=cosign_required) for k, v in rows.items()}


def effective_decisions(run_store: RunStore, run_id: str) -> dict[str, dict]:
    """The effective row of every item in a final state; a `correct` row also carries
    `edited_value` so existing readers keep working."""
    out = {}
    for k, s in item_states(run_store, run_id).items():
        if s.state in FINAL_STATES:
            row = s.effective
            # legacy record_review_decision rows carry only `edited_value` (issue #406)
            out[k] = {**row, "edited_value": row.get("corrected_value") or row.get("edited_value")} if row.get("decision") == "correct" else row
    return out


def append_decision(run_store: RunStore, run_id: str, d: ReviewDecision) -> None:
    run_store.append_decision_row(run_id, d.model_dump(mode="json"))


def public_decision(row: dict, principal: Principal | None) -> dict:
    """What clients may see of a decision row: never `user_id`, never `reviewer`."""
    return {k: row.get(k) for k in PUBLIC_KEYS} | {"mine": principal is not None and row.get("user_id") == principal.user_id}


def blind_for(s: ItemState, principal: Principal, *, high_risk: bool) -> bool:
    return (
        high_risk
        and s.state == "first_done"
        and principal.role != "approver"
        and principal.user_id != s.first.get("user_id")
    )
