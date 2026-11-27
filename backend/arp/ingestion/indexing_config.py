"""Bundles the small subset of Settings that the object-store live-upload
hook (arp/storage/document_blob_store.py) needs, so DocumentSource
implementations (LocalFileDocumentSource, EdgarDocumentSource) take one
narrow, explicit config object instead of the whole Settings -- matching
how those classes already take individual primitive values (user_agent,
cache_dir, ttl) rather than a Settings instance.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arp.config import Settings


@dataclass(frozen=True)
class IndexingConfig:
    object_store_endpoint_url: str | None = None
    object_store_access_key: str | None = None
    object_store_secret_key: str | None = None
    object_store_bucket: str = "arp-documents"
    object_store_live_upload_enabled: bool = False
    blob_store_dir: Path | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> IndexingConfig:
        return cls(
            object_store_endpoint_url=settings.object_store_endpoint_url,
            object_store_access_key=settings.object_store_access_key,
            object_store_secret_key=settings.object_store_secret_key,
            object_store_bucket=settings.object_store_bucket,
            object_store_live_upload_enabled=settings.object_store_live_upload_enabled,
            blob_store_dir=settings.blob_store_dir,
        )

    @property
    def object_store_enabled(self) -> bool:
        return bool(self.object_store_endpoint_url and self.object_store_live_upload_enabled)
