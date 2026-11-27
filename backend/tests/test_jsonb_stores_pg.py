"""Postgres `app_documents` persistence tests for the 6 JSONB-backed stores."""

from __future__ import annotations

import pytest

from arp.schemas.common import CompanyRef
from arp.schemas.emerging_themes import (
    CandidateStatus,
    EmergingThemeCandidate,
    LineageEvent,
    LineageTransition,
    TopicCluster,
)
from arp.schemas.issuer import IdentifierMap
from arp.schemas.taxonomy import DerivationMethod, TaxonomyStatus
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.stewardship.notes import NoteLog
from arp.stewardship.trigger_store import TriggerStore
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.issuer_sectors import IssuerSectorStore, apply_master
from arp.storage.taxonomy_store import TaxonomyStore
from arp.storage.topic_store import TopicStateStore


def _theme(name: str = "Electrification") -> ThemeDefinition:
    return ThemeDefinition(
        name=name,
        description="",
        activities=[ActivityDefinition(name="EV", in_scope_description="x", out_of_scope_description="y")],
    )


def test_stores_require_path_or_dsn():
    for cls in (IssuerSectorStore, IdentifierMapStore, TopicStateStore, TaxonomyStore, NoteLog, TriggerStore):
        with pytest.raises(ValueError, match="dsn"):
            cls()


def test_identifier_map_file_replace(tmp_path):
    store = IdentifierMapStore(tmp_path / "idmap.jsonl")
    store.add(IdentifierMap(issuer_key="i1", scheme="LEI", value="5493001KJTIIGC8Y1R12"))
    store.replace([IdentifierMap(issuer_key="i2", scheme="ISIN", value="US0378331005")])
    assert [r.issuer_key for r in store.rows()] == ["i2"]


def test_issuer_sector_store_pg_round_trip(pg):
    store = IssuerSectorStore(dsn=pg)
    assert store.get("c1") == {}
    store.replace({"c1": {"nace_code": "35.11", "nace_rev": "2"}})
    assert store.get("c1") == {"nace_code": "35.11", "nace_rev": "2"}
    updated = apply_master(CompanyRef(company_id="c1", name="Acme"), store)
    assert updated.nace_code == "35.11"


def test_identifier_map_store_pg_round_trip(pg):
    store = IdentifierMapStore(dsn=pg)
    assert store.rows() == []
    store.add(IdentifierMap(issuer_key="i1", scheme="ISIN", value="US0378331005"))
    store.add(IdentifierMap(issuer_key="i2", scheme="ISIN", value="DE0007164600"))
    assert store.resolve("ISIN", "us0378331005") == ["i1"]
    assert len(store.rows()) == 2

    store.replace([IdentifierMap(issuer_key="i3", scheme="ISIN", value="FR0000120271")])
    assert [r.issuer_key for r in store.rows()] == ["i3"]


def test_topic_state_store_pg_round_trip(pg):
    store = TopicStateStore(dsn=pg)
    assert store.list_periods() == []
    assert store.load_period("2026-W01") is None

    clusters = [TopicCluster(cluster_id="c1", period="2026-W01", representative_label="grid", company_ids=["acme"])]
    store.save_period("2026-W01", clusters)
    store.save_period("2026-W02", [])
    assert store.list_periods() == ["2026-W01", "2026-W02"]
    assert store.latest_period_before("2026-W02") == "2026-W01"
    loaded = store.load_period("2026-W01")
    assert loaded is not None and loaded[0].cluster_id == "c1"

    events = [LineageEvent(cluster_id="c1", period="2026-W01", transition=LineageTransition.BIRTH)]
    store.save_lineage_events("2026-W01", events)
    assert len(store.load_lineage_events("2026-W01")) == 1
    assert store.load_lineage_events("2026-W99") == []

    cand = EmergingThemeCandidate(
        theme_name="Grid storage",
        description="",
        first_detected_date="2026-01-01",
        signal_velocity=1.5,
        economic_rationale="",
        cluster_id="c1",
        run_id="r1",
        status=CandidateStatus.CANDIDATE,
    )
    store.append_candidate(cand)
    assert [c.theme_id for c in store.list_candidates()] == [cand.theme_id]


def test_taxonomy_store_pg_round_trip_and_immutability(pg):
    store = TaxonomyStore(dsn=pg)
    assert store.list_all() == []
    assert store.get("tax_missing") is None

    v1 = store.create("Electrification", _theme(), DerivationMethod.LLM_DRAFT, "initial")
    assert store.get(v1.taxonomy_id) == v1

    v2 = store.new_version(v1.taxonomy_id, _theme("Electrification v2"), DerivationMethod.MANUAL, "edit")
    assert v2.version == 2
    assert store.get(v1.taxonomy_id) == v2
    assert store.get(v1.taxonomy_id, version=1) == v1
    assert [t.version for t in store.list_versions(v1.taxonomy_id)] == [1, 2]
    assert [t.taxonomy_id for t in store.list_all()] == [v1.taxonomy_id]

    with pytest.raises(FileExistsError):
        store._write_new_version(v1)

    ratified = store.ratify(v1.taxonomy_id, 2, ratified_by="alice")
    assert ratified.status == TaxonomyStatus.RATIFIED
    assert store.get(v1.taxonomy_id, 2).ratified_by == "alice"


def test_note_log_pg_round_trip(pg):
    log = NoteLog(dsn=pg)
    assert log.notes("c1") == []
    assert log.summary() == {}

    n1 = log.add("c1", "First remark", by="alice", scope="house")
    n2 = log.add("c1", "Second remark", by="bob", scope="house")
    assert [n["note_id"] for n in log.notes("c1")] == [n2["note_id"], n1["note_id"]]
    assert log.summary()["c1"]["count"] == 2
    assert log.summary()["c1"]["latest"]["text"] == "Second remark"


def test_trigger_store_pg_round_trip(pg):
    store = TriggerStore(dsn=pg)
    assert store.list_triggers() == []

    raised = store.record_run(
        "2026-11",
        [
            {
                "issuer_id": "c1",
                "company": "Acme",
                "rule": "high_controversy",
                "type": "controversy",
                "theme": "governance",
                "severity": "high",
                "reason": "Severe controversy",
            }
        ],
    )
    assert len(raised) == 1
    tid = raised[0].trigger_id
    assert store.list_triggers(status="open")[0].trigger_id == tid

    updated = store.transition(tid, "acknowledged", decided_by="alice", reason="Reviewing")
    assert updated.status == "acknowledged"
    assert store.companies()[tid] == "Acme"
