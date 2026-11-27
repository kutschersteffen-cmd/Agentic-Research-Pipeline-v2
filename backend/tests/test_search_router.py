from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

from arp.api.routers import search as search_router
from arp.api.routers.search import _like_pattern, _score_text, _search_taxonomies, search
from arp.config import Settings
from arp.db import models as m
from arp.db.session import transaction
from arp.errors import NotConfigured
from arp.schemas.search import SearchHit, SearchResultType
from arp.schemas.taxonomy import DerivationMethod
from arp.schemas.thematic import ActivityDefinition, ThemeDefinition
from arp.storage.taxonomy_store import TaxonomyStore


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
        portfolios_dir=tmp_path / "portfolios",
        document_store_dir=tmp_path / "docstore",
        taxonomies_dir=tmp_path / "taxonomies",
        **overrides,
    )


def test_like_pattern_escapes_wildcards():
    assert _like_pattern("100%_a\\b") == "%100\\%\\_a\\\\b%"


def test_whitespace_only_query_returns_empty_without_executing_sql():
    class _ForbiddenSession:
        def execute(self, _stmt):
            raise AssertionError("whitespace-only query must not execute SQL")

    assert search_router._search_documents(_ForbiddenSession(), "   ", 10) == []
    assert search_router._search_companies(_ForbiddenSession(), "\t\n ", 10) == []


def test_score_text_ranks_phrase_above_partial_tokens():
    phrase_score = _score_text(["grid", "storage"], "grid storage", [("Grid Storage Systems", 3.0)])
    partial_score = _score_text(["grid", "storage"], "grid storage", [("Smart Grid", 3.0)])
    assert phrase_score > partial_score > 0.0
    assert _score_text(["solar"], "solar", [("Coal Mining", 3.0)]) == 0.0


def test_search_taxonomies_matches_activities_and_theme_fallback(tmp_path):
    store = TaxonomyStore(tmp_path / "taxonomies")
    grid = store.create(
        name="Grid Modernisation",
        theme=ThemeDefinition(
            name="Grid Modernisation",
            description="Transmission and utility-scale storage infrastructure.",
            activities=[
                ActivityDefinition(
                    name="High-Voltage Transformers",
                    in_scope_description="Manufacturing grid transformers and substations.",
                    out_of_scope_description="Consumer electronics.",
                    seed_keywords=["substation", "hvdc"],
                )
            ],
        ),
        derivation_method=DerivationMethod.MANUAL,
    )
    water = store.create(
        name="Water Scarcity",
        theme=ThemeDefinition(
            name="Water Scarcity",
            description="Desalination and municipal leak detection.",
            activities=[],
        ),
        derivation_method=DerivationMethod.MANUAL,
    )

    act_hits = _search_taxonomies(store, "hvdc", limit=10)
    assert len(act_hits) == 1
    assert act_hits[0].type is SearchResultType.TAXONOMY
    assert act_hits[0].title == "High-Voltage Transformers"
    assert act_hits[0].link == f"/api/taxonomies/{grid.taxonomy_id}"
    assert act_hits[0].company_id is None

    theme_hits = _search_taxonomies(store, "desalination", limit=10)
    assert len(theme_hits) == 1
    assert theme_hits[0].id == water.taxonomy_id
    assert theme_hits[0].link == f"/api/taxonomies/{water.taxonomy_id}"


def test_search_taxonomy_only_does_not_require_postgres(tmp_path):
    store = TaxonomyStore(tmp_path / "taxonomies")
    store.create(
        name="Electrification",
        theme=ThemeDefinition(name="Electrification", description="Electric vehicles and charging.", activities=[]),
        derivation_method=DerivationMethod.MANUAL,
    )
    res = search(
        q="charging",
        types=[SearchResultType.TAXONOMY],
        limit=10,
        settings=_settings(tmp_path, postgres_dsn=None),
        taxonomy_store=store,
    )
    assert res.query == "charging"
    assert res.total == 1
    assert res.hits[0].title == "Electrification"


def test_search_documents_without_postgres_raises_not_configured(tmp_path):
    store = TaxonomyStore(tmp_path / "taxonomies")
    with pytest.raises(NotConfigured):
        search(
            q="annual report",
            types=[SearchResultType.DOCUMENT],
            limit=10,
            settings=_settings(tmp_path, postgres_dsn=None),
            taxonomy_store=store,
        )


def test_search_merges_sorts_and_truncates_across_types(tmp_path, monkeypatch):
    @contextmanager
    def _fake_tx(_dsn):
        yield object()

    monkeypatch.setattr(search_router, "transaction", _fake_tx)
    monkeypatch.setattr(
        search_router,
        "_search_documents",
        lambda _s, _q, _lim: [
            SearchHit(type=SearchResultType.DOCUMENT, id="d_low", title="Low", score=0.5),
            SearchHit(type=SearchResultType.DOCUMENT, id="d_high", title="High", score=9.0),
        ],
    )
    monkeypatch.setattr(
        search_router,
        "_search_companies",
        lambda _s, _q, _lim: [
            SearchHit(type=SearchResultType.COMPANY, id="c_mid", title="Mid", score=4.0),
        ],
    )
    store = TaxonomyStore(tmp_path / "taxonomies")
    res = search(
        q="x",
        types=[SearchResultType.DOCUMENT, SearchResultType.COMPANY],
        limit=2,
        settings=_settings(tmp_path, postgres_dsn="postgresql+psycopg://u:p@localhost/db"),
        taxonomy_store=store,
    )
    assert res.total == 2
    assert [h.id for h in res.hits] == ["d_high", "c_mid"]


def test_search_postgres_fts_documents_and_companies(tmp_path, pg):
    comp_id = uuid.uuid4()
    uuid_only_id = uuid.uuid4()
    with transaction(pg) as session:
        session.add(m.Company(id=comp_id, name="Nordic Wind Power ASA", country="NO", sector="Renewables"))
        session.add(m.Company(id=uuid_only_id, name=str(uuid_only_id), country="NO", sector="Renewables"))
        session.flush()
        session.add(m.CompanyIdentifier(company_id=comp_id, scheme=m.IdScheme.TICKER.value, value="NWP"))
        session.add(
            m.Document(
                doc_id="doc_nwp_2025",
                company_id=comp_id,
                universe_id="nordic_wind",
                doc_type="annual_report_10k",
                title="Nordic Wind Annual Sustainability Report 2025",
                content_key="sha_nwp_2025",
            )
        )

    store = TaxonomyStore(tmp_path / "taxonomies")
    settings = _settings(tmp_path, postgres_dsn=pg)

    doc_res = search(q="Sustainability Report", types=[SearchResultType.DOCUMENT], limit=10, settings=settings, taxonomy_store=store)
    assert any(h.id == "doc_nwp_2025" and h.company_id == "nordic_wind" for h in doc_res.hits)

    comp_res = search(q="Nordic Wind", types=[SearchResultType.COMPANY], limit=10, settings=settings, taxonomy_store=store)
    assert [h.id for h in comp_res.hits] == [str(comp_id)]
    assert comp_res.hits[0].snippet == "Renewables · NO"

    ticker_res = search(q="NWP", types=[SearchResultType.COMPANY], limit=10, settings=settings, taxonomy_store=store)
    assert [h.id for h in ticker_res.hits] == [str(comp_id)]
