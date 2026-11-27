"""Generic Postgres JSONB repository backed by the `app_documents` table.

Provides atomic upserts, version increments, namespace isolation, and clean CRUD
for document-like application state that previously lived as loose JSON files.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from arp.db.models import AppDocument
from arp.db.session import transaction


def _require_non_empty(value: str, name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{name} must be a non-empty string")
    return cleaned


class JsonDocumentRepo:
    """Namespace-scoped CRUD repository over `app_documents`."""

    def __init__(self, dsn: str, namespace: str) -> None:
        self.dsn = dsn
        self.namespace = _require_non_empty(namespace, "namespace")

    def get(self, doc_key: str) -> dict[str, Any] | None:
        key = _require_non_empty(doc_key, "doc_key")
        with transaction(self.dsn) as session:
            row = session.get(AppDocument, (self.namespace, key))
            return dict(row.payload) if row is not None else None

    def get_with_version(self, doc_key: str) -> tuple[dict[str, Any], int] | None:
        key = _require_non_empty(doc_key, "doc_key")
        with transaction(self.dsn) as session:
            row = session.get(AppDocument, (self.namespace, key))
            return (dict(row.payload), row.version) if row is not None else None

    def put(self, doc_key: str, payload: dict[str, Any]) -> int:
        """Atomically insert or update `(namespace, doc_key)`, returning the new version."""
        key = _require_non_empty(doc_key, "doc_key")
        now = datetime.now(UTC)
        stmt = (
            pg_insert(AppDocument)
            .values(
                namespace=self.namespace,
                doc_key=key,
                payload=dict(payload),
                version=1,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[AppDocument.namespace, AppDocument.doc_key],
                set_={
                    "payload": dict(payload),
                    "version": AppDocument.version + 1,
                    "updated_at": now,
                },
            )
            .returning(AppDocument.version)
        )
        with transaction(self.dsn) as session:
            return int(session.execute(stmt).scalar_one())

    def delete(self, doc_key: str) -> bool:
        key = _require_non_empty(doc_key, "doc_key")
        with transaction(self.dsn) as session:
            result = session.execute(
                delete(AppDocument).where(
                    AppDocument.namespace == self.namespace,
                    AppDocument.doc_key == key,
                )
            )
            return bool(result.rowcount)

    def exists(self, doc_key: str) -> bool:
        key = _require_non_empty(doc_key, "doc_key")
        with transaction(self.dsn) as session:
            found = session.execute(
                select(AppDocument.doc_key).where(
                    AppDocument.namespace == self.namespace,
                    AppDocument.doc_key == key,
                )
            ).scalar_one_or_none()
            return found is not None

    def list_keys(self) -> list[str]:
        with transaction(self.dsn) as session:
            rows = session.scalars(
                select(AppDocument.doc_key)
                .where(AppDocument.namespace == self.namespace)
                .order_by(AppDocument.doc_key)
            )
            return list(rows)

    def list_items(self) -> list[tuple[str, dict[str, Any]]]:
        with transaction(self.dsn) as session:
            rows = session.execute(
                select(AppDocument.doc_key, AppDocument.payload)
                .where(AppDocument.namespace == self.namespace)
                .order_by(AppDocument.doc_key)
            )
            return [(doc_key, dict(payload)) for doc_key, payload in rows]
