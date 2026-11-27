from __future__ import annotations

from arp.config import Settings
from arp.ingestion.indexing_config import IndexingConfig


def _settings(tmp_path, **overrides) -> Settings:
    return Settings(
        anthropic_api_key="unused",
        runs_dir=tmp_path / "runs",
        documents_dir=tmp_path / "docs",
        cache_dir=tmp_path / "cache",
        discovery_state_dir=tmp_path / "disc",
        portfolios_dir=tmp_path / "portfolios",
        document_store_dir=tmp_path / "docstore",
        **overrides,
    )


def test_from_settings_maps_every_field(tmp_path):
    settings = _settings(
        tmp_path,
        blob_store_dir=tmp_path / "blobs",
    )

    config = IndexingConfig.from_settings(settings)

    assert config.blob_store_dir == tmp_path / "blobs"


def test_defaults_are_entirely_disabled():
    config = IndexingConfig()
    assert config.blob_store_dir is None
