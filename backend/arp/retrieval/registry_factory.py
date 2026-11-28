"""Document source registry and content-store factories shared by API entrypoints and orchestration."""

from __future__ import annotations

from functools import lru_cache

from arp.config import Settings, get_settings
from arp.ingestion.edgar import EdgarDocumentSource
from arp.ingestion.esef import EsefDocumentSource
from arp.ingestion.indexing_config import IndexingConfig
from arp.ingestion.local_files import LocalFileDocumentSource
from arp.ingestion.registry import DocumentSourceRegistry
from arp.retrieval.content_store_factory import content_store_for
from arp.storage.document_store import DocumentContentStore


@lru_cache
def get_document_content_store() -> DocumentContentStore:
    settings = get_settings()
    return content_store_for(settings)


def build_registry(settings: Settings, content_store: DocumentContentStore) -> DocumentSourceRegistry:
    """get_registry's sources, for a run that needs its own content store
    (a restart from Find evidence re-parses rather than reading the cache)."""
    indexing_config = IndexingConfig.from_settings(settings)
    return DocumentSourceRegistry(
        [
            LocalFileDocumentSource(
                settings.documents_dir,
                content_store=content_store,
                max_concurrent_parses=settings.max_concurrent_parses,
                indexing_config=indexing_config,
            ),
            EdgarDocumentSource(
                settings.edgar_user_agent,
                settings.cache_dir,
                content_store=content_store,
                submissions_ttl_hours=settings.edgar_submissions_ttl_hours,
                indexing_config=indexing_config,
            ),
            *([EsefDocumentSource(settings.esef_index_url, settings.cache_dir, content_store=content_store,
                                  indexing_config=indexing_config)] if settings.esef_enabled else []),
        ],
        settings=settings,
    )


@lru_cache
def get_registry() -> DocumentSourceRegistry:
    settings = get_settings()
    return build_registry(settings, get_document_content_store())


def _xbrl_source(settings: Settings):
    """Built as arp.api.deps.get_xbrl_source builds it; the pipelines
    themselves check xbrl_facts_enabled."""
    from arp.ingestion.edgar import EdgarDocumentSource
    from arp.ingestion.xbrl import XbrlFactSource
    from arp.platform.storage.indexing_config import IndexingConfig
    from arp.retrieval.content_store_factory import content_store_for

    edgar = EdgarDocumentSource(
        settings.edgar_user_agent,
        settings.cache_dir,
        content_store=content_store_for(settings),
        submissions_ttl_hours=settings.edgar_submissions_ttl_hours,
        indexing_config=IndexingConfig.from_settings(settings),  # the blob store tagged values are frozen into
    )
    return XbrlFactSource(edgar, settings.cache_dir, ttl_hours=settings.xbrl_facts_ttl_hours)
