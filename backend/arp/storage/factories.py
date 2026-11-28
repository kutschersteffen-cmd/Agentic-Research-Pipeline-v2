"""Low-level cached store factories shared by API entrypoints and lower-layer modules.

`arp.api.deps` re-exports these exact callables so FastAPI `app.dependency_overrides` keys stay identical
while keeping lower-layer modules free of upward imports into `arp.api`.
"""

from __future__ import annotations

from functools import lru_cache

from arp.config import get_settings
from arp.db.session import require_dsn
from arp.storage.portfolio_store_factory import build_portfolio_store
from arp.storage.reporting_store import ReportingStore
from arp.storage.run_store import RunStore
from arp.storage.taxonomy_store import TaxonomyStore


@lru_cache
def get_run_store() -> RunStore:
    settings = get_settings()
    return RunStore(require_dsn(settings), settings.runs_dir)


@lru_cache
def get_taxonomy_store() -> TaxonomyStore:
    return TaxonomyStore(get_settings().taxonomies_dir)


@lru_cache
def get_portfolio_store():
    return build_portfolio_store(get_settings())


@lru_cache
def get_reporting_store() -> ReportingStore:
    settings = get_settings()
    return ReportingStore(settings.reports_dir, settings.report_templates_dir, settings.report_images_dir)
