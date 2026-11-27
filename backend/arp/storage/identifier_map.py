from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from arp.db.companies import normalise_identifier  # noqa: F401  (re-export)
from arp.db.json_document_repo import JsonDocumentRepo
from arp.schemas.issuer import IdentifierMap
from arp.storage.atomic_io import atomic_write_text
from arp.storage.jsonl_io import append_jsonl, read_jsonl


class IdentifierMapStore:
    """External identifiers per issuer, backed by Postgres `app_documents` when `dsn` is provided
    or by an append-only JSONL file otherwise."""

    def __init__(self, path: Path | None = None, *, dsn: str | None = None) -> None:
        if path is None and not dsn:
            raise ValueError("IdentifierMapStore requires either path or dsn")
        self.path = path
        self.dsn = dsn
        self._repo = JsonDocumentRepo(dsn, "identifier_map") if dsn else None

    def add(self, row: IdentifierMap) -> None:
        payload = row.model_dump(mode="json")
        if self._repo is not None:
            self._repo.update("rows", lambda cur: {"rows": [*(cur or {}).get("rows", []), payload]})
            return
        assert self.path is not None
        append_jsonl(self.path, payload)

    def replace(self, rows: list[IdentifierMap]) -> None:
        dumped = [row.model_dump(mode="json") for row in rows]
        if self._repo is not None:
            self._repo.put("rows", {"rows": dumped})
            return
        assert self.path is not None
        atomic_write_text(self.path, "".join(json.dumps(r) + "\n" for r in dumped))

    def rows(self) -> list[IdentifierMap]:
        if self._repo is not None:
            doc = self._repo.get("rows") or {}
            return [IdentifierMap.model_validate(r) for r in doc.get("rows", [])]
        assert self.path is not None
        return [IdentifierMap.model_validate(r) for r in read_jsonl(self.path)]

    def resolve(self, scheme: str, value: str, *, on: str | None = None) -> list[str]:
        day = on or date.today().isoformat()
        want = normalise_identifier(scheme, value)
        keys: list[str] = []
        for r in self.rows():
            if r.scheme != scheme or normalise_identifier(scheme, r.value) != want:
                continue
            if (r.valid_from and day < r.valid_from) or (r.valid_to and day >= r.valid_to):
                continue
            if r.issuer_key not in keys:
                keys.append(r.issuer_key)
        return keys

    def rows_for(self, issuer_key: str) -> list[IdentifierMap]:
        return [r for r in self.rows() if r.issuer_key == issuer_key]
