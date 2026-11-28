"""Explicit composition root wiring the 5 bounded contexts and runtime hooks at process startup."""

from __future__ import annotations

from types import ModuleType

from arp.domains import DOMAINS
from arp.platform.hooks import register_extraction_runner


def domain_facades() -> dict[str, ModuleType]:
    """Return the 5 vertical-slice bounded-context public facades keyed by domain name."""
    from arp.domains.argus import public as argus
    from arp.domains.data_hub import public as data_hub
    from arp.domains.rd_lab import public as rd_lab
    from arp.domains.stewardiq import public as stewardiq
    from arp.domains.transition import public as transition

    facades: dict[str, ModuleType] = {
        "stewardiq": stewardiq,
        "argus": argus,
        "transition": transition,
        "rd_lab": rd_lab,
        "data_hub": data_hub,
    }
    if tuple(facades.keys()) != DOMAINS:
        raise RuntimeError(f"domain_facades keys {tuple(facades.keys())} do not match DOMAINS {DOMAINS}")
    return facades


def wire() -> None:
    """Register cross-domain runtime hooks via domain public facades (idempotent)."""
    from arp.domains.argus import public as argus

    register_extraction_runner(argus.create_extraction_run, argus.execute_extraction_run)
