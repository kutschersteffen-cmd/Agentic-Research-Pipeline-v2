"""Local immutable blob store for each source document's original bytes,
keyed by the same content-addressed hash DocumentContentStore/derive_doc_id
already compute (arp/db/documents.py).

Scope is deliberate: this store only ever holds the original, immutable
source file so a reviewer or auditor can retrieve the exact original PDF
a citation came from, even if the local working copy is gone.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from arp.core.atomic_io import atomic_write_bytes
from arp.core.errors import NotConfigured
from arp.platform.storage.indexing_config import IndexingConfig


class CaptureStoreError(NotConfigured):
    """The original bytes could not be stored and verified."""


class LocalBlobStore:
    """Default store: `root/<key[:2]>/<key>` on local disk."""

    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def _path(self, content_key: str) -> Path:
        return self._root / content_key[:2] / content_key

    def uri(self, content_key: str) -> str:
        return "file://" + str(self._path(content_key).resolve())

    def put(self, content_key: str, data: bytes) -> str:
        atomic_write_bytes(self._path(content_key), data)
        return self.uri(content_key)

    def get(self, content_key: str) -> bytes:
        return self._path(content_key).read_bytes()

    def exists(self, content_key: str) -> bool:
        return self._path(content_key).is_file()


def blob_store_for(config: IndexingConfig) -> LocalBlobStore:
    if config.blob_store_dir is None:
        raise CaptureStoreError("no blob store configured: set blob_store_dir")
    return LocalBlobStore(config.blob_store_dir)


def upload_or_fail(store: LocalBlobStore, content_key: str, data: bytes) -> str:
    """Stores `data` under `content_key` (its sha256) and reads it back to
    verify. Skips the put when the blob is already there. Any error or hash
    mismatch raises CaptureStoreError, so a document never counts as
    collected without a verified copy."""
    try:
        if hashlib.sha256(data).hexdigest() != content_key:
            raise ValueError("content_key is not the sha256 of the bytes")
        uri = store.uri(content_key)
        if not store.exists(content_key):
            uri = store.put(content_key, data)
        if hashlib.sha256(store.get(content_key)).hexdigest() != content_key:
            raise ValueError("hash mismatch on re-read")
        return uri
    except Exception as exc:
        raise CaptureStoreError(f"store failed for {content_key}: {exc}") from exc
