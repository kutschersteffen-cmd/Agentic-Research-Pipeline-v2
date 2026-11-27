"""One count of everything waiting on a person's decision, for the top bar's badge."""

from __future__ import annotations

from pydantic import BaseModel

from arp.core.auth import Principal
from arp.db.runs import RunStore
from arp.review.items import list_open_items


class WaitingCounts(BaseModel):
    review: int
    decisions: int
    ballots: int
    total: int


def waiting_counts(run_store: RunStore, principal: Principal, pending_drafts: int = 0) -> WaitingCounts:
    review = len(list_open_items(run_store, principal))
    return WaitingCounts(review=review, decisions=pending_drafts, ballots=0, total=review + pending_drafts)
