import copy
import json
import os
import re

import pytest
from typer.testing import CliRunner

from arp.cli import app
from arp.research.indirect_exposure.factory import sectors
from arp.research.indirect_exposure.migrate import (
    UnknownIcioCode,
    convert_document,
    convert_parts,
    convert_theme,
    icio_sectors,
)
from arp.research.indirect_exposure.migrate import icio_sectors as S
from arp.schemas.thematic import OLD_FORMAT_MESSAGE
from arp.schemas.value_chain import LinkRule
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.taxonomy_store import TaxonomyStore


def test_sectors_count_and_first():
    assert len(sectors()) == 163
    assert sectors()[0] == "Cultivation of paddy rice"
    assert not any(re.search(r" \(\d+\)$", s) for s in sectors())


def test_icio_sectors_b07():
    s = icio_sectors("B07")
    assert len(s) == 8 and "Mining of uranium and thorium ores" in s
    assert s == sorted(s)


def test_icio_sectors_split_code():
    s = icio_sectors("D_GEN_REN")
    assert len(s) == 7 and all(n.startswith("Production of electricity by") for n in s)


def test_unknown_code():
    with pytest.raises(UnknownIcioCode) as e:
        icio_sectors("ZZZ")
    assert e.value.code == "ZZZ"


def test_convert_theme_key_order():
    theme = {"activities": [{"activity_id": "a1", "name": "n", "core_isic_codes": ["B07"], "source_citation": None}]}
    assert convert_theme(theme) is True
    assert list(theme["activities"][0]) == ["activity_id", "name", "core_sectors", "source_citation"]
    assert theme["activities"][0]["core_sectors"] == icio_sectors("B07")
    assert convert_theme(theme) is False


def test_convert_unmapped():
    theme = {"activities": [], "standards_mapping": {"unmapped_isic_codes": ["B07"]}}
    assert convert_theme(theme) is True
    assert theme["standards_mapping"] == {"unmapped_sectors": icio_sectors("B07")}


def test_convert_parts():
    parts = [{"icio_code": "B07", "share": 0.4}, {"icio_code": "D_GEN_REN", "share": 0.6}]
    assert convert_parts("split", parts) == [
        {"sectors": icio_sectors("B07"), "share": 0.4},
        {"sectors": icio_sectors("D_GEN_REN"), "share": 0.6},
    ]
    assert convert_parts("nodes", [{"region": "DE", "sector": "Copper production", "share": 1}]) is None
    assert convert_parts("split", [{"sectors": ["x"], "share": 1}]) is None


def test_convert_document_taxonomy_and_bare_theme():
    act = {"activity_id": "a1", "core_isic_codes": ["B07"]}
    tax = {"theme": {"activities": [dict(act)]}}
    assert convert_document(tax) is True
    assert tax["theme"]["activities"][0]["core_sectors"] == icio_sectors("B07")
    bare = {"activities": [dict(act)]}
    assert convert_document(bare) is True
    assert "core_isic_codes" not in bare["activities"][0]


def test_convert_parts_llm_like_split():
    assert convert_parts("llm", [{"icio_code": "B07", "share": 1}]) == [{"sectors": icio_sectors("B07"), "share": 1}]


def test_convert_theme_unknown_code():
    with pytest.raises(UnknownIcioCode):
        convert_theme({"activities": [{"core_isic_codes": ["ZZZ"]}]})


def test_convert_document_bare_run_theme():
    theme = {"activities": [{"activity_id": "a1", "name": "n", "core_isic_codes": ["B07"]}]}
    assert convert_document(theme) is True
    assert theme["activities"][0]["core_sectors"] == icio_sectors("B07")


runner = CliRunner()
DSN = os.environ.get("ARP_TEST_POSTGRES_DSN")
C1 = {"kind": "split", "parts": [{"icio_code": "B07", "share": 0.4}, {"icio_code": "D_GEN_REN", "share": 0.6}], "set_by": "a", "set_at": "t"}
C2 = {"kind": "nodes", "parts": [{"region": "DE", "sector": "Copper production", "share": 1}], "set_by": "a", "set_at": "t"}


