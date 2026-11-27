"""Stewardship summary report as data and as a House Deck PowerPoint (no LLM).

Rendered by the house deck renderer (`arp.reporting.house_pptx`, plus a PDF
next to it when requested), so it picks up the house deck design without any
model-written prose.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from arp.reporting.browser import write_pdf
from arp.reporting.chart_data import deck_from_plan
from arp.reporting.house_pptx import build_house_pptx
from arp.reporting.html_render import render_deck_html
from arp.schemas.engagement import EngagementRecord
from arp.schemas.reporting import (
    ChartSpec,
    ChartType,
    ColumnKind,
    ContentItem,
    DatasetColumn,
    QuantitativeDataset,
    ReportPlan,
    ReportSection,
    SectionLayoutHint,
    TableSpec,
)
from arp.stewardship.monitoring import OPEN
from arp.stewardship.sample import load_sample


def _w(s: str | None) -> str:
    return (s or "").replace("_", " ")


def client_report(
    root: Path,
    client_name: str,
    records: list[EngagementRecord],
) -> dict:
    """Compile a deterministic stewardship summary from the house universe and live engagement records."""
    sample = load_sample()
    open_issues = [(r, i) for r in records for i in r.issues if i.status in OPEN]
    closed_issues = [(r, i) for r in records for i in r.issues if i.status not in OPEN]
    by_theme = Counter(_w(i.theme) for _, i in open_issues)
    by_sector = Counter(i.get("sector") or "Unclassified" for i in sample["issuers"])

    summary = [
        f"Covered issuers: {len(sample['issuers'])} companies across {len(by_sector)} sectors.",
        f"Engagements: {len(open_issues)} open, {len(closed_issues)} closed across {len(records)} companies.",
    ]
    if by_theme:
        top = ", ".join(f"{t} ({n})" for t, n in by_theme.most_common(3))
        summary.append(f"Active themes: {top}.")

    return {
        "client": client_name,
        "as_of": datetime.now(UTC).date().isoformat(),
        "summary": summary,
        "sectors": [{"sector": sec, "companies": count} for sec, count in sorted(by_sector.items())],
        "engagements": [
            {
                "company": r.name,
                "theme": _w(i.theme),
                "status": _w(i.status.value),
                "step": _w(i.escalation_stage.value),
                "milestone": _w(i.milestone_stage.value),
            }
            for r, i in open_issues
        ],
        "notes": [
            "Covered company universe: configured house universe (portfolio holdings or synthetic sample).",
            "Engagements, correspondence and commitments: live records from the stewardship store.",
        ],
    }


def _dataset(name: str, rows: list[dict], numeric: set[str] = frozenset()) -> QuantitativeDataset:
    cols = list(rows[0]) if rows else []
    return QuantitativeDataset(
        dataset_id=name,
        name=name,
        columns=[DatasetColumn(name=c, kind=ColumnKind.NUMBER if c in numeric else ColumnKind.CATEGORY) for c in cols],
        rows=rows,
    )


def build_pptx(report: dict, out_path: Path, pdf: bool = True) -> Path:
    def text(*lines: str) -> list[ContentItem]:
        return [ContentItem(text=t) for t in lines]

    datasets = [
        _dataset("sectors", report["sectors"], {"companies"}),
        _dataset("engagements", report["engagements"]),
    ]
    sections = [
        ReportSection(
            heading="Stewardship at a glance",
            layout_hint=SectionLayoutHint.TEXT_ONLY,
            narrative=text(*report["summary"]),
        ),
        (
            ReportSection(
                heading="Covered universe by sector",
                narrative=text("Companies covered by the house stewardship programme."),
                chart=ChartSpec(dataset_id="sectors", chart_type=ChartType.BAR, category_column="sector", value_columns=["companies"]),
            )
            if report["sectors"]
            else ReportSection(heading="Covered universe by sector", narrative=text("No covered companies in the current house universe."))
        ),
        (
            ReportSection(
                heading="Open engagements",
                layout_hint=SectionLayoutHint.CHART_FOCUS,
                narrative=text("Active company engagements and current escalation steps."),
                table=TableSpec(dataset_id="engagements", max_rows=12),
            )
            if report["engagements"]
            else ReportSection(heading="Open engagements", narrative=text("No open engagements."))
        ),
        ReportSection(
            heading="Data sources",
            layout_hint=SectionLayoutHint.TEXT_ONLY,
            narrative=text(*report["notes"]),
            appendix=True,
        ),
    ]
    plan = ReportPlan(title=f"{report['client']}: stewardship report", subtitle=f"As of {report['as_of']}", sections=sections)
    return render_plan(plan, datasets, out_path, pdf)


def render_plan(plan: ReportPlan, datasets: list[QuantitativeDataset], out_path: Path, pdf: bool = True) -> Path:
    """House-renders a hand-built plan, no LLM: the pptx at `out_path`, and with `pdf` a PDF next to it
    (that one needs Chromium, so skip it where the PDF is not kept)."""
    deck = deck_from_plan(plan)
    build_house_pptx(deck, datasets, out_path)
    if not pdf:
        return out_path
    # ponytail: asyncio.run, so callers must be sync (the routes are plain `def`); make this async if one isn't.
    asyncio.run(write_pdf(render_deck_html(deck, datasets), out_path.with_suffix(".pdf")))
    return out_path
