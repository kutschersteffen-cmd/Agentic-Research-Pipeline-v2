"""Closing an engagement with its outcome and compiling deterministic E7 case studies."""

from __future__ import annotations

from collections import Counter

from arp.schemas.engagement import (
    CommitmentStatus,
    CorrespondenceEntry,
    CorrespondenceType,
    EngagementRecord,
    IssueStatus,
)
from arp.stewardship.style import check
from arp.storage.engagement_store import EngagementStore

CLOSED = (IssueStatus.RESOLVED, IssueStatus.CLOSED)


def _w(s: str) -> str:
    return s.replace("_", " ")


def _day(iso: str) -> str:
    return iso[:10]


def close(
    engagements: EngagementStore,
    company_id: str,
    issue_id: str,
    status: IssueStatus,
    outcome: str,
    decided_by: str,
):
    """Closes an engagement with its outcome, logged as correspondence so the
    case study and reports can cite it."""
    if status not in CLOSED:
        raise ValueError("An engagement is closed as resolved or closed")
    if not outcome.strip() or not decided_by.strip():
        raise ValueError("Closing needs an outcome and decided_by")
    record = engagements.get(company_id)
    issue = next((i for i in record.issues if i.issue_id == issue_id), None) if record else None
    if issue is None:
        raise KeyError(f"{company_id}/{issue_id}")
    if issue.status in CLOSED:
        raise ValueError(f"Already {issue.status.value}")
    engagements.add_correspondence(
        company_id,
        issue_id,
        CorrespondenceEntry(type=CorrespondenceType.OTHER, summary=f"Outcome ({status.value}): {outcome}", logged_by=decided_by),
    )
    return engagements.set_issue_status(company_id, issue_id, status)


def case_study(record: EngagementRecord, issue_id: str, blocklist: dict) -> dict:
    """E7: a case study compiled from the records of a closed engagement."""
    issue = next((i for i in record.issues if i.issue_id == issue_id), None)
    if issue is None:
        raise KeyError(issue_id)
    if issue.status not in CLOSED:
        raise ValueError("Case studies are drafted only for closed engagements")
    steps = [f"{_day(t.changed_at)}: {_w(t.stage.value)} (decided by {t.decided_by})" for t in issue.escalation_history]
    top = issue.escalation_history[-1].stage.value if issue.escalation_history else issue.escalation_stage.value
    contacts = Counter(
        f"{c.type.value}{' (' + _w(c.interaction_type.value) + ')' if c.interaction_type else ''}"
        for c in issue.correspondence
        if not c.summary.startswith("Outcome (")
    )
    logged = next((c.summary for c in reversed(issue.correspondence) if c.summary.startswith("Outcome (")), None)
    outcome = f"{issue.status.value.capitalize()}: {logged.split('): ', 1)[1]}" if logged else f"Closed as {issue.status.value}."
    kept = [c for c in issue.commitments if c.status == CommitmentStatus.VERIFIED]
    missed = [c for c in issue.commitments if c.status == CommitmentStatus.MISSED]
    paragraphs = [
        f"{record.name}: {_w(issue.theme)}",
        f"Why we engaged. Opened on {_day(issue.opened_at)} ({_w(issue.source.value)})"
        + (f": {issue.source_detail}." if issue.source_detail else "."),
        "What we did. "
        + (", ".join(f"{n} {k}" for k, n in sorted(contacts.items())) + "." if contacts else "No outreach logged.")
        + f" Highest escalation step: {_w(top)}.",
        ("Escalation steps. " + "; ".join(steps) + ".") if steps else "Escalation steps. None beyond private engagement.",
        "Commitments. "
        + (f"Kept: {'; '.join(c.text for c in kept)}. " if kept else "")
        + (f"Missed: {'; '.join(c.text for c in missed)}. " if missed else "")
        + ("None recorded." if not kept and not missed else ""),
        f"Outcome. {outcome}",
    ]
    text = "\n\n".join(paragraphs)
    return {
        "company_id": record.company_id,
        "company": record.name,
        "issue_id": issue_id,
        "theme": issue.theme,
        "status": issue.status.value,
        "text": text,
        "style_flags": check(text, blocklist),
        "provenance": "Compiled from the engagement record (escalation history, correspondence, commitments); no model-written text.",
    }