def _doc(version: int, **extra) -> dict:
    return {
        "taxonomy_id": "t1", "name": "T", "version": version, "derivation_method": "manual", "source_notes": "",
        "status": "draft", "ratified_by": None, "ratified_at": None, "based_on_version": None, "created_at": "t",
        "theme": {"name": "x", "activities": [
            {"id": "a1", "name": "A1", "core_isic_codes": ["B07"], "standards_mapping": {"unmapped_isic_codes": ["B07"]}},
            {"id": "a2", "name": "A2", "core_isic_codes": []},
        ]},
        **extra,
    }


def _valid_taxonomy_doc(taxonomy_id: str, version: int, **extra) -> dict:
    return {
        "taxonomy_id": taxonomy_id,
        "name": "T",
        "version": version,
        "derivation_method": "manual",
        "source_notes": "",
        "status": "draft",
        "ratified_by": None,
        "ratified_at": None,
        "based_on_version": None,
        "created_at": "2026-01-01T00:00:00Z",
        "theme": {
            "name": "x",
            "description": "d",
            "activities": [
                {
                    "activity_id": "a1",
                    "name": "A1",
                    "in_scope_description": "in",
                    "out_of_scope_description": "out",
                    "seed_keywords": ["kw"],
                    "core_isic_codes": ["B07"],
                    "standards_mapping": {
                        "activity_id": "a1",
                        "activity_name": "A1",
                        "unmapped_isic_codes": ["B07"],
                    },
                },
                {
                    "activity_id": "a2",
                    "name": "A2",
                    "in_scope_description": "in",
                    "out_of_scope_description": "out",
                    "seed_keywords": ["kw2"],
                    "core_isic_codes": [],
                },
            ],
        },
        **extra,
    }


def _write(path, doc) -> None:
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")


def _snapshot(tdir, store) -> dict:
    files = {str(p): p.read_bytes() for p in sorted(tdir.rglob("*")) if p.is_file()}
    return {"files": files, "rules": {k: v.model_dump() for k, v in store.list_link_rules().items()}}


def _install(tmp_path, monkeypatch, store):
    tdir = tmp_path / "taxonomies"
    (tdir / "t1").mkdir(parents=True)
    _write(tdir / "t1" / "v1.json", _doc(1, status="ratified", ratified_by="bob", ratified_at="2026-01-01T00:00:00Z"))
    _write(tdir / "t1" / "v2.json", _doc(2, based_on_version=1))
    (tdir / "t1" / "latest.json").write_text('{"version": 2}')
    (tdir / "t1" / "notes.txt").write_text("core_isic_codes stray")
    monkeypatch.setattr("arp.cli._shared._taxonomy_store", lambda: TaxonomyStore(tdir))
    monkeypatch.setattr("arp.cli._shared._link_rule_stores", lambda: [store])
    store.save_link_rule("company:c1", LinkRule(**C1))
    store.save_link_rule("company:c2", LinkRule(**C2))
    return tdir


@pytest.fixture
def m(tmp_path, monkeypatch):
    store = PortfolioStore(tmp_path / "pf")
    return _install(tmp_path, monkeypatch, store), store


def _run(*args):
    return runner.invoke(app, ["io", "migrate-exiobase", *args])


def _load(tdir, n):
    return json.loads((tdir / "t1" / f"v{n}.json").read_text())


def test_taxonomies_converted(m):  # AC-1, 2, 3, 55, 56, 57
    tdir, store = m
    before = _load(tdir, 1)
    assert _run().exit_code == 0
    for n in (1, 2):
        a1, a2 = _load(tdir, n)["theme"]["activities"]
        assert a1["core_sectors"] == S("B07") and a2["core_sectors"] == []
        assert "core_isic_codes" not in a1 and "core_isic_codes" not in a2
    v1 = _load(tdir, 1)
    assert all(v1[k] == before[k] for k in ("status", "ratified_by", "ratified_at"))
    assert v1["theme"]["activities"][0]["standards_mapping"] == {"unmapped_sectors": S("B07")}
    v2 = _load(tdir, 2)
    assert (v2["version"], v2["based_on_version"]) == (2, 1)
    assert not (tdir / "t1" / "v3.json").exists()


