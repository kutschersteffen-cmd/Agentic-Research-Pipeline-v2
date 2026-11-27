"""One count of everything waiting on a person's decision, for the top bar's badge."""

from __future__ import annotations

from pydantic import BaseModel

from arp.core.auth import Principal
from arp.db.runs import RunStore
from arp.review.items import list_open_items

DECISION_STAGES = {"checkpoint", "tracking"}


class WaitingCounts(BaseModel):
    review: int
    decisions: int
    ballots: int
    total: int


def waiting_counts(run_store: RunStore, principal: Principal, house_flow: dict) -> WaitingCounts:
    review = len(list_open_items(run_store, principal))
    decisions = sum(len(s["decisions"]) for s in house_flow["stages"] if s["id"] in DECISION_STAGES)
    return WaitingCounts(review=review, decisions=decisions, ballots=0, total=review + decisions)
