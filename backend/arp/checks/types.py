"""Shared check context and threshold-key primitives (breaks `checks` internal import cycle)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from dataclasses import field as dc_field
from typing import Any

from arp.schemas.common import CompanyRef, SourceDocument
from arp.schemas.datapoints import CheckResult, DataPointSchema, ExtractedField, FieldDefinition


@dataclass
class CheckContext:
    company: CompanyRef
    issuer_key: str
    schema: DataPointSchema
    documents_by_id: dict[str, SourceDocument]
    record_fields: list[ExtractedField]
    history: Any = None
    references: dict[str, list[Any]] = dc_field(default_factory=dict)  # item key -> other-source values


Check = Callable[[FieldDefinition, ExtractedField, CheckContext], list[CheckResult]]
ModelCheck = Callable[[FieldDefinition, ExtractedField, CheckContext], Awaitable[list[CheckResult]]]


def threshold_ref(spec: FieldDefinition, name: str) -> str:
    return f"{spec.field_id}:v{spec.version}:check_config.{name}"