def test_links_converted_and_stdout(m):  # AC-4, 5, 6
    tdir, store = m
    c2 = store.get_link_rule("company:c2").model_dump()
    res = _run()
    assert res.exit_code == 0
    assert res.stdout == "taxonomy t1 v1\ntaxonomy t1 v2\nlink company:c1\n3 changed\n"
    assert store.get_link_rule("company:c1").parts == [{"sectors": S("B07"), "share": 0.4}, {"sectors": S("D_GEN_REN"), "share": 0.6}]
    assert store.get_link_rule("company:c2").model_dump() == c2


def test_idempotent(m):  # AC-7, 59
    tdir, store = m
    _run()
    snap = _snapshot(tdir, store)
    res = _run()
    assert (res.exit_code, res.stdout) == (0, "0 changed\n")
    assert _snapshot(tdir, store) == snap


def test_dry_run(m):  # AC-8
    tdir, store = m
    snap = _snapshot(tdir, store)
    res = _run("--dry-run")
    assert (res.exit_code, res.stdout) == (0, "taxonomy t1 v1\ntaxonomy t1 v2\nlink company:c1\n3 changed\n")
    assert _snapshot(tdir, store) == snap


def test_unknown_code_aborts_without_writing(m):  # AC-9, 10
    tdir, store = m
    bad = copy.deepcopy(C1)
    bad["parts"][1]["icio_code"] = "ZZZ"
    store.save_link_rule("company:c1", LinkRule(**bad))
    snap = _snapshot(tdir, store)
    res = _run()
    assert res.exit_code == 1 and res.stderr == "unknown ICIO code 'ZZZ' in link company:c1\n"
    assert _snapshot(tdir, store) == snap


def test_unknown_code_in_taxonomy_names_version(m):
    tdir, store = m
    d = _doc(2, based_on_version=1)
    d["theme"]["activities"][0]["core_isic_codes"] = ["ZZZ"]
    _write(tdir / "t1" / "v2.json", d)
    res = _run()
    assert res.exit_code == 1 and res.stderr == "unknown ICIO code 'ZZZ' in taxonomy t1 v2\n"
    assert "core_isic_codes" in (tdir / "t1" / "v1.json").read_text()


def test_file_mode(m, tmp_path):  # AC-11, 60, 61, 12, 13
    tdir, store = m
    f = tmp_path / "theme.json"
    _write(f, {"name": "x", "activities": [{"id": "a1", "name": "A", "core_isic_codes": ["B07"]}]})
    snap = _snapshot(tdir, store)
    res = _run("--file", str(f))
    assert (res.exit_code, res.stdout) == (0, f"file {f}\n1 changed\n")
    act = json.loads(f.read_text())["activities"][0]
    assert act["core_sectors"] == S("B07") and "core_isic_codes" not in act
    assert _snapshot(tdir, store) == snap
    # AC-13: a copy of unmigrated v1 ends byte-identical to what the full run writes
    copy_v1 = tmp_path / "v1.json"
    copy_v1.write_bytes((tdir / "t1" / "v1.json").read_bytes())
    assert _run("--file", str(copy_v1)).exit_code == 0
    _run()
    assert copy_v1.read_bytes() == (tdir / "t1" / "v1.json").read_bytes()


