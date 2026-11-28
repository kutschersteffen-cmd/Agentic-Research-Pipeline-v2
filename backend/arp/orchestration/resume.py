"""Run resume dispatcher: checks resumability, restarts counts, and invokes each run type's pipeline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from typing import TYPE_CHECKING

from arp.errors import ClientInputError
from arp.job_runtime.jobs import hold_run
from arp.llm.factory import batch_settings, build_llm_client, build_verifier_llm_client
from arp.retrieval.registry_factory import _xbrl_source
from arp.schemas.common import JobStatus, RunManifest, now_iso
from arp.storage.run_store import RunStore

if TYPE_CHECKING:
    from arp.config import Settings
    from arp.ingestion.registry import DocumentSourceRegistry
    from arp.llm.base import LLMClient


class NotResumable(ClientInputError):
    """This run cannot be resumed; the message says why."""


def _reached_every_company(run_store: RunStore, manifest: RunManifest) -> bool:
    """Every stored company has a result or was stopped for review. company_count is no guide: it counts
    refs save_companies may drop, and a company with review items counts as completed and for review."""
    companies = run_store.load_companies(manifest.run_id)
    if not companies:  # a theme run from before companies.json
        return True
    done = run_store.done_keys(manifest.run_id, include_errors=True)
    return {c.company_id for c in companies} <= done


def check_resumable(run_store: RunStore, run_id: str) -> RunManifest:
    """The run's manifest, or NotResumable saying why it can't be resumed."""
    manifest = run_store.load_manifest(run_id)
    if manifest is None:
        raise NotResumable("Unknown run_id")
    if manifest.run_type == "transition_plan":  # its pipeline is gone; the preset runs as an extraction run
        raise NotResumable("Transition-plan runs can no longer be resumed: start a new transition-plan assessment.")
    if manifest.status == JobStatus.COMPLETED and _reached_every_company(run_store, manifest):
        raise NotResumable("already completed")  # a completed run that missed companies resumes for them
    if manifest.run_type not in RESUMABLE:
        raise NotResumable(f"{manifest.run_type} runs are not resumable; start a new run")
    if manifest.run_type == "theme" and not manifest.params.get("extraction_schema_id"):
        raise NotResumable("Started before taxonomy schemas; start a new run.")
    # A theme run may instead have a universe file (runs from before companies.json).
    if not run_store.has_companies(run_id) and not (
        manifest.run_type == "theme" and manifest.params.get("universe_path")
    ):
        raise NotResumable("run has no stored inputs")
    return manifest


def restart_run(run_store: RunStore, run_id: str, failed_count: int = 0) -> None:
    """Marks the run RUNNING again (error and cancel request cleared), with
    its counts rebuilt from the files: failed items are retried, so they no
    longer count; tokens and cost stay, that money was spent. review_count
    stays too: review-stopped items are never re-run, and a discovery company's
    result and review items are stored together, so the count matches the queue."""
    with run_store.lock(run_id):
        current = run_store.load_manifest(run_id)
        current.completed_count = len(run_store.done_keys(run_id))
        current.failed_count = failed_count
        # when this restart began and how much was done by then: time left counts from here (Argus step 4)
        current.params = {**current.params, "restarted_at": now_iso(), "done_at_restart": current.completed_count + failed_count}
        current.cancel_requested = False
        current.status = JobStatus.RUNNING
        current.error = None
        run_store.save_manifest(current)


async def resume_run(
    run_id: str,
    *,
    settings: Settings,
    run_store: RunStore,
    registry: DocumentSourceRegistry,
    llm: LLMClient | None = None,
    verifier_llm: LLMClient | None = None,
    lease: bool = True,
    company_ids: list[str] | None = None,
) -> str:
    """Continues a run that was killed, failed, partly failed or cancelled,
    from what its creator stored (manifest params, companies.json). Items
    already in results.jsonl, or stopped for review, are not run again;
    plain failures are retried. Holds the run's lease throughout unless
    `lease=False` (the caller -- a LocalJobLauncher -- already holds it).
    `company_ids`: only these companies; the run's other failures stay failed."""
    manifest = check_resumable(run_store, run_id)
    run_type = manifest.run_type
    companies = run_store.load_companies(run_id)
    still_failed = 0
    if company_ids is not None:
        companies = [c for c in companies if c.company_id in company_ids]
        done = run_store.done_keys(run_id, include_errors=True)
        still_failed = len({r["key"] for r in run_store.read_errors(run_id) if r.get("key")} - done - set(company_ids))

    # The run keeps the models it started on.
    run_settings = settings.model_copy(
        update={k: v for k, v in (("llm_model", manifest.model), ("llm_verifier_model", manifest.verifier_model)) if v}
    )
    run_settings = batch_settings(run_settings, bool(manifest.params.get("batch")))
    if run_settings.llm_batch:
        # A batch run resumes on batch clients: callers' pre-built clients are real-time.
        llm = verifier_llm = None
    if run_type not in {"discovery", "xbrl_fetch"}:  # no LLM steps
        llm = llm or build_llm_client(run_settings)
        verifier_llm = verifier_llm or build_verifier_llm_client(run_settings)

    from arp.ingestion.registry import for_run

    with hold_run(run_store, run_id) if lease else nullcontext():
        restart_run(run_store, run_id, still_failed)

        common = {"settings": run_settings, "run_store": run_store}
        llms = {"llm": llm, "verifier_llm": verifier_llm, "registry": for_run(registry, run_store.run_dir(run_id))}
        return await _RESUME[run_type](run_id, manifest, companies, **common, **llms)


async def _resume_theme(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.research.pipeline import resume_theme_run

    return await resume_theme_run(run_id, llm=llm, verifier_llm=verifier_llm, registry=registry, settings=settings,
                                  run_store=run_store)


async def _resume_extraction(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.extraction.pipeline import execute_extraction_run, load_run_schema

    schema = load_run_schema(run_store, run_id)
    return await execute_extraction_run(run_id, schema, companies, llm=llm, verifier_llm=verifier_llm, registry=registry,
                                        settings=settings, run_store=run_store, xbrl_source=_xbrl_source(settings))


async def _resume_identity(run_id, manifest, companies, *, settings, run_store, llm, verifier_llm, registry) -> str:
    from arp.discovery.identity_pipeline import execute_identity_run

    return await execute_identity_run(run_id, companies, llm=llm, settings=settings, run_store=run_store)


async def _resume_discovery(run_id, manifest, companies, *, settings, run_store, **_) -> str:
    from arp.discovery.pipeline import execute_discovery_run
    from arp.schemas.discovery import DiscoveryRunParams

    params = DiscoveryRunParams.model_validate(manifest.params)
    return await execute_discovery_run(run_id, companies, doc_types=params.doc_types or None, settings=settings,
                                       run_store=run_store)


async def _resume_xbrl_fetch(run_id, manifest, companies, *, settings, run_store, **_) -> str:
    from arp.xbrl_pipeline.fetch import execute_xbrl_run

    return await execute_xbrl_run(
        run_id, companies, settings=settings, run_store=run_store, tags=manifest.params.get("tags"),
        refresh=bool(manifest.params.get("refresh")), market=manifest.params.get("market", "sec"),
    )


# One entry per resumable run type: how a resume continues it.
_RESUME: dict[str, Callable[..., Awaitable[str]]] = {
    "theme": _resume_theme,
    "extraction": _resume_extraction,
    "identity": _resume_identity,
    "discovery": _resume_discovery,
    "xbrl_fetch": _resume_xbrl_fetch,
}
RESUMABLE = frozenset(_RESUME)
