"""FastAPI dependency factories for Theme Dossier and Research stores."""

from __future__ import annotations

from fastapi import Depends

from arp.api.deps import get_run_store, settings_dep
from arp.config import Settings
from arp.job_runtime.jobs import run_alive
from arp.storage.run_store import RunStore
from arp.themes.dossiers import DossierStore
from arp.themes.research import ResearchStore


def get_dossier_store(settings: Settings = Depends(settings_dep)) -> DossierStore:
    return DossierStore(settings.runs_dir / "_dossiers")


def get_research_store(
    settings: Settings = Depends(settings_dep),
    run_store: RunStore = Depends(get_run_store),
) -> ResearchStore:
    return ResearchStore(settings.runs_dir / "_dossiers" / "research", lambda run_id: run_alive(run_store, run_id))
