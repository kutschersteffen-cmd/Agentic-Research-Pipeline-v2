"""Spec server-paths-upload-limits, slice 3: every upload read is capped (AC-37 to AC-39, AC-42) and a guard
test keeps it that way (AC-43)."""
from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from arp.api import deps
from arp.api.main import app
from arp.api.routers import holdings as holdings_router
from arp.config import get_settings

LIMIT = 2_000_000
TOO_BIG = 413, {"detail": "File is larger than the 2 MB upload limit."}
ROUTERS = Path(__file__).resolve().parents[1] / "arp" / "api" / "routers"
ALLOWED: set[tuple[str, str]] = set()


@pytest.fixture
def settings(tmp_path, monkeypatch):
    s = get_settings().model_copy(update={
        "max_upload_bytes": LIMIT, "runs_dir": tmp_path / "runs",
        "documents_dir": tmp_path / "documents",
    })
    (s.runs_dir / "_universes").mkdir(parents=True)
    monkeypatch.setitem(app.dependency_overrides, deps.settings_dep, lambda: s)
    monkeypatch.setitem(app.dependency_overrides, holdings_router.get_portfolio_store, lambda: None)
    monkeypatch.setitem(app.dependency_overrides, holdings_router.get_identifier_map, lambda: None)
    return s


@pytest.fixture
def client(settings):
    return TestClient(app)


def _answer(r):
    return r.status_code, r.json()


# Upload reads 1 to 3: route, file name, other form fields.
SAVING_UPLOADS = [
    ("/api/universe/upload", "big.csv", {}),
    ("/api/universe/raw-upload", "big.csv", {}),
    ("/api/universe/from-holdings", "big.csv", {}),
]


def test_raw_upload_at_and_over_the_limit(client, settings):  # AC-37
    assert client.post("/api/universe/raw-upload", files={"file": ("ok.csv", b"a" * LIMIT)}).status_code == 200
    assert _answer(client.post("/api/universe/raw-upload", files={"file": ("big.csv", b"a" * (LIMIT + 1))})) == TOO_BIG


@pytest.mark.parametrize(("route", "name", "data"), SAVING_UPLOADS)
def test_upload_over_the_limit_saves_nothing(client, settings, route, name, data):  # AC-38
    folders = [settings.runs_dir / "_universes"]
    before = [sorted(d.rglob("*")) for d in folders]
    assert _answer(client.post(route, data=data, files={"file": (name, b"a" * (LIMIT + 1))})) == TOO_BIG
    assert [sorted(d.rglob("*")) for d in folders] == before


@pytest.mark.parametrize(("route", "files"), [
    ("/api/reports/templates", {"file": ("big.pptx", b"a" * (LIMIT + 1))}),
    ("/api/reports/templates", [("file", ("t.pptx", b"a")), ("fonts", ("Big-400.ttf", b"a" * (LIMIT + 1)))]),
    ("/api/reports/datasets/upload", {"file": ("big.csv", b"a" * (LIMIT + 1))}),
])
def test_report_uploads_over_the_limit(client, route, files):  # upload reads 6 to 8
    assert _answer(client.post(route, files=files)) == TOO_BIG


@pytest.mark.parametrize(("route", "data"), [
    ("/api/documents/upload", {"company_id": "acme", "doc_type": "10-K"}),
    ("/api/holdings/upload", {"holder_id": "h", "kind": "portfolio", "as_of": "2026-10-31"}),
])
def test_uploads_that_already_had_the_limit(client, route, data):  # AC-42
    assert _answer(client.post(route, data=data, files={"file": ("big.csv", b"a" * (LIMIT + 1))})) == TOO_BIG


def unbounded_reads(routers: Path) -> list[str]:
    """`file:line` of each `.read()` call with no argument under `routers`, minus the allow-list."""
    found = []
    for path in sorted(routers.rglob("*.py")):
        source = path.read_text()
        lines = source.splitlines()
        for node in ast.walk(ast.parse(source)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "read"
                    and not node.args and not node.keywords
                    and (path.name, lines[node.lineno - 1].strip()) not in ALLOWED):
                found.append(f"{path.relative_to(routers)}:{node.lineno}")
    return found


def test_upload_guard():  # AC-43, real folder
    found = unbounded_reads(ROUTERS)
    assert found == [], f"upload read without a size cap (use deps.read_capped): {found}"


def test_upload_guard_catches_a_new_unbounded_read(tmp_path):  # AC-43, a copy with one bad line
    copy = shutil.copytree(ROUTERS, tmp_path / "routers")
    target = copy / "universe.py"
    target.write_text(target.read_text() + "\n\nasync def _bad(file):\n    data = await file.read()\n")
    line = len(target.read_text().splitlines())
    assert unbounded_reads(copy) == [f"universe.py:{line}"]
