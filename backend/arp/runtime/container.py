"""Explicit composition root wiring the 5 bounded contexts and runtime hooks at process startup."""

from __future__ import annotations

from types import ModuleType

from arp.domains import DOMAINS
from arp.domains.argus import public as argus
from arp.domains.data_hub import public as data_hub
from arp.domains.rd_lab import public as rd_lab
from arp.domains.stewardiq import public as stewardiq
from arp.domains.transition import public as transition
from arp.platform.hooks import register_extraction_runner


def domain_facades() -> dict[str, ModuleType]:
    """Return the 5 vertical-slice bounded-context public facades keyed by domain name."""
    facades: dict[str, ModuleType] = {
        "stewardiq": stewardiq,
        "argus": argus,
        "transition": transition,
        "rd_lab": rd_lab,
        "data_hub": data_hub,
    }
    assert tuple(facades.keys()) == DOMAINS
    return facades


def wire() -> None:
    """Register cross-domain runtime hooks via domain public facades (idempotent)."""

    def _create(*args, **kwargs):
        return argus.create_extraction_run(*args, **kwargs)

    async def _execute(*args, **kwargs):
        return await argus.execute_extraction_run(*args, **kwargs)

    register_extraction_runner(_create, _execute)
