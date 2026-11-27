from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store, get_stream_store
from arp.db.runs import RunStore
from arp.review.waiting import WaitingCounts, waiting_counts
from arp.stewardship.config_store import StreamStore
from arp.stewardship.drafting import DraftStore

router = APIRouter(prefix="/api", tags=["review"])


@router.get("/waiting")
def get_waiting(
    run_store: RunStore = Depends(get_run_store),
    principal: Principal = Depends(current_user),
    streams: StreamStore = Depends(get_stream_store),
) -> WaitingCounts:
    try:
        pending_drafts = sum(1 for d in DraftStore(streams.root).list() if d.get("status") == "draft")
    except Exception as exc:
        raise HTTPException(503, "Stewardship decisions could not be counted") from exc
    return waiting_counts(run_store, principal, pending_drafts)
