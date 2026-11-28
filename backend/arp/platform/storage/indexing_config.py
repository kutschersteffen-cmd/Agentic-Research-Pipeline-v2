"""Narrow config bundle for the local immutable blob store (`document_blob_store`)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class IndexingConfig:
    blob_store_dir: Path | None = None

    @classmethod
    def from_settings(cls, settings: Any) -> IndexingConfig:
        return cls(
            blob_store_dir=settings.blob_store_dir,
        )
