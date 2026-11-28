"""Public facade for the Transition Intel bounded context."""

from __future__ import annotations

from arp.transition_barrier import RUN_TYPE as BARRIER_RUN_TYPE
from arp.transition_barrier.dataset import check_rule_book
from arp.transition_barrier.ratings import Ratings, current_cell
from arp.transition_data.benchmarks import check_benchmarks, load_benchmarks, sector_for_isic

DOMAIN_NAME = "transition"

__all__ = [
    "BARRIER_RUN_TYPE",
    "DOMAIN_NAME",
    "Ratings",
    "check_benchmarks",
    "check_rule_book",
    "current_cell",
    "load_benchmarks",
    "sector_for_isic",
]
