
import pytest

from arp.config import Settings
from arp.reporting.adapters import load_run_datasets
from arp.schemas.common import RunManifest
from arp.schemas.reporting import RunRef
from arp.storage.run_store import RunStore

pytestmark = pytest.mark.usefixtures("pg")  # the CLI/app and RunStore need Postgres


def _settings(tmp_path) -> Settings:
    return Settings(runs_dir=tmp_path / "runs", reports_dir=tmp_path / "reports")


def test_run_adapter_flattens_results_jsonl(tmp_path, pg):
    s = _settings(tmp_path)
    runs = RunStore(pg, s.runs_dir)
    runs.save_manifest(RunManifest(run_id="run_1", run_type="theme"))
    for r in [
        {"company": "Acme", "revenue_share": 0.4, "evidence": [{"q": "x"}], "meta": {"a": 1}},
        {"company": "Beta", "revenue_share": 0.1, "evidence": []},
    ]:
        runs.append_result("run_1", r)
    [ds] = load_run_datasets([RunRef(kind="run", ref_id="run_1")], s)
    assert ds.name == "theme"
    assert ds.column_names() == ["company", "revenue_share"]  # nested fields dropped
    assert ds.rows == [{"company": "Acme", "revenue_share": 0.4}, {"company": "Beta", "revenue_share": 0.1}]


def test_unknown_ref_raises(tmp_path):
    s = _settings(tmp_path)
    with pytest.raises(ValueError, match="unknown run run_x"):
        load_run_datasets([RunRef(kind="run", ref_id="run_x")], s)
