"""security-errors-ssrf PR 2: the converted raise sites in routers (AC-49..AC-54)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arp.api.auth import Principal, current_user
from arp.api.deps import get_run_store
from arp.api.main import app
from arp.schemas.common import RunManifest
from arp.storage.run_store import RunStore

pytestmark = pytest.mark.usefixtures("pg")


@pytest.fixture
def themes(tmp_path, pg):
    rs = RunStore(pg, tmp_path / "runs")
    rs.save_manifest(RunManifest(run_id="r1", run_type="extraction"))
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[current_user] = lambda: Principal(user_id="u", name="U", role="approver")
    yield TestClient(app)
    app.dependency_overrides.clear()


def _review(c, key, decision):
    return c.post("/api/themes/runs/r1/review", json={"item_key": key, "decision": decision})


def test_ac50_unknown_decision(themes):
    r = _review(themes, "k", "maybe")
    assert (r.status_code, r.json()["detail"]) == (400, "decision must be one of ['approve', 'edit', 'escalate', 'reject']")


def test_ac51_workbench_key(themes):
    r = _review(themes, "held:x", "approve")
    assert (r.status_code, r.json()["detail"]) == (400, "decide this item through the review workbench")


def test_ac52_workbench_run_type(themes):
    r = _review(themes, "k", "approve")
    assert (r.status_code, r.json()["detail"]) == (400, "decide extraction items through the review workbench")
