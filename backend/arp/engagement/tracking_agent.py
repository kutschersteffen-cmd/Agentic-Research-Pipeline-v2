from __future__ import annotations

from typing import Any

from arp.schemas.engagement import (
    Commitment,
    CorrespondenceEntry,
    EngagementRecord,
    MilestoneStage,
)

EngagementStore = Any

"""Non-LLM logic: logs outcomes and advances milestone state on the record
store. No sub-agent here talks to a model -- this is deliberately
mechanical bookkeeping, kept separate from Research/Drafting so a bug in an
LLM prompt can never silently corrupt milestone state.
"""


def log_outreach_sent(
    store: EngagementStore, company_id: str, issue_id: str, summary: str, sent_by: str, doc_ref: str | None = None
) -> EngagementRecord:
    """Called only after the human send-authorization checkpoint has
    already happened -- this function has no opinion on authorization, it
    just records that outreach went out and advances the milestone."""
    record = store.get(company_id)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None) if record else None
    if issue and any(c.type == "letter" and c.summary == summary and c.doc_ref == doc_ref for c in issue.correspondence):
        return record  # the same letter logged again: nothing new happened
    store.add_correspondence(
        company_id,
        issue_id,
        CorrespondenceEntry(type="letter", summary=summary, doc_ref=doc_ref, logged_by=sent_by),
    )
    return store.set_milestone_stage(
        company_id, issue_id, MilestoneStage.CONTACTED, reason=f"Outreach sent by {sent_by}.", forward_only=True
    )


def log_meeting_summary_validated(
    store: EngagementStore,
    company_id: str,
    issue_id: str,
    summary: str,
    commitments: list[str],
    validated_by: str,
) -> EngagementRecord:
    """Called only after the human meeting-notes-validation checkpoint --
    logs the validated summary as correspondence and, if the human-approved
    summary named any commitments, logs each one and advances the
    milestone to COMMITMENT_MADE; otherwise advances to RESPONSE_RECEIVED.
    """
    store.add_correspondence(
        company_id, issue_id, CorrespondenceEntry(type="meeting", summary=summary, logged_by=validated_by)
    )
    for text in commitments:
        store.add_commitment(company_id, issue_id, Commitment(text=text))
    stage = MilestoneStage.COMMITMENT_MADE if commitments else MilestoneStage.RESPONSE_RECEIVED
    reason = f"Meeting notes validated by {validated_by}." + (f" {len(commitments)} commitment(s) logged." if commitments else "")
    return store.set_milestone_stage(company_id, issue_id, stage, reason=reason, forward_only=True)


from arp.schemas.engagement import (  # noqa: E402, F401
    EVIDENCE_MSG,
    MissingEvidence,
    check_evidence,
    log_commitment_verified,
)
