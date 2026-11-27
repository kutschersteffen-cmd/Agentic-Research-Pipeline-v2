"""Unit tests for the local document blob store."""

from __future__ import annotations

import pytest

from arp.ingestion.indexing_config import IndexingConfig
from arp.storage import document_blob_store


def test_local_blob_store_roundtrip(tmp_path):
    store = document_blob_store.LocalBlobStore(tmp_path)
    assert not store.exists("abcdef")
    uri = store.put("abcdef", b"data")
    assert uri == "file://" + str((tmp_path / "ab" / "abcdef").resolve())
    assert store.exists("abcdef")
    assert store.get("abcdef") == b"data"


def test_blob_store_for_defaults_to_local(tmp_path):
    store = document_blob_store.blob_store_for(IndexingConfig(blob_store_dir=tmp_path))
    assert isinstance(store, document_blob_store.LocalBlobStore)
    with pytest.raises(document_blob_store.CaptureStoreError):
        document_blob_store.blob_store_for(IndexingConfig())
