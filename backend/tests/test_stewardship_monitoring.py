from __future__ import annotations

import copy
import json

import pytest
from fastapi import HTTPException

from arp.api.routers.stewardship import (
    OpenFromTriggerRequest,
    monitoring_triggers,
    open_engagement_from_trigger,
)
from arp.stewardship.config_store import PolicyStore, StreamStore
from arp.stewardship.monitoring import evaluate, load_graph, preview
from arp.stewardship.universe import SAMPLE_PATH
from arp.storage.engagement_store import EngagementStore
from tests.conftest import PRINCIPAL

SAMPLE = json.loads(SAMPLE_PATH.read_text())


pytestmark = pytest.mark.usefixtures("sample_house_universe", "pg")


def _one(fields: dict, holding: dict | None = None) -> dict:
    return {
        "issuers": [{"issuer_id": "X", "name": "X", "region": "EU", "sector": "S", "fields": fields, "holding": holding or {}}]
    }


def test_one_issuer_can_raise_several_triggers_and_missing_data_raises_none():
    rules = {t["rule"] for t in evaluate(load_graph(), _one({"controversy.max_severity": 5}, {"change_pct": 80}), [])}
    assert rules == {"severe_controversy", "position_jump"}
    assert evaluate(load_graph(), _one({}), []) == []


def test_sample_triggers_are_valid_and_unmatched_without_engagements():
    triggers = evaluate(load_graph(), SAMPLE, [])
    assert triggers and all(t["engagement_id"] is None and t["severity"] in {"low", "medium", "high"} for t in triggers)


def test_a_trigger_is_matched_to_an_open_engagement_on_the_same_theme(tmp_path):
    store = EngagementStore(tmp_path)
    _, issue = store.open_issue("SYN10", "Synthetic Company 10", theme="climate_transition")
    store.open_issue("SYN09", "Synthetic Company 09", theme="board_governance")  # other theme: no match
    by_issuer = {t["issuer_id"]: t for t in evaluate(load_graph(), SAMPLE, store.list_all())}
    assert by_issuer["SYN10"]["engagement_id"] == issue.issue_id
    assert by_issuer["SYN09"]["engagement_id"] is None


def test_preview_shows_who_a_stricter_threshold_flags():
    candidate = copy.deepcopy(load_graph())
    table = next(n for n in candidate["nodes"] if n["id"] == "monitoring_rules")
    next(r for r in table["content"]["rules"] if r["_id"] == "clti_laggard")["clti"] = "< 80"
    result = preview(candidate, load_graph(), SAMPLE, [])
    assert result["by_rule_candidate"]["clti_laggard"] > result["by_rule_active"]["clti_laggard"]
    assert result["newly_flagged"] and not result["no_longer_flagged"]


def test_evaluator_handles_null_cells_bool_int_and_malformed_graphs():
    graph = copy.deepcopy(load_graph())
    table = next(n for n in graph["nodes"] if n["id"] == "monitoring_rules")
    table["content"]["rules"][0]["controversy"] = None  # JSON null cell acts as wildcard
    assert len(evaluate(graph, SAMPLE, [])) == len(evaluate(load_graph(), SAMPLE, []))
    # bool vs int must not cross-match
    bool_graph = {
        "nodes": [{
            "type": "decisionTableNode",
            "content": {
                "inputs": [{"id": "c1", "field": "issuer.flag"}],
                "outputs": [
                    {"id": "o1", "field": "rule"}, {"id": "o2", "field": "type"},
                    {"id": "o3", "field": "theme"}, {"id": "o4", "field": "severity"},
                    {"id": "o5", "field": "reason"},
                ],
                "rules": [{"c1": "true", "o1": "'r'", "o2": "'score_change'", "o3": "'climate'", "o4": "'high'", "o5": "'x'"}],
            },
        }],
    }
    assert evaluate(bool_graph, _one({"flag": 1}), []) == []
    assert len(evaluate(bool_graph, _one({"flag": True}), [])) == 1
    for bad in ({"nodes": ["bad"]}, {"nodes": [{"type": "decisionTableNode", "content": {"inputs": "bad"}}]}):
        with pytest.raises(ValueError):
            evaluate(bad, _one({}), [])
    bad_expr = copy.deepcopy(bool_graph)
    bad_expr["nodes"][0]["content"]["rules"][0]["c1"] = "== invalid("
    with pytest.raises(ValueError):
        evaluate(bad_expr, _one({"flag": True}), [])


def test_an_invalid_trigger_type_is_rejected_on_save(tmp_path):
    graph = copy.deepcopy(load_graph())
    table = next(n for n in graph["nodes"] if n["id"] == "monitoring_rules")
    table["content"]["rules"][0]["typ"] = "'gossip'"
    table["content"]["rules"][0]["clti"] = ""  # fires for every issuer
    with pytest.raises(ValueError, match="invalid trigger"):
        PolicyStore(tmp_path).save("monitoring_rules", graph, "", "Designer", SAMPLE)


def test_open_engagement_from_a_trigger_uses_the_rule_and_only_once(tmp_path):
    streams, engagements = StreamStore(tmp_path / "s"), EngagementStore(tmp_path / "e")
    body = OpenFromTriggerRequest(issuer_id="SYN10", rule="clti_laggard")
    opened = open_engagement_from_trigger(body, streams, engagements, PRINCIPAL)
    [issue] = engagements.get("SYN10").issues
    assert (issue.theme, issue.severity.value, issue.source.value) == ("climate_transition", "high", "monitoring_rule")
    assert opened["issue_id"] == issue.issue_id
    attached = next(t for t in monitoring_triggers(streams, engagements)["triggers"] if t["rule"] == "clti_laggard")
    assert attached["engagement_id"] == issue.issue_id
    with pytest.raises(HTTPException) as again:
        open_engagement_from_trigger(body, streams, engagements, PRINCIPAL)
    assert again.value.status_code == 409
    with pytest.raises(HTTPException) as unknown:
        open_engagement_from_trigger(
            OpenFromTriggerRequest(issuer_id="SYN01", rule="clti_laggard"), streams, engagements, PRINCIPAL
        )
    assert unknown.value.status_code == 404


def test_a_stored_trigger_no_longer_raised_can_still_open_an_engagement(tmp_path):
    from arp.stewardship.trigger_store import TriggerStore

    streams, engagements = StreamStore(tmp_path / "s"), EngagementStore(tmp_path / "e")
    stored = {"issuer_id": "GONE", "company": "Gone Co", "sector": "Utilities", "type": "score_change",
              "theme": "climate_transition", "severity": "medium", "rule": "clti_laggard", "reason": "CLTI 20",
              "engagement_id": None}
    TriggerStore(streams.root).record_run("2026-09", [stored])
    body = OpenFromTriggerRequest(issuer_id="GONE", rule="clti_laggard")
    opened = open_engagement_from_trigger(body, streams, engagements, PRINCIPAL)
    [issue] = engagements.get("GONE").issues
    assert (issue.theme, issue.severity.value, opened["issue_id"]) == ("climate_transition", "medium", issue.issue_id)
    with pytest.raises(HTTPException) as again:
        open_engagement_from_trigger(body, streams, engagements, PRINCIPAL)
    assert again.value.status_code == 409
    with pytest.raises(HTTPException) as unknown:
        open_engagement_from_trigger(OpenFromTriggerRequest(issuer_id="GONE", rule="other"), streams, engagements, PRINCIPAL)
    assert unknown.value.status_code == 404