def test_latest_and_stray_files_untouched(m):  # Review Focus 3
    tdir, _ = m
    _run()
    assert (tdir / "t1" / "latest.json").read_text() == '{"version": 2}'
    assert (tdir / "t1" / "notes.txt").read_text() == "core_isic_codes stray"


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")
def test_postgres_store(tmp_path, monkeypatch):  # AC-58
    from arp.db.postgres_schema import ensure_schema
    from arp.storage.postgres_portfolio_store import PostgresPortfolioStore
    from tests.postgres_helpers import reset_postgres_tables

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    try:
        store = PostgresPortfolioStore(DSN, PortfolioStore(tmp_path / "pg-files"))
        _install(tmp_path, monkeypatch, store)
        assert _run().exit_code == 0
        assert store.get_link_rule("company:c1").parts == [{"sectors": S("B07"), "share": 0.4}, {"sectors": S("D_GEN_REN"), "share": 0.6}]
    finally:
        reset_postgres_tables(DSN)


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")
def test_postgres_taxonomy_store_migration(tmp_path, monkeypatch):
    from arp.db.json_document_repo import JsonDocumentRepo
    from arp.db.postgres_schema import ensure_schema
    from tests.postgres_helpers import reset_postgres_tables

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    try:
        versions_repo = JsonDocumentRepo(DSN, "taxonomy_versions")
        latest_repo = JsonDocumentRepo(DSN, "taxonomy_latest")
        versions_repo.put(
            "t1:v1",
            _valid_taxonomy_doc("t1", 1, status="ratified", ratified_by="bob", ratified_at="2026-01-01T00:00:00Z"),
        )
        versions_repo.put("t1:v2", _valid_taxonomy_doc("t1", 2, based_on_version=1))
        latest_repo.put("t1", {"latest_version": 2})

        pg_store = TaxonomyStore(tmp_path / "empty_tdir", dsn=DSN)
        pf_store = PortfolioStore(tmp_path / "empty_pf")
        monkeypatch.setattr("arp.cli._shared._taxonomy_store", lambda: pg_store)
        monkeypatch.setattr("arp.cli._shared._link_rule_stores", lambda: [pf_store])

        # Dry run reports changes and leaves Postgres untouched (including AppDocument.version)
        dry = _run("--dry-run")
        assert (dry.exit_code, dry.stdout) == (0, "taxonomy t1 v1\ntaxonomy t1 v2\n2 changed\n")
        payload_before, ver_before = versions_repo.get_with_version("t1:v1")
        assert ver_before == 1 and "core_isic_codes" in payload_before["theme"]["activities"][0]

        # Real run migrates both rows in place and preserves metadata & latest pointer
        res = _run()
        assert (res.exit_code, res.stdout) == (0, "taxonomy t1 v1\ntaxonomy t1 v2\n2 changed\n")
        _, ver_after = versions_repo.get_with_version("t1:v1")
        assert ver_after == 2
        assert latest_repo.get("t1") == {"latest_version": 2}

        loaded_v1 = TaxonomyStore(dsn=DSN).get("t1", 1)
        assert loaded_v1 is not None
        assert (loaded_v1.status.value, loaded_v1.ratified_by, loaded_v1.ratified_at) == (
            "ratified",
            "bob",
            "2026-01-01T00:00:00Z",
        )
        assert loaded_v1.theme.activities[0].core_sectors == S("B07")
        assert loaded_v1.theme.activities[0].standards_mapping.unmapped_sectors == S("B07")
        all_versions = TaxonomyStore(dsn=DSN).list_versions("t1")
        assert [t.version for t in all_versions] == [1, 2]
        assert all_versions[1].based_on_version == 1

        # Second run is idempotent and does not bump AppDocument.version
        again = _run()
        assert (again.exit_code, again.stdout) == (0, "0 changed\n")
        _, ver_idempotent = versions_repo.get_with_version("t1:v1")
        assert ver_idempotent == ver_after
    finally:
        reset_postgres_tables(DSN)


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")
def test_postgres_taxonomy_unknown_code_aborts_before_any_write(tmp_path, monkeypatch):
    from arp.db.json_document_repo import JsonDocumentRepo
    from arp.db.postgres_schema import ensure_schema
    from tests.postgres_helpers import reset_postgres_tables

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    try:
        tdir = tmp_path / "taxonomies"
        (tdir / "t_file").mkdir(parents=True)
        _write(tdir / "t_file" / "v1.json", _doc(1, taxonomy_id="t_file"))
        file_before = (tdir / "t_file" / "v1.json").read_bytes()

        versions_repo = JsonDocumentRepo(DSN, "taxonomy_versions")
        versions_repo.put("t_pg:v1", _valid_taxonomy_doc("t_pg", 1))
        bad_v2 = _valid_taxonomy_doc("t_pg", 2, based_on_version=1)
        bad_v2["theme"]["activities"][0]["core_isic_codes"] = ["ZZZ"]
        versions_repo.put("t_pg:v2", bad_v2)

        pf_store = PortfolioStore(tmp_path / "pf")
        pf_store.save_link_rule("company:c1", LinkRule(**C1))

        monkeypatch.setattr("arp.cli._shared._taxonomy_store", lambda: TaxonomyStore(tdir, dsn=DSN))
        monkeypatch.setattr("arp.cli._shared._link_rule_stores", lambda: [pf_store])

        res = _run()
        assert res.exit_code == 1
        assert res.stderr == "unknown ICIO code 'ZZZ' in taxonomy t_pg v2\n"
        assert (tdir / "t_file" / "v1.json").read_bytes() == file_before
        pg_v1, pg_ver = versions_repo.get_with_version("t_pg:v1")
        assert pg_ver == 1 and "core_isic_codes" in pg_v1["theme"]["activities"][0]
        assert pf_store.get_link_rule("company:c1").parts == C1["parts"]
    finally:
        reset_postgres_tables(DSN)


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")
def test_dual_mode_file_and_postgres_taxonomies_both_migrated(tmp_path, monkeypatch):
    from arp.db.json_document_repo import JsonDocumentRepo
    from arp.db.postgres_schema import ensure_schema
    from tests.postgres_helpers import reset_postgres_tables

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    try:
        tdir = tmp_path / "taxonomies"
        (tdir / "t_file").mkdir(parents=True)
        _write(tdir / "t_file" / "v1.json", _doc(1, taxonomy_id="t_file"))

        versions_repo = JsonDocumentRepo(DSN, "taxonomy_versions")
        versions_repo.put("t_pg:v1", _valid_taxonomy_doc("t_pg", 1))
        versions_repo.put("custom_key", _valid_taxonomy_doc("custom_key", 1))

        pf_store = PortfolioStore(tmp_path / "pf")
        monkeypatch.setattr("arp.cli._shared._taxonomy_store", lambda: TaxonomyStore(tdir, dsn=DSN))
        monkeypatch.setattr("arp.cli._shared._link_rule_stores", lambda: [pf_store])

        res = _run()
        assert res.exit_code == 0
        lines = res.stdout.splitlines()
        assert "taxonomy t_file v1" in lines
        assert "taxonomy t_pg v1" in lines
        assert "taxonomy custom_key" in lines
        assert lines[-1] == "3 changed"
        assert json.loads((tdir / "t_file" / "v1.json").read_text())["theme"]["activities"][0]["core_sectors"] == S("B07")
        assert versions_repo.get("t_pg:v1")["theme"]["activities"][0]["core_sectors"] == S("B07")
    finally:
        reset_postgres_tables(DSN)


