"""Pure observation input types shared by `arp.db.observations` and `arp.db.to_observations`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any
from uuid import UUID

from arp.db.models import CitationRole, Route, SourceKind, ValueState

RULE_NOT_APPLICABLE = "not_applicable_by_rule"  # observation method of a row the applicability rules skipped


@dataclass(kw_only=True)
class CitationIn:
    doc_id: str
    role: CitationRole = CitationRole.PRIMARY
    content_key: str | None = None
    page: int | None = None
    sheet: str | None = None
    location: str | None = None
    quote: str | None = None
    span_text: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    table_ref: dict | None = None
    passage_id: str | None = None
    grounded: bool = False
    match_method: str | None = None
    match_score: float | None = None


@dataclass(kw_only=True)
class ObservationIn:
    company_id: UUID
    field_id: str
    field_version: int
    source_kind: SourceKind
    period_end: date | None
    basis: str = ""
    value: Any
    value_state: ValueState
    unit: str | None = None
    canonical_value: float | None = None
    canonical_unit: str | None = None
    scale_applied: float | None = None
    fx_rate: float | None = None
    confidence: float | None = None
    checks: list | dict | None = None
    route: Route | None = None
    method: str | None = None
    period_start: date | None = None
    run_id: str | None = None
    source_id: int | None = None
    load_id: int | None = None
    citations: list[CitationIn] = field(default_factory=list)
    conflicting_sources: bool = False
    trial: bool = False
    held: bool = False
