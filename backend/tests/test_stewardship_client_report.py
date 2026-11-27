from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pptx = pytest.importorskip("pptx")

from arp.stewardship.client_report import build_pptx, client_report  # noqa: E402
from arp.stewardship.config_store import StreamStore  # noqa: E402
from arp.storage.postgres_engagement_store import PostgresEngagementStore  # noqa: E402

pytestmark = pytest.mark.usefixtures("sample_house_universe", "pg")


def _texts(path) -> list[str]:
    return [sh.text_frame.text for s in pptx.Presentation(path).slides for sh in s.shapes if sh.has_text_frame]


def test_stewardship_client_report_uses_house_renderer_without_llm(tmp_path, monkeypatch):
    import arp.llm.factory

    monkeypatch.setattr(arp.llm.factory, "build_llm_client", lambda *a, **k: pytest.fail("no LLM for stewardship decks"))
    streams = StreamStore(tmp_path)
    out = build_pptx(client_report(streams.root, "House programme", []), tmp_path / "r.pptx")
    assert out == tmp_path / "r.pptx" and out.exists() and (tmp_path / "r.pdf").exists()
    assert "Data sources" in _texts(out)


def test_pptx_endpoint_skips_the_pdf_and_the_browser(tmp_path, pg, monkeypatch):
    from fastapi import BackgroundTasks

    import arp.stewardship.client_report as cr
    from arp.api.routers.stewardship import get_house_report_pptx

    monkeypatch.setattr(cr, "write_pdf", lambda *a: pytest.fail("the endpoint deletes its temp dir; no PDF"))
    streams = StreamStore(tmp_path)
    tasks = BackgroundTasks()
    resp = get_house_report_pptx(tasks, streams, PostgresEngagementStore(pg))
    out = Path(resp.path)
    assert out.suffix == ".pptx" and out.exists() and not list(out.parent.glob("*.pdf"))
    shutil.rmtree(out.parent)


def test_report_summarises_universe_and_open_engagements(tmp_path, pg):
    streams = StreamStore(tmp_path)
    eng = PostgresEngagementStore(pg)
    eng.open_issue("SYN10", "Synthetic Company 10", theme="climate_transition")
    report = client_report(streams.root, "House programme", eng.list_all())
    assert sum(s["companies"] for s in report["sectors"]) == 12
    assert len(report["engagements"]) == 1
    assert report["engagements"][0]["company"] == "Synthetic Company 10"
    titles = _texts(build_pptx(report, tmp_path / "r.pptx"))
    for heading in ("Stewardship at a glance", "Covered universe by sector", "Open engagements", "Data sources"):
        assert heading in titles
