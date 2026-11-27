from __future__ import annotations

import io
import json

import openpyxl
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from arp.api.auth import Principal, current_user
from arp.api.deps import get_portfolio_store, get_run_store, settings_dep
from arp.api.main import app
from arp.config import Settings
from arp.holdings.intake import ingest
from arp.holdings.validate import validate
from arp.schemas.portfolio import HolderConfig
from arp.storage.identifier_map import IdentifierMapStore
from arp.storage.portfolio_store import PortfolioStore
from arp.storage.run_store import RunStore
from tests.conftest import PRINCIPAL

ISIN, ISIN2 = "US0378331005", "DE0007164600"
LEI, BAD_LEI = "5493001KJTIIGC8Y1R12", "5493001KJTIIGC8Y1R13"
ANALYST = Principal(user_id="u_ana", name="Ana", role="analyst")
URL = "/api/holdings"
HEADER = "ISIN,LEI,Name,Weight (%),Market value,Currency\n"


@pytest.fixture
def env(tmp_path, pg):
    store, rs, idmap = PortfolioStore(tmp_path / "pf"), RunStore(pg, tmp_path / "runs"), IdentifierMapStore(tmp_path / "id.jsonl")
    store.save_holder(HolderConfig(holder_id="P1", kind="portfolio", source="api"))
    yield store, rs, idmap
    for dep in (get_portfolio_store, get_run_store, settings_dep, current_user):
        app.dependency_overrides.pop(dep, None)


def api(env, tmp_path, who=PRINCIPAL, **settings):
    store, rs, _ = env
    app.dependency_overrides[get_portfolio_store] = lambda: store
    app.dependency_overrides[get_run_store] = lambda: rs
    app.dependency_overrides[settings_dep] = lambda: Settings(identifier_map_path=tmp_path / "id.jsonl", **settings)
    app.dependency_overrides[current_user] = lambda: who
    return TestClient(app)


def upload(c, body: bytes, name="positions.csv", **form):
    data = {"holder_id": "P1", "kind": "portfolio", "as_of": "2026-09-30", **form}
    return c.post(f"{URL}/upload", data=data, files={"file": (name, body)})


def test_upload_bad_lei_422_names_row(env, tmp_path):
    body = (HEADER + f"{ISIN},{LEI},Apple,60,600,EUR\n{ISIN2},{BAD_LEI},SAP,40,400,EUR\n").encode()
    r = upload(api(env, tmp_path), body)
    assert r.status_code == 422
    err = r.json()["detail"]["errors"][0]
    assert (err["row"], err["column"]) == (3, "lei") and err["message"]


def test_upload_writes_and_ignores_formulas(env, tmp_path):
    body = (HEADER + f"{ISIN},,=HYPERLINK(\"x\"),60,600,EUR\n{ISIN2},,SAP,40,400,EUR\n").encode()
    r = upload(api(env, tmp_path), body, override_reason="desk correction")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "written" and r.json()["revision"] == 1


def test_upload_over_size_limit_413(env, tmp_path):
    r = upload(api(env, tmp_path, max_upload_bytes=10), (HEADER * 2).encode())
    assert r.status_code == 413


def test_upload_unreadable_file_422(env, tmp_path):
    c = api(env, tmp_path)
    for r in (upload(c, b"not a zip", name="positions.xlsx"), upload(c, HEADER.encode(), provider="nope"),
              upload(c, HEADER.encode(), as_of="20260930")):
        assert r.status_code == 422
        assert r.json()["detail"]["errors"] == []


def test_upload_over_api_month_without_reason_409(env, tmp_path):
    store, _, idmap = env
    raw = [
        {"_row": 2, "isin": ISIN, "lei": LEI, "weight": 60.0, "market_value": 600.0, "currency": "EUR", "fx_rate_to_eur": 1.0},
        {"_row": 3, "isin": ISIN2, "weight": 40.0, "market_value": 400.0, "currency": "EUR", "fx_rate_to_eur": 1.0},
    ]
    ingest(store, validate(raw, kind="portfolio", as_of="2026-09-30"), kind="portfolio", holder_id="P1", as_of="2026-09-30",
           source="api", source_ref="api:seed", principal=None, override_reason=None, idmap=idmap)
    body = (HEADER + f"{ISIN},,Apple,50,600,EUR\n{ISIN2},,SAP,50,400,EUR\n").encode()
    assert upload(api(env, tmp_path), body).status_code == 409


def test_template_download_xlsx_opens(env, tmp_path):
    r = api(env, tmp_path).get(f"{URL}/template", params={"kind": "portfolio", "format": "xlsx"})
    assert r.status_code == 200
    assert r.headers["content-disposition"] == 'attachment; filename="holdings-template-portfolio.xlsx"'
    header = next(openpyxl.load_workbook(io.BytesIO(r.content)).active.iter_rows(values_only=True))
    assert header[0] == "ISIN" and "FX rate to EUR" in header


def test_put_holder_needs_approver_and_is_audited(env, tmp_path):
    body = {"name": "Fund", "source": "file"}
    assert api(env, tmp_path, who=ANALYST).put(f"{URL}/holders/portfolio/P1", json=body).status_code == 403
    r = api(env, tmp_path).put(f"{URL}/holders/portfolio/P1", json=body)
    assert r.status_code == 200 and r.json()["source"] == "file" and "user_id" not in r.text
    audit = env[0]._read_jsonl(env[0].holdings_audit_path())[-1]
    assert (audit["user_id"], audit["old_source"], audit["new_source"]) == (PRINCIPAL.user_id, "api", "file")
    assert api(env, tmp_path).put(f"{URL}/holders/portfolio/P1", json={"source": "file"}).json()["name"] == "Fund"


def test_holders_response_has_no_user_id(env, tmp_path):
    c = api(env, tmp_path)
    body = (HEADER + f"{ISIN},,Apple,60,600,EUR\n{ISIN2},,SAP,40,400,EUR\n").encode()
    assert upload(c, body, override_reason="r").status_code == 200
    r = c.get(f"{URL}/holders")
    assert r.json()["holders"][0]["holder_id"] == "P1"
    assert "user_id" not in r.text and PRINCIPAL.user_id not in r.text


def test_cli_import_xlsx(env, tmp_path, monkeypatch):
    from arp.cli import holdings as cli

    users = tmp_path / "users.json"
    users.write_text(json.dumps({"users": [{"user_id": "u_apr", "name": "A", "role": "approver", "token": "ta"}]}))
    monkeypatch.setattr(cli, "get_settings", lambda: Settings(
        users_file=users, portfolios_dir=tmp_path / "pf", runs_dir=tmp_path / "runs",
        identifier_map_path=tmp_path / "id.jsonl"))
    monkeypatch.setenv("ARP_CLI_TOKEN", "ta")
    wb = openpyxl.Workbook()
    for line in (HEADER.strip().split(","), [ISIN, LEI, "Apple", 60, 600, "EUR"], [ISIN2, None, "SAP", 40, 400, "EUR"]):
        wb.active.append(line)
    path = tmp_path / "positions.xlsx"
    wb.save(path)
    env[0].save_holder(HolderConfig(holder_id="P1", kind="portfolio", source="file"))
    res = CliRunner().invoke(cli.holdings_app, ["import", "--file", str(path), "--holder", "P1", "--as-of", "2026-09-30"])
    assert res.exit_code == 0, res.output
    assert env[0].list_revisions("portfolio", "P1", "2026-09-30") == [1]
