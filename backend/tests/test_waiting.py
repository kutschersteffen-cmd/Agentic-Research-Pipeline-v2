from __future__ import annotations

import pytest

from arp.api import main  # noqa: F401  (registers the routers)
from arp.api.routers import waiting as waiting_router
from arp.review.items import list_open_items
from arp.review.waiting import waiting_counts
from tests.test_review_decide import (
    ALICE,
    APPROVE,
    CORRECT,
    client,
    decide,
    env,  # noqa: F401  (the fixture)
)

pytestmark = pytest.mark.usefixtures("pg")


def counts(rs, pending_drafts: int = 0):
    return waiting_counts(rs, ALICE, pending_drafts)


def test_ac1_shape(env):  # noqa: F811
    r = client(ALICE).get("/api/waiting")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"review", "decisions", "ballots", "total"}
    assert all(type(v) is int for v in body.values())
    assert body["total"] == body["review"] + body["decisions"] + body["ballots"]


def test_ac2_review_equals_open_items(env):  # noqa: F811
    items = client(ALICE).get("/api/review/items").json()["items"]
    assert len({i["run_id"] for i in items}) >= 2
    assert client(ALICE).get("/api/waiting").json()["review"] == len(items) == len(list_open_items(env[0], ALICE))


def test_ac3_single_review_approve_drops_one(env):  # noqa: F811
    before = counts(env[0]).review
    r = decide(ALICE, APPROVE)
    assert r.status_code == 200 and r.json()["state"] == "final", r.text
    assert counts(env[0]).review == before - 1


def test_ac3b_first_of_two_unchanged(env):  # noqa: F811
    before = counts(env[0]).review
    assert decide(ALICE, CORRECT).json()["state"] == "first_done"
    assert counts(env[0]).review == before


def test_ac4_decisions_counts_pending_drafts(env):  # noqa: F811
    c = waiting_counts(env[0], ALICE, 3)
    assert c.decisions == 3 and c.total == c.review + 3


def test_ac4b_ballots_always_zero(env):  # noqa: F811
    assert counts(env[0]).ballots == 0


def test_broken_draft_store_is_503(env, monkeypatch):  # noqa: F811
    class _Broken:
        def __init__(self, *_a, **_k):
            pass

        def list(self):
            raise ValueError("bad store")

    monkeypatch.setattr(waiting_router, "DraftStore", _Broken)
    r = client(ALICE).get("/api/waiting")
    assert r.status_code == 503 and "could not be counted" in r.text
