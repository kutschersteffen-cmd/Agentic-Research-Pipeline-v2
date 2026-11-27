"""User-facing search across documents, companies, and taxonomy entries.

Documents and companies are queried directly in Postgres using full-text search
(`to_tsvector` / `websearch_to_tsquery` / `ts_rank_cd`) with an escaped `ILIKE`
substring fallback so tickers, partial titles, and exact identifiers match too.
Taxonomy entries are searched via `TaxonomyStore`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from arp.api.deps import get_taxonomy_store, settings_dep
from arp.config import Settings
from arp.db import models as m
from arp.db.session import require_dsn, transaction
from arp.schemas.search import SearchHit, SearchResponse, SearchResultType
from arp.storage.taxonomy_store import TaxonomyStore

router = APIRouter(prefix="/api/search", tags=["search"])

_DEFAULT_TYPES = [SearchResultType.DOCUMENT, SearchResultType.COMPANY, SearchResultType.TAXONOMY]
_UUID_RE = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


def _like_pattern(q: str) -> str:
    escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _search_documents(session: Session, q: str, limit: int) -> list[SearchHit]:
    q = q.strip()
    if not q:
        return []
    doc_text = func.concat_ws(" ", m.Document.title, m.Document.doc_type, m.Document.universe_id)
    vec = func.to_tsvector("simple", doc_text)
    tsq = func.websearch_to_tsquery("simple", q)
    rank = func.ts_rank_cd(vec, tsq)
    pattern = _like_pattern(q)
    stmt = (
        select(m.Document, rank.label("rank"))
        .where(
            or_(
                vec.op("@@")(tsq),
                m.Document.title.ilike(pattern, escape="\\"),
                m.Document.doc_type.ilike(pattern, escape="\\"),
                m.Document.universe_id.ilike(pattern, escape="\\"),
            )
        )
        .order_by(rank.desc(), m.Document.title.asc())
        .limit(limit)
    )
    hits: list[SearchHit] = []
    for doc, score in session.execute(stmt):
        company_key = doc.universe_id or str(doc.company_id)
        hits.append(
            SearchHit(
                type=SearchResultType.DOCUMENT,
                id=doc.doc_id,
                title=doc.title or doc.doc_id,
                snippet=doc.doc_type or "",
                score=round(float(score or 0.0) + 0.1, 4),
                company_id=company_key,
                link=f"/api/documents/{company_key}" if company_key else None,
            )
        )
    return hits


def _search_companies(session: Session, q: str, limit: int) -> list[SearchHit]:
    q = q.strip()
    if not q:
        return []
    comp_text = func.concat_ws(" ", m.Company.name, m.Company.sector, m.Company.country)
    vec = func.to_tsvector("simple", comp_text)
    tsq = func.websearch_to_tsquery("simple", q)
    rank = func.ts_rank_cd(vec, tsq)
    pattern = _like_pattern(q)
    alias_subq = select(m.CompanyIdentifier.company_id).where(
        m.CompanyIdentifier.valid_to.is_(None),
        m.CompanyIdentifier.value.ilike(pattern, escape="\\"),
    )
    stmt = (
        select(m.Company, rank.label("rank"))
        .where(
            m.Company.name.op("!~*")(_UUID_RE),
            or_(
                vec.op("@@")(tsq),
                m.Company.name.ilike(pattern, escape="\\"),
                m.Company.sector.ilike(pattern, escape="\\"),
                m.Company.country.ilike(pattern, escape="\\"),
                m.Company.id.in_(alias_subq),
            ),
        )
        .order_by(rank.desc(), m.Company.name.asc())
        .limit(limit)
    )
    hits: list[SearchHit] = []
    for comp, score in session.execute(stmt):
        cid = str(comp.id)
        snippet = " · ".join(part for part in (comp.sector, comp.country) if part)
        hits.append(
            SearchHit(
                type=SearchResultType.COMPANY,
                id=cid,
                title=comp.name,
                snippet=snippet,
                score=round(float(score or 0.0) + 0.1, 4),
                company_id=cid,
                link=f"/api/documents/{cid}",
            )
        )
    return hits


def _score_text(tokens: list[str], phrase: str, fields: list[tuple[str, float]]) -> float:
    score = 0.0
    for text, weight in fields:
        if not text:
            continue
        low = text.lower()
        if phrase in low:
            score += weight * 2.0
        elif tokens and all(tok in low for tok in tokens):
            score += weight
        else:
            matched = sum(1 for tok in tokens if tok in low)
            if matched:
                score += weight * (matched / len(tokens)) * 0.5
    return round(score, 4)


def _search_taxonomies(taxonomy_store: TaxonomyStore, q: str, limit: int) -> list[SearchHit]:
    phrase = q.strip().lower()
    tokens = [t for t in phrase.split() if t]
    if not tokens:
        return []
    hits: list[SearchHit] = []
    for tax in taxonomy_store.list_all():
        matched_activity = False
        for act in tax.theme.activities:
            keywords = " ".join((*act.seed_keywords, *act.contextual_keywords))
            score = _score_text(
                tokens,
                phrase,
                [(act.name, 3.0), (keywords, 2.0), (act.in_scope_description, 1.0), (tax.name, 0.5)],
            )
            if score > 0:
                matched_activity = True
                hits.append(
                    SearchHit(
                        type=SearchResultType.TAXONOMY,
                        id=act.activity_id,
                        title=act.name,
                        snippet=act.in_scope_description[:200],
                        score=score,
                        company_id=None,
                        link=f"/api/taxonomies/{tax.taxonomy_id}",
                    )
                )
        if not matched_activity:
            score = _score_text(tokens, phrase, [(tax.name, 3.0), (tax.theme.description, 1.0)])
            if score > 0:
                hits.append(
                    SearchHit(
                        type=SearchResultType.TAXONOMY,
                        id=tax.taxonomy_id,
                        title=tax.name,
                        snippet=tax.theme.description[:200],
                        score=score,
                        company_id=None,
                        link=f"/api/taxonomies/{tax.taxonomy_id}",
                    )
                )
    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:limit]


@router.get("", response_model=SearchResponse)
def search(
    q: str = Query(..., min_length=1),
    types: list[SearchResultType] | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    settings: Settings = Depends(settings_dep),
    taxonomy_store: TaxonomyStore = Depends(get_taxonomy_store),
) -> SearchResponse:
    selected_types = types or _DEFAULT_TYPES
    hits: list[SearchHit] = []
    needs_db = SearchResultType.DOCUMENT in selected_types or SearchResultType.COMPANY in selected_types
    if needs_db:
        with transaction(require_dsn(settings)) as session:
            if SearchResultType.DOCUMENT in selected_types:
                hits.extend(_search_documents(session, q, limit))
            if SearchResultType.COMPANY in selected_types:
                hits.extend(_search_companies(session, q, limit))
    if SearchResultType.TAXONOMY in selected_types:
        hits.extend(_search_taxonomies(taxonomy_store, q, limit))
    hits.sort(key=lambda h: h.score, reverse=True)
    hits = hits[:limit]
    return SearchResponse(query=q, total=len(hits), hits=hits)
