"""Unit tests for PR 5c-2d runtime wiring, saved-universe file loader, and factory re-exports."""

from __future__ import annotations

import pytest

from arp.api import deps
from arp.errors import ClientInputError
from arp.orchestration import hooks
from arp.retrieval import registry_factory
from arp.runtime import container
from arp.storage import factories as storage_factories
from arp.universe import NOT_SAVED_UNIVERSE, UNREADABLE_UNIVERSE, load_saved_universe_file


def test_deps_reexports_preserve_factory_identity():
    assert deps.get_run_store is storage_factories.get_run_store
    assert deps.get_taxonomy_store is storage_factories.get_taxonomy_store
    assert deps.get_portfolio_store is storage_factories.get_portfolio_store
    assert deps.get_reporting_store is storage_factories.get_reporting_store
    assert deps.get_document_content_store is registry_factory.get_document_content_store
    assert deps.build_registry is registry_factory.build_registry
    assert deps.get_registry is registry_factory.get_registry


def test_extraction_runner_hook_requires_registration_and_wires(monkeypatch):
    import asyncio

    from arp.extraction import pipeline as extraction_pipeline

    monkeypatch.setattr(hooks, "_extraction_runner", None)
    with pytest.raises(RuntimeError, match="not registered"):
        hooks.get_extraction_runner()
    container.wire()
    create_fn, execute_fn = hooks.get_extraction_runner()
    assert callable(create_fn) and callable(execute_fn)

    monkeypatch.setattr(extraction_pipeline, "create_extraction_run", lambda *a, **k: "run-123")

    async def fake_execute(*a, **k):
        return "done-123"

    monkeypatch.setattr(extraction_pipeline, "execute_extraction_run", fake_execute)
    assert create_fn() == "run-123"
    assert asyncio.run(execute_fn()) == "done-123"


def test_load_saved_universe_file_checks_folder_and_readability(tmp_path):
    runs_dir = tmp_path / "runs"
    universes = runs_dir / "_universes"
    universes.mkdir(parents=True)

    valid = universes / "ok.csv"
    valid.write_text("company_id,name\nc1,Acme\n", encoding="utf-8")
    refs = load_saved_universe_file(str(valid), runs_dir)
    assert [r.company_id for r in refs] == ["c1"]

    outside = tmp_path / "outside.csv"
    outside.write_text("company_id,name\nc1,Acme\n", encoding="utf-8")
    with pytest.raises(ClientInputError, match=NOT_SAVED_UNIVERSE):
        load_saved_universe_file(str(outside), runs_dir)

    broken = universes / "bad.json"
    broken.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ClientInputError, match="not valid JSON"):
        load_saved_universe_file(str(broken), runs_dir)

    unreadable = universes / "bad.csv"
    unreadable.write_bytes(b"\xff\xfe\x00")
    with pytest.raises(ClientInputError, match=UNREADABLE_UNIVERSE):
        load_saved_universe_file(str(unreadable), runs_dir)
