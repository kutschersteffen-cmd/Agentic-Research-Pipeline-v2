"""Compatibility re-export; canonical home is `arp.platform.storage.document_blob_store`."""

from arp.platform.storage.document_blob_store import (
    CaptureStoreError,
    LocalBlobStore,
    blob_store_for,
    upload_or_fail,
)

__all__ = [
    "CaptureStoreError",
    "LocalBlobStore",
    "blob_store_for",
    "upload_or_fail",
]
