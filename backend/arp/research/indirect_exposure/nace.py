"""Compatibility re-export; canonical home is `arp.core.nace`."""

from arp.core.nace import (
    _SECTORS,
    division_sectors,
    isic_to_nace2,
    nace_known,
    nace_sectors,
    nace_title,
    normalise_nace,
)

__all__ = [
    "_SECTORS",
    "division_sectors",
    "isic_to_nace2",
    "nace_known",
    "nace_sectors",
    "nace_title",
    "normalise_nace",
]
from arp.core.nace import _NACE_REVS  # noqa: F401
