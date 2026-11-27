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
    blob_store_dir: Path | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> IndexingConfig:
        return cls(
            blob_store_dir=settings.blob_store_dir,
        )
