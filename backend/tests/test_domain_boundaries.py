"""Tests for the 5 vertical-slice bounded-context facades and strict zero-cycle DAG invariant."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from arp.domains import DOMAINS
from arp.runtime import container

REPO_ROOT = Path(__file__).resolve().parents[2]
ARP_ROOT = REPO_ROOT / "backend" / "arp"
ARCH_GUARD_PATH = REPO_ROOT / ".github" / "scripts" / "arch_guard.py"


def _load_arch_guard():
    spec = importlib.util.spec_from_file_location("_arp_arch_guard", ARCH_GUARD_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_arp_arch_guard"] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop("_arp_arch_guard", None)
    return mod


def test_five_bounded_context_facades_expose_declared_public_contracts() -> None:
    facades = container.domain_facades()
    assert tuple(facades.keys()) == DOMAINS
    assert set(DOMAINS) == {"stewardiq", "argus", "transition", "rd_lab", "data_hub"}

    for domain_name, facade in facades.items():
        assert domain_name == facade.DOMAIN_NAME
        exported = getattr(facade, "__all__", ())
        assert exported, f"{domain_name}.public must declare __all__"
        for symbol in exported:
            assert hasattr(facade, symbol), f"{domain_name}.public missing exported symbol {symbol!r}"


def test_composition_root_wire_is_idempotent() -> None:
    container.wire()
    container.wire()


def test_strict_architecture_dag_has_zero_violations_and_zero_cycles() -> None:
    ag = _load_arch_guard()
    result = ag.analyze(ARP_ROOT)
    assert result.layer_violations == [], f"Layer violations: {result.layer_violations}"
    assert result.module_cycle_edges == [], f"Module cycles: {result.module_cycle_edges}"
    assert result.package_cycle_edges == [], f"Package cycles: {result.package_cycle_edges}"
