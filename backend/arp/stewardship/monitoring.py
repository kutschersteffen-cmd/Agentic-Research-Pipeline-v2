"""Stage 1 monitoring rules: which company data raises a trigger.

The rules are a ZEN decision table (`data/house_monitoring_policy.graph.json`,
hit policy `collect`, output path `triggers`), so one issuer can raise several
triggers. Each trigger has a type from the Trigger Event enum, a theme, a
severity, the rule that fired and a reason. Missing data never raises a
trigger: decision-table cells do not match null.

A trigger is matched to an open engagement on the same issuer and theme; an
unmatched trigger makes the issuer a selection candidate, and a person can open
an engagement from it.
"""

from __future__ import annotations

import ast
from collections import Counter

from arp.schemas.engagement import EngagementRecord, EscalationStage, IssueStatus
from arp.stewardship.style import load

OPEN = {IssueStatus.OPEN, IssueStatus.STALLED}
TYPES = {
    "vote_outcome",
    "controversy",
    "score_change",
    "holding_change",
    "commitment_missed",
    "engagement_stalled",
    "calendar",
    "manual",
}
SEVERITIES = {"low", "medium", "high"}


def load_graph() -> dict:
    return load("house_monitoring_policy.graph.json")


def open_engagements(records: list[EngagementRecord]) -> dict[tuple[str, str], str]:
    """(company_id, theme) -> the open (or stalled) engagement's issue_id, the last one where there are several."""
    return {(r.company_id, i.theme): i.issue_id for r in records for i in r.issues if i.status in OPEN}


def _nest(flat: dict[str, object]) -> dict:
    out: dict = {}
    for key, value in flat.items():
        cur = out
        parts = key.split(".")
        for p in parts[:-1]:
            cur = cur.setdefault(p, {})
        cur[parts[-1]] = value
    return out


def _get_field(ctx: dict, field: str) -> object:
    cur: object = ctx
    for part in field.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _parse_literal(expr: str) -> object:
    s = expr.strip()
    if s == "true":
        return True
    if s == "false":
        return False
    try:
        return ast.literal_eval(s)
    except (SyntaxError, ValueError, TypeError, RecursionError) as exc:
        raise ValueError(f"Invalid rule literal: {expr!r}") from exc


def _match_cell(value: object, expr: object) -> bool:
    if expr is None:
        return True
    if not isinstance(expr, str):
        expr = str(expr)
    s = expr.strip()
    if not s:
        return True
    if value is None:
        return False
    for op, fn in (
        ("<=", lambda a, b: a <= b),
        (">=", lambda a, b: a >= b),
        ("<", lambda a, b: a < b),
        (">", lambda a, b: a > b),
    ):
        if s.startswith(op):
            if isinstance(value, bool) or not isinstance(value, int | float):
                return False
            try:
                threshold = float(s[len(op) :].strip())
            except ValueError as exc:
                raise ValueError(f"Invalid numeric threshold: {expr!r}") from exc
            return fn(value, threshold)
    target = _parse_literal(s)
    if isinstance(value, bool) != isinstance(target, bool):
        return False
    return value == target


def _eval_table(graph: dict, ctx: dict) -> list[dict]:
    nodes = graph.get("nodes") if isinstance(graph, dict) else None
    if not isinstance(nodes, list):
        raise ValueError("Monitoring graph must contain a list of nodes")
    table = next((n for n in nodes if isinstance(n, dict) and n.get("type") == "decisionTableNode"), None)
    if not table or not isinstance(table.get("content"), dict):
        raise ValueError("Monitoring graph has no decisionTableNode")
    content = table["content"]
    inputs = content.get("inputs") or []
    outputs = content.get("outputs") or []
    rules = content.get("rules") or []
    if not (isinstance(inputs, list) and isinstance(outputs, list) and isinstance(rules, list)):
        raise ValueError("decisionTableNode inputs, outputs, and rules must be lists")
    hits = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("Each decisionTableNode rule must be an object")
        try:
            matched = all(_match_cell(_get_field(ctx, inp["field"]), rule.get(inp["id"])) for inp in inputs)
            if matched:
                hits.append({out["field"]: _parse_literal("''" if rule.get(out["id"]) is None else str(rule.get(out["id"]))) for out in outputs})
        except (KeyError, TypeError, AttributeError) as exc:
            raise ValueError(f"Malformed decisionTableNode entry: {exc}") from exc
    return hits


def issuer_contexts(sample: dict, records: list[EngagementRecord]) -> list[dict]:
    """One context per issuer: holdings, company flags and engagement history."""
    history: dict[str, dict] = {}
    for r in records:
        open_issues = [i for i in r.issues if i.status in OPEN]
        history[r.company_id] = {
            "open_engagements": len(open_issues),
            "escalated": any(i.escalation_stage != EscalationStage.PRIVATE_ENGAGEMENT for i in open_issues),
        }
    return [
        {
            "issuer_id": i["issuer_id"],
            "name": i["name"],
            "holding": i.get("holding", {}),
            "issuer": {**_nest(i["fields"]), "region": i["region"], "sector": i["sector"]},
            "history": history.get(i["issuer_id"], {"open_engagements": 0, "escalated": False}),
        }
        for i in sample["issuers"]
    ]


def evaluate(graph: dict, sample: dict, records: list[EngagementRecord]) -> list[dict]:
    """Every trigger the rules raise on the sample, matched to open engagements."""
    open_by_theme = open_engagements(records)
    out = []
    for c in issuer_contexts(sample, records):
        for t in _eval_table(graph, c):
            if t.get("type") not in TYPES or t.get("severity") not in SEVERITIES or not t.get("theme"):
                raise ValueError(f"Monitoring rule {t.get('rule')!r} returned an invalid trigger for {c['issuer_id']}: {t}")
            out.append(
                {
                    "issuer_id": c["issuer_id"],
                    "company": c["name"],
                    "sector": c["issuer"]["sector"],
                    **{k: t.get(k) for k in ("type", "theme", "severity", "rule", "reason")},
                    "engagement_id": open_by_theme.get((c["issuer_id"], t["theme"])),
                    # raised by demo votes alone: no against-management vote outside the demo sources (owner, 15 Nov 2026)
                    "demo": t.get("rule") == "vote_against_management"
                    and not c["issuer"].get("vote", {}).get("against_management_non_demo"),
                }
            )
    return out


def preview(candidate: dict, active: dict, sample: dict, records: list[EngagementRecord]) -> dict:
    """What a candidate rule set would raise against the active one."""
    new, old = evaluate(candidate, sample, records), evaluate(active, sample, records)
    new_ids, old_ids = {t["issuer_id"] for t in new}, {t["issuer_id"] for t in old}
    names = {t["issuer_id"]: t["company"] for t in new + old}
    return {
        "companies": len(sample["issuers"]),
        "triggers_candidate": len(new),
        "triggers_active": len(old),
        "flagged_candidate": len(new_ids),
        "flagged_active": len(old_ids),
        "by_rule_candidate": dict(Counter(t["rule"] for t in new)),
        "by_rule_active": dict(Counter(t["rule"] for t in old)),
        "newly_flagged": [{"issuer_id": i, "company": names[i]} for i in sorted(new_ids - old_ids)],
        "no_longer_flagged": [{"issuer_id": i, "company": names[i]} for i in sorted(old_ids - new_ids)],
        "triggers": new,
    }
