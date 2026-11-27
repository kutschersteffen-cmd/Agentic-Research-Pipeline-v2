"""Real steps for the plan executor: each starts an existing run type through its own entry point.

Each step is a `Step`: `start` creates the run under the call's launch key (or finds the run that key already
created), `finish` executes it, or attaches to it, in the executor's worker thread, driving its async run with
`asyncio.run`. Results are what the script sees: {"id", "run_id", "companies": [{id, name, exposure, included}], "gate"}.
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from arp.config import Settings
from arp.db.runs import RunStore
from arp.orchestration.job_manager import LAUNCH_KEY
from arp.orchestration.plan_executor import Step
from arp.orchestration.review_queue import latest_decisions
from arp.schemas.common import CompanyRef

_RANK = {"none": 0, "minor": 1, "significant": 2, "pure_play": 3}


def _companies(run_store: RunStore, universe_run_id: str, ids: list[str] | None) -> list[CompanyRef]:
    refs = run_store.load_companies(universe_run_id)
    if refs is None:
        raise ValueError(f"no companies stored for run {universe_run_id}")
    if ids is None:
        return refs
    wanted = set(ids)
    return [r for r in refs if r.company_id in wanted]


def _has_pending_review(run_store: RunStore, run_id: str) -> bool:
    decided = latest_decisions(run_store, run_id)
    return any(r["item_key"] not in decided for r in run_store.read_review_queue(run_id))


def _result(run_id: str, run_store: RunStore, companies: list[dict] | None = None) -> dict[str, Any]:
    return {"id": run_id, "run_id": run_id, "companies": companies or [],
            "gate": _has_pending_review(run_store, run_id)}


def _launch(run_store: RunStore, launch_key: str | None, create: Callable[[], str]) -> str:
    """The run `launch_key` already created, else a new one whose manifest carries the key."""
    if launch_key is not None and (found := run_store.find_launch_key(launch_key)):
        return found
    token = LAUNCH_KEY.set(launch_key)
    try:
        return create()
    finally:
        LAUNCH_KEY.reset(token)


def _finished(run_store: RunStore, run_id: str) -> bool:
    manifest = run_store.load_manifest(run_id)
    return manifest is not None and manifest.status.value not in {"pending", "running"}


def _background(run_store: RunStore, create: Callable[..., str], execute: Callable[..., Any]) -> Step:
    """A run type with a create and an async execute: `finish` executes it unless it already ended. A run left
    pending or running by a dead worker is executed again; the pipelines skip every company already stored."""
    def start(launch_key: str | None, **params: Any) -> str:
        return _launch(run_store, launch_key, lambda: create(**params))

    def finish(run_id: str, **params: Any) -> dict[str, Any]:
        if not _finished(run_store, run_id):
            asyncio.run(execute(run_id, **params))
        return _result(run_id, run_store)

    return Step(start, finish)


def build_steps(settings: Settings, run_store: RunStore) -> dict[str, Step]:
    from arp.api.deps import get_registry
    from arp.llm.factory import build_llm_client, build_verifier_llm_client

    def _universe(taxonomy_id: str, source: str):
        from arp.db.fields import SchemaRegistry
        from arp.research.taxonomy_schema import released_run_schema
        from arp.storage.taxonomy_store import TaxonomyStore
        from arp.universe import load_company_universe, not_saved_message, saved_universes, universe_source_path

        # shortcut: `source` is a saved universe's file name or a path inside the universes folder; portfolio ids
        # come with the Plans page (plan task 9).
        taxonomy, schema = released_run_schema(TaxonomyStore(settings.taxonomies_dir), SchemaRegistry(settings.postgres_dsn),
                                               taxonomy_id, None)
        path = universe_source_path(settings.runs_dir, source)
        if path is None:  # never read a file outside the universes folder
            raise ValueError(not_saved_message(source, saved_universes(settings.runs_dir)))
        companies = load_company_universe(path)
        return taxonomy, schema, path, companies

    def universe_start(launch_key: str | None, *, taxonomy_id: str, source: str) -> str:
        from arp.research.pipeline import create_theme_run

        taxonomy, schema, path, companies = _universe(taxonomy_id, source)
        return _launch(run_store, launch_key, lambda: create_theme_run(
            taxonomy.theme, companies, settings, run_store, universe_path=str(path), taxonomy_id=taxonomy.taxonomy_id,
            taxonomy_version=taxonomy.version, extraction_schema=schema))

    def universe_finish(run_id: str, *, taxonomy_id: str, source: str) -> dict[str, Any]:
        from arp.research.indirect_exposure.factory import resolve_indirect_exposure_model
        from arp.research.pipeline import execute_theme_run, load_theme_run_matches

        taxonomy, _schema, _path, companies = _universe(taxonomy_id, source)
        if not _finished(run_store, run_id):
            asyncio.run(execute_theme_run(
                run_id, taxonomy.theme, companies, llm=build_llm_client(settings),
                verifier_llm=build_verifier_llm_client(settings), registry=get_registry(), settings=settings,
                run_store=run_store, indirect_model=resolve_indirect_exposure_model(settings, use_sample=False)))
        best: dict[str, dict] = {c.company_id: {"id": c.company_id, "name": c.name, "exposure": "none",
                                                "included": False} for c in companies}
        for m in load_theme_run_matches(run_store, run_id) or []:
            row = best.setdefault(m.company_id, {"id": m.company_id, "name": m.name, "exposure": "none",
                                                 "included": False})
            if _RANK[m.exposure_estimate.value] > _RANK[row["exposure"]]:
                row["exposure"] = m.exposure_estimate.value
            row["included"] = row["included"] or m.verdict.value == "include"
        return _result(run_id, run_store, list(best.values()))

    def discovery_create(*, universe_run_id: str, doc_types: list[str] | None = None,
                         companies: list[str] | None = None) -> str:
        from arp.discovery.pipeline import create_discovery_run

        return create_discovery_run(_companies(run_store, universe_run_id, companies), doc_types, "research_plan",
                                    run_store)

    async def discovery_execute(run_id: str, *, universe_run_id: str, doc_types: list[str] | None = None,
                                companies: list[str] | None = None) -> None:
        from arp.discovery.pipeline import execute_discovery_run

        await execute_discovery_run(run_id, _companies(run_store, universe_run_id, companies), settings=settings,
                                    run_store=run_store, doc_types=doc_types)

    def extraction_create(*, universe_run_id: str, schema_id: str, companies: list[str] | None = None) -> str:
        from arp.db.fields import SchemaRegistry
        from arp.extraction.pipeline import create_extraction_run

        schema = SchemaRegistry(settings.postgres_dsn).get(schema_id)
        refs = _companies(run_store, universe_run_id, companies)
        return create_extraction_run(schema, refs, settings, run_store)  # refuses an unreleased schema

    async def extraction_execute(run_id: str, *, universe_run_id: str, schema_id: str,
                                 companies: list[str] | None = None) -> None:
        from arp.db.fields import SchemaRegistry
        from arp.extraction.pipeline import execute_extraction_run

        schema = SchemaRegistry(settings.postgres_dsn).get(schema_id)
        refs = _companies(run_store, universe_run_id, companies)
        await execute_extraction_run(run_id, schema, refs, llm=build_llm_client(settings),
                                     verifier_llm=build_verifier_llm_client(settings), registry=get_registry(),
                                     settings=settings, run_store=run_store)

    def xbrl_create(*, universe_run_id: str, companies: list[str] | None = None, market: str = "auto") -> str:
        from arp.xbrl_pipeline.fetch import create_xbrl_run

        return create_xbrl_run(_companies(run_store, universe_run_id, companies), None, False, run_store, market=market)

    async def xbrl_execute(run_id: str, *, universe_run_id: str, companies: list[str] | None = None,
                           market: str = "auto") -> None:
        from arp.xbrl_pipeline.fetch import execute_xbrl_run

        await execute_xbrl_run(run_id, _companies(run_store, universe_run_id, companies), settings=settings,
                               run_store=run_store, tags=None, refresh=False, market=market)

    def identity_create(*, universe_run_id: str, companies: list[str] | None = None) -> str:
        from arp.discovery.identity_pipeline import create_identity_run

        return create_identity_run(_companies(run_store, universe_run_id, companies), run_store)

    async def identity_execute(run_id: str, *, universe_run_id: str, companies: list[str] | None = None) -> None:
        from arp.discovery.identity_pipeline import execute_identity_run

        await execute_identity_run(run_id, _companies(run_store, universe_run_id, companies),
                                   llm=build_llm_client(settings), settings=settings, run_store=run_store)

    def report_start(_launch_key: str | None, *, source_ids: list[str], template_id: str | None = None) -> str:
        # shortcut: a report manifest has no params to carry the launch key, so a crash inside create_and_plan leaves
        # an unused report and the resumed step plans another.
        from arp.api.deps import get_reporting_store
        from arp.reporting.service import ReportingService
        from arp.schemas.reporting import ReportRequest, RunRef

        request = ReportRequest(title="Research plan report", qualitative_notes="", template_id=template_id,
                                run_refs=[RunRef(kind="run", ref_id=i) for i in source_ids])
        manifest = asyncio.run(ReportingService(get_reporting_store()).create_and_plan(request,
                                                                                         build_llm_client(settings)))
        return manifest.report_id

    def report_finish(report_id: str, **_params: Any) -> dict[str, Any]:
        from arp.api.deps import get_reporting_store
        from arp.reporting.service import ReportingService
        from arp.schemas.reporting import ReportStatus

        manifest = get_reporting_store().load_manifest(report_id)
        # A house deck stops at its storyline for a person to approve (its own gate); others render now.
        if manifest.status not in {ReportStatus.STORYLINE_READY, ReportStatus.COMPLETED}:
            manifest = asyncio.run(ReportingService(get_reporting_store()).render_from_plan(report_id))
        return {"id": manifest.report_id, "run_id": None, "result_ref": f"report:{manifest.report_id}",
                "companies": [], "gate": manifest.status == ReportStatus.STORYLINE_READY}

    return {
        "universe_build": Step(universe_start, universe_finish),
        "document_discovery": _background(run_store, discovery_create, discovery_execute),
        "extraction": _background(run_store, extraction_create, extraction_execute),
        "xbrl_facts": _background(run_store, xbrl_create, xbrl_execute),
        "report_render": Step(report_start, report_finish),
        "identity_resolution": _background(run_store, identity_create, identity_execute),
    }


def build_reviewed(run_store: RunStore):
    """A gated run is reviewed once it has no pending review item left; a gated report once its storyline is
    approved."""
    def reviewed(call: dict[str, Any]) -> bool:
        ref = call.get("result_ref") or ""
        if ref.startswith("report:"):
            from arp.api.deps import get_reporting_store
            from arp.schemas.reporting import ReportStatus

            manifest = get_reporting_store().load_manifest(ref.removeprefix("report:"))
            return manifest is not None and manifest.status != ReportStatus.STORYLINE_READY
        return not call.get("run_id") or not _has_pending_review(run_store, call["run_id"])
    return reviewed
