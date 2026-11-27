from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.config import get_settings
from arp.storage.run_store import RunStore
from arp.xbrl_pipeline.store import XbrlStore
from tests.postgres_helpers import pg_dsn

pytestmark = pytest.mark.usefixtures("pg")  # the CLI/app and RunStore need Postgres

CIK = "0001234567"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("ARP_XBRL_DIR", str(tmp_path / "xbrl"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def _invoke(*args):
    return CliRunner().invoke(app, ["xbrl", *args])


def test_fetch_runs_with_patched_source(env, monkeypatch):
    class Source:
        async def resolve_cik(self, cik, ticker):
            return None

    monkeypatch.setattr("arp.cli.xbrl.build_source", lambda settings, refresh=False: Source())
    universe = env / "u.json"
    universe.write_text(json.dumps([{"company_id": "ex", "name": "Example Inc"}]))
    result = _invoke("fetch", "--universe", str(universe), "--tags", "", "--market", "sec")
    assert result.exit_code == 0, result.output
    assert "no_cik=1" in result.stdout
    run_id = result.stdout.split("Run: ")[1].split()[0]
    store = RunStore(pg_dsn(), env / "runs")
    assert [(r["company_id"], r["status"]) for r in store.read_results(run_id)] == [("ex", "no_cik")]
    assert store.load_manifest(run_id).params["tags"] is None


def test_fetch_market_esef_passes_market(env, monkeypatch):
    seen = {}

    async def stub(run_id, companies, **kw):
        seen.update(kw)

    monkeypatch.setattr("arp.cli.xbrl.execute_xbrl_run", stub)
    universe = env / "u.json"
    universe.write_text(json.dumps([{"company_id": "ex", "name": "Example Inc"}]))
    result = _invoke("fetch", "--universe", str(universe), "--market", "esef")
    assert result.exit_code == 0, result.output
    assert seen["market"] == "esef" and seen["source"] is None


def test_fetch_rejects_unknown_market(env):
    universe = env / "u.json"
    universe.write_text(json.dumps([{"company_id": "ex", "name": "Example Inc"}]))
    assert _invoke("fetch", "--universe", str(universe), "--market", "jp").exit_code == 2


def test_fetch_rejects_malformed_tag_before_running(env, tmp_path):
    uni = tmp_path / "u.csv"
    uni.write_text("company_id,name,cik\nex,Ex,1\n")
    result = _invoke("fetch", "--universe", str(uni), "--tags", "us-gaap:Revenues,Bad Tag")
    assert result.exit_code == 2 and "Bad Tag" in result.stderr and not list((env / "runs").glob("*"))


def test_fetch_default_market_is_auto(env, monkeypatch):
    seen = {}

    async def stub(run_id, companies, **kw):
        seen.update(kw)

    monkeypatch.setattr("arp.cli.xbrl.execute_xbrl_run", stub)
    universe = env / "u.json"
    universe.write_text(json.dumps([{"company_id": "ex", "name": "Example Inc"}]))
    result = _invoke("fetch", "--universe", str(universe))
    assert result.exit_code == 0, result.output
    assert seen["market"] == "auto"


def _screen_universe(env):
    universe = env / "u.json"
    universe.write_text(json.dumps([
        {"company_id": "us", "name": "US", "cik": "1234567"},
        {"company_id": "de", "name": "DE", "country": "Germany"},
        {"company_id": "jp", "name": "JP", "isin": "JP3633400001"},
        {"company_id": "nn", "name": "Name Only"},
    ]))
    return universe


def test_screen_prints_routes_and_summary(env):
    result = _invoke("screen", "--universe", str(_screen_universe(env)))
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].split()[:3] == ["us", "sec", "cik"]
    assert lines[1].split()[:3] == ["de", "esef", "country"]
    assert lines[2].split()[:3] == ["jp", "no_source", "isin_prefix"]
    assert lines[3].split()[:2] == ["nn", "unrouted"]
    assert lines[-1] == "sec=1  esef=1  no_source=1  unrouted=1"


def test_screen_does_not_write_runs(env):
    assert _invoke("screen", "--universe", str(_screen_universe(env))).exit_code == 0
    assert not (env / "runs").exists() or not list((env / "runs").iterdir())


def _seed_segments(env, note=None):
    from arp.xbrl_pipeline.segments import sec_segments, store_segments
    from tests.segment_fixture import fixture_s, ixbrl

    store = XbrlStore(env / "xbrl")
    store.set_meta(CIK, source_sha="abc", tags=None, company_id="s1", company_name="S1", fact_count=1)
    rows, found = sec_segments(ixbrl(fixture_s(note=note)), company_id="s1", accession="a1")
    store_segments(store, CIK, rows, found)


def test_ac_18_segments_prints_rows(env):
    _seed_segments(env)
    result = _invoke("segments", "s1")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "year  segment  metric  value  unit  concept  sum_check" and len(lines) == 4
    assert all(s in lines[1] for s in ("2025", "Alpha", "revenue", "300", "USD", "true"))


def test_ac_19_segments_unknown_company(env):
    result = _invoke("segments", "zz")
    assert result.exit_code == 1 and "No XBRL data for zz" in result.output


def test_ac_32_segment_note_prints(env):
    _seed_segments(env, note="Alpha sells widgets. Beta sells gadgets.")
    result = _invoke("segment-note", "s1")
    assert result.exit_code == 0 and result.stdout.strip() == "Alpha sells widgets. Beta sells gadgets."


def test_ac_33_segment_note_missing(env):
    _seed_segments(env)
    result = _invoke("segment-note", "s1")
    assert result.exit_code == 1 and "No segment note for s1" in result.output


def _seed_p(env):
    from arp.xbrl_pipeline.segments import sec_segments, store_segments
    from tests.segment_fixture import fixture_p, ixbrl

    store = XbrlStore(env / "xbrl")
    store.set_meta(CIK, source_sha="abc", tags=None, company_id="s1", company_name="S1", fact_count=1)
    store_segments(store, CIK, *sec_segments(ixbrl(fixture_p()), company_id="s1", accession="a1"))


def test_ac_14_axis_product(env):
    _seed_p(env)
    result = _invoke("segments", "s1", "--axis", "product")
    lines = result.stdout.splitlines()
    assert result.exit_code == 0 and lines[0] == "year  segment  level  metric  value  unit  concept  sum_check"
    assert len(lines) == 5 and "Widgets  company  revenue  600" in lines[1]


def test_ac_15_axis_geography(env):
    _seed_p(env)
    result = _invoke("segments", "s1", "--axis", "geography")
    lines = result.stdout.splitlines()
    assert result.exit_code == 0 and lines[0] == "year  segment  metric  value  unit  concept  sum_check"
    assert len(lines) == 4


def test_ac_16_default_axis_segment(env):
    _seed_p(env)
    result = _invoke("segments", "s1")
    lines = result.stdout.splitlines()
    assert result.exit_code == 0 and lines[0] == "year  segment  metric  value  unit  concept  sum_check"
    assert len(lines) == 4 and all(s in lines[1] for s in ("2025", "Alpha", "revenue", "300", "USD", "true"))


def test_ac_17_axis_invalid(env):
    _seed_p(env)
    assert _invoke("segments", "s1", "--axis", "region").exit_code == 2
