"""Sector codes from the security master, kept per issuer and applied over a company whenever it is read."""

from __future__ import annotations

import json
from pathlib import Path

from arp.db.json_document_repo import JsonDocumentRepo
from arp.schemas.common import CompanyRef
from arp.storage.atomic_io import atomic_write_text, read_text_utf8


class IssuerSectorStore:
    """Per-issuer sector codes `{issuer_id: {column: value}}`, backed by Postgres `app_documents` when
    `dsn` is provided or by a local JSON file otherwise."""

    def __init__(self, path: Path | None = None, *, dsn: str | None = None) -> None:
        if path is None and not dsn:
            raise ValueError("IssuerSectorStore requires either path or dsn")
        self.path = path
        self._repo = JsonDocumentRepo(dsn, "issuer_sectors") if dsn else None

    def replace(self, rows: dict[str, dict[str, str]]) -> None:
        if self._repo is not None:
            self._repo.put("all", rows)
            return
        assert self.path is not None
        atomic_write_text(self.path, json.dumps(rows))

    def get(self, issuer_id: str) -> dict[str, str]:
        return self._all().get(issuer_id, {})

    def _all(self) -> dict[str, dict[str, str]]:
        if self._repo is not None:
            return self._repo.get("all") or {}
        assert self.path is not None
        return json.loads(read_text_utf8(self.path)) if self.path.exists() else {}


def apply_master(company: CompanyRef, sectors: IssuerSectorStore) -> CompanyRef:
    """The company with the master's values over its own; matched by `company_id == issuer_id` exactly."""
    row = sectors.get(company.company_id)
    return company.model_copy(update=row) if row else company