def test_plan_all_ignores_non_dict_repo_entries():
    from arp.research.indirect_exposure import migrate

    class _StubRepo:
        def list_items(self):
            return [("bad:v1", ["not-a-dict"])]

    assert migrate.plan_all(None, [], versions_repo=_StubRepo()) == []


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")
def test_postgres_taxonomy_store_list_versions_rejects_unmigrated():
    from arp.db.json_document_repo import JsonDocumentRepo
    from arp.db.postgres_schema import ensure_schema
    from tests.postgres_helpers import reset_postgres_tables

    ensure_schema(DSN)
    reset_postgres_tables(DSN)
    try:
        versions_repo = JsonDocumentRepo(DSN, "taxonomy_versions")
        latest_repo = JsonDocumentRepo(DSN, "taxonomy_latest")
        versions_repo.put("t1:v1", _valid_taxonomy_doc("t1", 1))
        latest_repo.put("t1", {"latest_version": 1})

        store = TaxonomyStore(dsn=DSN)
        with pytest.raises(ValueError, match=re.escape(OLD_FORMAT_MESSAGE)):
            store.get("t1")
        with pytest.raises(ValueError, match=re.escape(OLD_FORMAT_MESSAGE)):
            store.list_all()
        with pytest.raises(ValueError, match=re.escape(OLD_FORMAT_MESSAGE)):
            store.list_versions("t1")
    finally:
        reset_postgres_tables(DSN)


