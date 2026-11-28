"""Pure GICS CSV reference and company-code loaders."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GicsReferenceEntry:
    code: str
    label: str
    level: str


def load_gics_reference(path: Path) -> list[GicsReferenceEntry]:
    entries: list[GicsReferenceEntry] = []
    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            entries.append(
                GicsReferenceEntry(
                    code=row["code"].strip(),
                    label=row["label"].strip(),
                    level=row.get("level", "").strip(),
                )
            )
    return entries


def load_company_gics(path: Path) -> dict[str, str]:
    """company_id -> GICS code, from a user-supplied CSV (company_id,gics_code)."""
    with path.open(newline="") as f:
        return {row["company_id"].strip(): row["gics_code"].strip() for row in csv.DictReader(f)}
