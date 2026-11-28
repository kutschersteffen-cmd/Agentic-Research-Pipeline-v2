"""Compatibility re-export; canonical home is `arp.core.nace`."""

from arp.core.nace import (
    _NACE_ISIC,
    _NACE_REVS,
    _SECTORS,
    _isic4_sections,
    _sector_rows,
    code_set_sectors,
    division_sectors,
    isic4_section,
    isic_to_nace2,
    nace2_to_isic4,
    nace_known,
    nace_sectors,
    nace_title,
    normalise_nace,
    sector_nace2_codes,
    sector_name,
)

__all__ = [
    "_NACE_ISIC",
    "_NACE_REVS",
    "_SECTORS",
    "_isic4_sections",
    "_sector_rows",
    "code_set_sectors",
    "division_sectors",
    "isic4_section",
    "isic_to_nace2",
    "nace2_to_isic4",
    "nace_known",
    "nace_sectors",
    "nace_title",
    "normalise_nace",
    "sector_nace2_codes",
    "sector_name",
]