@pytest.mark.parametrize("code", ["B09", "C21", "C301", "H53", "J58T60"])
def test_icio_codes_without_sectors_map_to_nothing(code):  # owner decision 2026-11-05
    assert icio_sectors(code) == []


def test_activity_with_unmatched_icio_code_gets_no_sectors():
    theme = {"activities": [{"name": "n", "core_isic_codes": ["C21"]}]}
    assert convert_theme(theme) is True
    assert theme["activities"][0]["core_sectors"] == []


def test_digit_codes_convert_through_nace():  # owner decision 2026-11-05: old hand-supplied ISIC Rev.4 codes
    assert icio_sectors("07") == [
        "Mining of aluminium ores and concentrates", "Mining of copper ores and concentrates", "Mining of iron ores",
        "Mining of lead, zinc and tin ores and concentrates", "Mining of nickel ores and concentrates",
        "Mining of other non-ferrous metal ores and concentrates", "Mining of precious metal ores and concentrates",
        "Mining of uranium and thorium ores",
    ]
    assert "Aluminium production" in icio_sectors("2420")
    with pytest.raises(UnknownIcioCode):
        icio_sectors("00")


def test_activity_with_both_keys_keeps_the_union():
    theme = {"activities": [{"name": "n", "core_sectors": ["Mining of iron ores", "Aluminium production"], "core_isic_codes": ["B07"]}]}
    assert convert_theme(theme) is True
    act = theme["activities"][0]
    assert act["core_sectors"] == sorted({"Aluminium production", *S("B07")}) and "core_isic_codes" not in act


def test_file_mode_non_object_json(m, tmp_path):
    f = tmp_path / "list.json"
    f.write_text("[1, 2]")
    res = _run("--file", str(f))
    assert (res.exit_code, res.stdout) == (0, "0 changed\n")
    assert f.read_text() == "[1, 2]"


def _env_file_store(tmp_path, monkeypatch):
    """Config through env only (no patched internals): a taxonomy and link rule c1 in ARP_PORTFOLIOS_DIR's file store."""
    from arp.config import get_settings

    tdir = tmp_path / "taxonomies"
    (tdir / "t1").mkdir(parents=True)
    _write(tdir / "t1" / "v1.json", _doc(1))
    store = PortfolioStore(tmp_path / "pf")
    store.save_link_rule("company:c1", LinkRule(**C1))
    monkeypatch.setenv("ARP_TAXONOMIES_DIR", str(tdir))
    monkeypatch.setenv("ARP_PORTFOLIOS_DIR", str(tmp_path / "pf"))
    get_settings.cache_clear()
    return store


def _assert_env_run(store):
    result = _run()
    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["taxonomy t1 v1", "link company:c1", "2 changed"]
    assert store.get_link_rule("company:c1").parts == [{"sectors": S("B07"), "share": 0.4}, {"sectors": S("D_GEN_REN"), "share": 0.6}]


def test_env_file_store_without_postgres(tmp_path, monkeypatch):
    monkeypatch.delenv("ARP_POSTGRES_DSN", raising=False)
    store = _env_file_store(tmp_path, monkeypatch)
    try:
        _assert_env_run(store)
    finally:
        from arp.config import get_settings

        get_settings.cache_clear()


def test_env_file_store_with_whitespace_postgres_dsn(tmp_path, monkeypatch):
    monkeypatch.setenv("ARP_POSTGRES_DSN", "   ")
    store = _env_file_store(tmp_path, monkeypatch)
    try:
        assert TaxonomyStore(tmp_path / "tax_ws", dsn="   ")._versions_repo is None
        _assert_env_run(store)
    finally:
        from arp.config import get_settings

        get_settings.cache_clear()


@pytest.mark.skipif(not DSN, reason="ARP_TEST_POSTGRES_DSN not set")
def test_env_file_store_with_postgres_configured(pg, tmp_path, monkeypatch):  # spec: "Postgres or file"
    _assert_env_run(_env_file_store(tmp_path, monkeypatch))
