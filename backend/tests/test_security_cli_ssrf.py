"""security-errors-ssrf PR 1: check-postgres password (AC-1..5), CGNAT (AC-6..8, 30, 31)."""
from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import arp.cli.db as db_cli
from arp.net_safety import UnsafeURLError, assert_safe_fetch_target

runner = CliRunner()
DSN = "postgresql+psycopg://arp:s3cr3t-pw@db.example:5432/arp"


# ---- check-postgres -------------------------------------------------------------------------
def _report(current: bool) -> dict:
    return {"vector_extension": True, "applied_steps": [], "missing_tables": [], "missing_columns": [],
            "pending_steps": [], "drift": [], "unmatched_company_rows": {}, "current": current}


def _check(monkeypatch, dsn: str, current: bool):
    monkeypatch.setattr(db_cli, "get_settings", lambda: SimpleNamespace(postgres_dsn=dsn))
    monkeypatch.setattr("arp.storage.postgres_schema.schema_report", lambda _dsn: _report(current))
    return runner.invoke(db_cli.db_app, ["check-postgres"])


def test_ac1_ac2_ac4_current_hides_password(monkeypatch):
    res = _check(monkeypatch, DSN, True)
    assert res.exit_code == 0
    assert res.output.splitlines()[0] == "Postgres schema at postgresql+psycopg://arp:***@db.example:5432/arp:"
    assert "s3cr3t-pw" not in res.output


def test_ac3_ac4_not_current(monkeypatch):
    res = _check(monkeypatch, DSN, False)
    assert res.exit_code == 1
    assert "NOT current -- run `arp db init-postgres` to apply what's missing." in res.output
    assert "s3cr3t-pw" not in res.output


def test_ac5_no_password_unchanged(monkeypatch):
    res = _check(monkeypatch, "postgresql+psycopg://arp@db.example/arp", True)
    assert res.exit_code == 0
    assert res.output.splitlines()[0] == "Postgres schema at postgresql+psycopg://arp@db.example/arp:"


def test_check_postgres_unmatched_company_rows_hint(monkeypatch):
    report = {**_report(True), "unmatched_company_rows": {"published_facts": 2}}
    monkeypatch.setattr(db_cli, "get_settings", lambda: SimpleNamespace(postgres_dsn=DSN))
    monkeypatch.setattr("arp.storage.postgres_schema.schema_report", lambda _dsn: report)
    res = runner.invoke(db_cli.db_app, ["check-postgres"])
    assert res.exit_code == 0
    assert "published_facts=2 (matched by `arp db init-postgres` once the company exists)" in res.output
    assert "s3cr3t-pw" not in res.output


def test_require_cutover_schema_gate(monkeypatch):
    from arp.db.session import require_cutover

    settings = SimpleNamespace(postgres_dsn=DSN, skip_cutover_check=False)
    monkeypatch.setattr("arp.storage.postgres_schema.schema_gaps", lambda _dsn: ([], [], []))
    require_cutover(settings)  # current schema passes

    monkeypatch.setattr("arp.storage.postgres_schema.schema_gaps", lambda _dsn: (["runs"], [], ["step1"]))
    with pytest.raises(RuntimeError, match="arp db upgrade.*arp db init-postgres"):
        require_cutover(settings)

    require_cutover(SimpleNamespace(postgres_dsn=DSN, skip_cutover_check=True))


# ---- net_safety -----------------------------------------------------------------------------
def _literal_resolver(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda host, *a, **k: [(2, 1, 6, "", (host, 0))])


def _host(h: str) -> str:
    return h.strip("[]")


@pytest.mark.parametrize("host", ["100.64.0.0", "100.64.0.1", "100.100.100.200", "100.127.255.255",
                                  "[::ffff:100.64.0.1]", "[::ffff:100.100.100.200]"])
def test_ac6_cgnat_blocked(monkeypatch, host):
    _literal_resolver(monkeypatch)
    with pytest.raises(UnsafeURLError) as e:
        assert_safe_fetch_target(f"http://{host}/")
    assert str(e.value) == f"{_host(host)} resolves to a disallowed address ({_host(host)})"


@pytest.mark.parametrize("host", ["100.63.255.255", "100.128.0.0", "[::ffff:100.63.255.255]", "[::ffff:100.128.0.0]"])
def test_ac7_cgnat_neighbours_allowed(monkeypatch, host):
    _literal_resolver(monkeypatch)
    assert_safe_fetch_target(f"http://{host}/")


def test_ac8_mixed_resolution_blocked(monkeypatch):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 0)), (2, 1, 6, "", ("100.64.0.1", 0))])
    with pytest.raises(UnsafeURLError) as e:
        assert_safe_fetch_target("http://mixed.test/")
    assert str(e.value) == "mixed.test resolves to a disallowed address (100.64.0.1)"


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "192.0.0.8",
                                  "0.0.0.0", "224.0.0.1", "[::1]", "[fe80::1]", "[::ffff:127.0.0.1]", "[64:ff9b::a00:1]"])
def test_ac30_still_blocked(monkeypatch, host):
    _literal_resolver(monkeypatch)
    with pytest.raises(UnsafeURLError) as e:
        assert_safe_fetch_target(f"http://{host}/")
    assert str(e.value) == f"{_host(host)} resolves to a disallowed address ({_host(host)})"


@pytest.mark.parametrize("host", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "192.0.0.9", "[2606:4700::1111]"])
def test_ac31_still_allowed(monkeypatch, host):
    _literal_resolver(monkeypatch)
    assert_safe_fetch_target(f"http://{host}/")
