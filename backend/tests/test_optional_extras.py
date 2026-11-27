"""Tests that optional backend extras (parsing, reporting, graph, embeddings) are truly opt-in."""

from __future__ import annotations

import builtins
import importlib
import importlib.util
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest

from arp import company_graph
from arp.config import Settings
from arp.reporting import browser, chart_data, vega
from arp.schemas.reporting import ChartSpec, ChartType

BLOCKED_TOP_LEVEL = ("docling", "neo4j", "playwright", "pptx", "vl_convert", "fastembed", "reportlab")
BACKEND_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = BACKEND_ROOT / "pyproject.toml"


def _blocked_import(blocked: set[str]):
    real_import = builtins.__import__

    def _guarded(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name.split(".", 1)[0] in blocked:
            raise ImportError(f"blocked optional dependency: {name}")
        return real_import(name, globals, locals, fromlist, level)

    return _guarded


def test_pyproject_moves_optional_stacks_out_of_core_dependencies() -> None:
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    core_deps = data["project"]["dependencies"]
    extras = data["project"]["optional-dependencies"]

    moved_prefixes = (
        "docling",
        "python-pptx",
        "reportlab",
        "vl-convert-python",
        "playwright",
        "neo4j",
        "fastembed",
    )
    for dep in core_deps:
        pkg = dep.split("[", 1)[0].split(">", 1)[0].split("<", 1)[0].split("=", 1)[0].strip().lower()
        assert not pkg.startswith(moved_prefixes), f"optional dependency left in core dependencies: {dep}"

    for extra_name in ("parsing", "reporting", "graph", "embeddings", "all"):
        assert extra_name in extras and extras[extra_name], f"missing optional extra: {extra_name}"
    assert extras["all"] == ["arp[parsing,reporting,graph,embeddings]"]


def test_core_entrypoints_import_without_optional_extras() -> None:
    script = f"""
import sys

BLOCKED = frozenset({BLOCKED_TOP_LEVEL!r})

class Blocker:
    def find_spec(self, fullname, path, target=None):
        if fullname.split(".", 1)[0] in BLOCKED:
            raise ImportError(f"blocked optional dependency: {{fullname}}")
        return None

sys.meta_path.insert(0, Blocker())

import arp.api.main as api_main
import arp.cli as cli_pkg
import arp.worker.main as worker_main

assert len(api_main.app.routes) > 0
assert cli_pkg.app is not None
assert callable(worker_main.run_worker)
loaded = sorted(k for k in sys.modules if k.split(".", 1)[0] in BLOCKED)
assert not loaded, f"unexpected optional modules loaded: {{loaded}}"
"""
    env = {**os.environ, "PYTHONPATH": str(BACKEND_ROOT)}
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"


def test_company_graph_requires_graph_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(company_graph, "GraphDatabase", None)
    settings = Settings(neo4j_uri="bolt://localhost:7687", neo4j_user="neo4j", neo4j_password="pw")
    with pytest.raises(company_graph.CompanyGraphError, match=r"arp\[graph\]"):
        company_graph.open_graph(settings)


@pytest.mark.asyncio
async def test_reporting_browser_requires_reporting_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "__import__", _blocked_import({"playwright"}))
    with pytest.raises(browser.BrowserUnavailable, match=r"arp\[reporting\]"):
        async with browser._page("<html></html>"):
            pass


def test_reporting_vega_requires_reporting_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(builtins, "__import__", _blocked_import({"vl_convert"}))
    with pytest.raises(ImportError, match=r"arp\[reporting\]"):
        vega._vlc()


def test_chart_data_is_native_independent_of_pptx() -> None:
    bar = ChartSpec(chart_type=ChartType.BAR, dataset_id="ds1", title="Bar", category_column="x", value_columns=["y"])
    scatter = ChartSpec(chart_type=ChartType.SCATTER, dataset_id="ds1", title="Scatter", x_column="x", value_columns=["y"])
    assert chart_data.is_native(bar) is True
    assert chart_data.is_native(scatter) is False


@pytest.mark.parametrize(
    ("module_name", "blocked_pkg", "expected_attr"),
    [
        ("arp.company_graph", "neo4j", "GraphDatabase"),
        ("arp.ingestion.pdf_page", "docling", "pypdfium2_lock"),
        ("arp.reporting.chart_data", "pptx", "_XL_CHART_TYPE"),
        ("arp.reporting.template_frame", "pptx", "PP_PLACEHOLDER"),
    ],
)
def test_optional_module_fallbacks_import_cleanly(module_name: str, blocked_pkg: str, expected_attr: str) -> None:
    # Execute in an isolated throwaway module so live sys.modules class identities stay intact.
    mod = importlib.import_module(module_name)
    assert mod.__file__ is not None
    probe_name = f"_optional_probe_{module_name.replace('.', '_')}"
    spec = importlib.util.spec_from_file_location(probe_name, mod.__file__)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    sys.modules[probe_name] = probe
    try:
        with patch.object(builtins, "__import__", _blocked_import({blocked_pkg})):
            spec.loader.exec_module(probe)
    finally:
        sys.modules.pop(probe_name, None)
    assert hasattr(probe, expected_attr)
