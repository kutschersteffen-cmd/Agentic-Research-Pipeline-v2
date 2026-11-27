"""Generic Postgres JSONB repository backed by the `app_documents` table.

Provides atomic upserts, version increments, namespace isolation, and clean CRUD
for document-like application state that previously lived as loose JSON files.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from arp.db.engine import get_engine
from arp.db.models import AppDocument


@contextmanager
def _tx(dsn: str) -> Iterator[Session]:
    with Session(get_engine(dsn)) as session, session.begin():
        yield session


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
        with _tx(self.dsn) as session:
            row = session.get(AppDocument, (self.namespace, key))
            return dict(row.payload) if row is not None else None

    def get_with_version(self, doc_key: str) -> tuple[dict[str, Any], int] | None:
        key = _require_non_empty(doc_key, "doc_key")
        with _tx(self.dsn) as session:
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
        with _tx(self.dsn) as session:
            return int(session.execute(stmt).scalar_one())

    def put_if_absent(self, doc_key: str, payload: dict[str, Any]) -> bool:
        """Atomically insert `(namespace, doc_key)` only if it does not already exist.

        Returns True when inserted, False when a record already exists (Postgres equivalent of O_EXCL).
        """
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
            .on_conflict_do_nothing(index_elements=[AppDocument.namespace, AppDocument.doc_key])
            .returning(AppDocument.doc_key)
        )
        with _tx(self.dsn) as session:
            return session.execute(stmt).scalar_one_or_none() is not None

    def update(self, doc_key: str, updater: Callable[[dict[str, Any] | None], dict[str, Any]]) -> dict[str, Any]:
        """Atomically read, transform, and upsert `(namespace, doc_key)` under a transaction-scoped advisory lock."""
        key = _require_non_empty(doc_key, "doc_key")
        with _tx(self.dsn) as session:
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(:ns), hashtext(:k))"),
                {"ns": self.namespace, "k": key},
            )
            row = session.get(AppDocument, (self.namespace, key))
            current = dict(row.payload) if row is not None else None
            updated = dict(updater(current))
            now = datetime.now(UTC)
            if row is None:
                session.add(
                    AppDocument(
                        namespace=self.namespace,
                        doc_key=key,
                        payload=updated,
                        version=1,
                        created_at=now,
                        updated_at=now,
                    )
                )
            else:
                row.payload = updated
                row.version = row.version + 1
                row.updated_at = now
            return updated

    def delete(self, doc_key: str) -> bool:
        key = _require_non_empty(doc_key, "doc_key")
        with _tx(self.dsn) as session:
            result = session.execute(
                delete(AppDocument).where(
                    AppDocument.namespace == self.namespace,
                    AppDocument.doc_key == key,
                )
            )
            return bool(result.rowcount)

    def exists(self, doc_key: str) -> bool:
        key = _require_non_empty(doc_key, "doc_key")
        with _tx(self.dsn) as session:
            found = session.execute(
                select(AppDocument.doc_key).where(
                    AppDocument.namespace == self.namespace,
                    AppDocument.doc_key == key,
                )
            ).scalar_one_or_none()
            return found is not None

    def list_keys(self) -> list[str]:
        with _tx(self.dsn) as session:
            rows = session.scalars(
                select(AppDocument.doc_key)
                .where(AppDocument.namespace == self.namespace)
                .order_by(AppDocument.doc_key)
            )
            return list(rows)

    def list_items(self) -> list[tuple[str, dict[str, Any]]]:
        with _tx(self.dsn) as session:
            rows = session.execute(
                select(AppDocument.doc_key, AppDocument.payload)
                .where(AppDocument.namespace == self.namespace)
                .order_by(AppDocument.doc_key)
            )
            return [(doc_key, dict(payload)) for doc_key, payload in rows]
