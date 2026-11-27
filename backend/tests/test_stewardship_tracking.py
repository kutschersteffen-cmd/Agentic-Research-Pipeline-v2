from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from arp.api.routers.stewardship import CloseRequest, close_engagement, get_case_study
from arp.schemas.engagement import (
    Commitment,
    CommitmentStatus,
    CorrespondenceEntry,
    EngagementIssue,
    EngagementRecord,
    EscalationStage,
    InteractionType,
    IssueStatus,
)
from arp.stewardship import worklist
from arp.stewardship.config_store import StreamStore
from arp.storage.engagement_store import EngagementStore
from tests.conftest import PRINCIPAL

pytestmark = pytest.mark.usefixtures("pg")

TODAY = date(2026, 9, 27)


@pytest.fixture
def world(tmp_path):
    engagements = EngagementStore(tmp_path / "e")
    _, issue = engagements.open_issue("ACME", "Acme", theme="climate_transition")
    return engagements, StreamStore(tmp_path / "s"), issue


@pytest.mark.parametrize("due", ["end of 2026", "31/12/2025"])
def test_a_free_text_due_date_counts_as_no_due_date(due):
    issue = EngagementIssue(theme="t", commitments=[Commitment(text="x", target_date=due)])
    records = [EngagementRecord(company_id="C", name="C", issues=[issue])]
    sample = {"issuers": [{"issuer_id": "C", "name": "C", "sector": "x", "holding": {}}]}
    [row] = worklist.indicators(sample, records, [], {"C": ("monitor", False)}, {}, {}, TODAY)
    assert row["overdue_commitments"] == 0


def test_a_closed_engagement_gets_a_case_study_from_its_records_with_style_flags(world):
    engagements, streams, issue = world
    with pytest.raises(HTTPException) as still_open:
        get_case_study("ACME", issue.issue_id, streams, engagements)
    assert still_open.value.status_code == 422
    engagements.set_escalation_stage("ACME", issue.issue_id, EscalationStage.WRITTEN_ESCALATION_TO_BOARD, "Lead")
    commitment = Commitment(text="Publish interim targets", target_date="2026-06-30", recorded_by=PRINCIPAL.name)
    engagements.add_commitment("ACME", issue.issue_id, commitment)
    engagements.update_commitment_status("ACME", issue.issue_id, commitment.commitment_id, CommitmentStatus.VERIFIED, PRINCIPAL.name)
    engagements.add_correspondence(
        "ACME",
        issue.issue_id,
        CorrespondenceEntry(type="letter", summary="x", interaction_type=InteractionType.ADVOCACY_PRESSURE),
    )
    close_engagement(
        CloseRequest(
            company_id="ACME",
            issue_id=issue.issue_id,
            status="resolved",
            outcome="Thanks to our engagement the board set interim targets.",
        ),
        engagements,
        PRINCIPAL,
    )
    assert engagements.get("ACME").issues[0].status == IssueStatus.RESOLVED
    study = get_case_study("ACME", issue.issue_id, streams, engagements)
    assert "written escalation to board (decided by Lead)" in study["text"]
    assert "1 letter (advocacy pressure)" in study["text"]
    assert "Kept: Publish interim targets" in study["text"]
    assert study["text"].endswith("Outcome. Resolved: Thanks to our engagement the board set interim targets.")
    assert [f["phrase"] for f in study["style_flags"]] == ["thanks to our engagement"]
    with pytest.raises(HTTPException) as twice:
        close_engagement(
            CloseRequest(company_id="ACME", issue_id=issue.issue_id, status="closed", outcome="x"), engagements, PRINCIPAL
        )
    assert twice.value.status_code == 422
