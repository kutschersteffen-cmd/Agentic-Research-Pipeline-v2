"""Tests for the generic Postgres JSONB `AppDocument` model and `JsonDocumentRepo`."""

from __future__ import annotations

import pytest

from arp.db.json_document_repo import JsonDocumentRepo
from arp.db.models import AppDocument


def test_app_document_table_metadata():
    table = AppDocument.__table__
    assert table.name == "app_documents"
    assert [c.name for c in table.primary_key.columns] == ["namespace", "doc_key"]
    assert {"namespace", "doc_key", "payload", "version", "created_at", "updated_at"} <= set(table.columns.keys())


def test_repo_rejects_blank_namespace_and_key():
    with pytest.raises(ValueError, match="namespace"):
        JsonDocumentRepo("postgresql+psycopg://unused/db", "   ")

    repo = JsonDocumentRepo("postgresql+psycopg://unused/db", "notes")
    with pytest.raises(ValueError, match="doc_key"):
        repo.get("")
    with pytest.raises(ValueError, match="doc_key"):
        repo.put("  ", {"a": 1})


def test_json_document_repo_crud_and_versioning(pg):
    repo = JsonDocumentRepo(pg, "schedules")

    assert repo.get("discovery") is None
    assert repo.get_with_version("discovery") is None
    assert repo.exists("discovery") is False
    assert repo.list_keys() == []
    assert repo.list_items() == []

    v1 = repo.put("discovery", {"enabled": True, "interval_hours": 24})
    assert v1 == 1
    assert repo.exists("discovery") is True
    assert repo.get("discovery") == {"enabled": True, "interval_hours": 24}
    assert repo.get_with_version("discovery") == ({"enabled": True, "interval_hours": 24}, 1)

    v2 = repo.put("discovery", {"enabled": False, "interval_hours": 12})
    assert v2 == 2
    assert repo.get_with_version("discovery") == ({"enabled": False, "interval_hours": 12}, 2)

    repo.put("calibration", {"enabled": True})
    assert repo.list_keys() == ["calibration", "discovery"]
    assert repo.list_items() == [
        ("calibration", {"enabled": True}),
        ("discovery", {"enabled": False, "interval_hours": 12}),
    ]

    assert repo.delete("discovery") is True
    assert repo.delete("discovery") is False
    assert repo.exists("discovery") is False
    assert repo.list_keys() == ["calibration"]


def test_json_document_repo_isolates_namespaces(pg):
    notes = JsonDocumentRepo(pg, "notes")
    schemas = JsonDocumentRepo(pg, "schemas")

    notes.put("shared-key", {"kind": "note"})
    schemas.put("shared-key", {"kind": "schema"})

    assert notes.get("shared-key") == {"kind": "note"}
    assert schemas.get("shared-key") == {"kind": "schema"}
    assert notes.delete("shared-key") is True
    assert schemas.get("shared-key") == {"kind": "schema"}
