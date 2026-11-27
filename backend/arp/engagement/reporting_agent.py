from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from arp.schemas.engagement import EngagementRecord, IssueStatus

"""Reporting Agent: periodic, non-LLM aggregation over the engagement
record store for quarterly/annual stewardship disclosure (e.g. PDCA-style
reporting). No agent call is needed here -- every number is a deterministic
rollup of already-decided, already-audited state, which is exactly what a
disclosure report should be."""


class EngagementStats(BaseModel):
    total_issues: int = 0
    open_issues: int = 0
    stalled_issues: int = 0
    resolved_issues: int = 0
    closed_issues: int = 0
    by_milestone_stage: dict[str, int] = Field(default_factory=dict)
    by_escalation_stage: dict[str, int] = Field(default_factory=dict)
    commitments_open: int = 0
    commitments_verified: int = 0
    commitments_missed: int = 0


class StewardshipReport(BaseModel):
    period_label: str
    engagement_stats: EngagementStats


def compile_engagement_stats(records: list[EngagementRecord]) -> EngagementStats:
    stats = EngagementStats()
    milestone_counter: Counter[str] = Counter()
    escalation_counter: Counter[str] = Counter()
    for record in records:
        for issue in record.issues:
            stats.total_issues += 1
            if issue.status == IssueStatus.OPEN:
                stats.open_issues += 1
            elif issue.status == IssueStatus.STALLED:
                stats.stalled_issues += 1
            elif issue.status == IssueStatus.RESOLVED:
                stats.resolved_issues += 1
            elif issue.status == IssueStatus.CLOSED:
                stats.closed_issues += 1
            milestone_counter[issue.milestone_stage.value] += 1
            escalation_counter[issue.escalation_stage.value] += 1
            for commitment in issue.commitments:
                if commitment.status.value == "open":
                    stats.commitments_open += 1
                elif commitment.status.value == "verified":
                    stats.commitments_verified += 1
                elif commitment.status.value == "missed":
                    stats.commitments_missed += 1
    stats.by_milestone_stage = dict(milestone_counter)
    stats.by_escalation_stage = dict(escalation_counter)
    return stats


def compile_report(records: list[EngagementRecord], period_label: str) -> StewardshipReport:
    return StewardshipReport(
        period_label=period_label,
        engagement_stats=compile_engagement_stats(records),
    )
