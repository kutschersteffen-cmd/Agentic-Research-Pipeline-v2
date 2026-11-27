from __future__ import annotations

import asyncio
import re
from collections import Counter
from pathlib import Path
from typing import Literal

import typer

from arp.cli._shared import _run_store
from arp.config import get_settings
from arp.storage.identifier_map import IdentifierMapStore
from arp.universe import load_company_universe
from arp.universe_workbench.mapping import MasterIndex
from arp.universe_workbench.routing import route_universe
from arp.xbrl_pipeline.fetch import build_source, create_xbrl_run, execute_xbrl_run
from arp.xbrl_pipeline.store import XbrlStore

xbrl_app = typer.Typer(help="XBRL fact pipeline: fetch SEC company facts or EU ESEF filings, screen routing, inspect segments.")
_TAG_ID = re.compile(r"^[\w.-]+:[\w.-]+$")


def _store() -> XbrlStore:
    return XbrlStore(get_settings().xbrl_dir)


def _split(text: str) -> list[str]:
    return [t.strip() for t in text.split(",") if t.strip()]


def _validate_tags(tag_list: list[str]) -> frozenset[str]:
    bad = [t for t in tag_list if not _TAG_ID.match(t)]
    if bad:
        typer.echo(f"malformed tag {bad[0]!r}: expected taxonomy:Concept, e.g. us-gaap:Revenues", err=True)
        raise typer.Exit(2)
    return frozenset(tag_list)


@xbrl_app.command("fetch")
def fetch(
    universe: Path = typer.Option(...),
    tags: str = typer.Option("", help="Comma-separated tags (us-gaap:Revenues,...); empty = mode All, keep every tag."),
    refresh: bool = typer.Option(False, help="Bypass the facts cache and re-download."),
    market: str = typer.Option("auto", help="auto (route each company), sec (SEC company facts) or esef (EU ESEF filings)."),
) -> None:
    if market not in ("auto", "sec", "esef"):
        typer.echo(f"--market must be auto, sec or esef, got {market!r}", err=True)
        raise typer.Exit(2)
    settings = get_settings()
    companies = load_company_universe(universe)
    tag_list = _split(tags) or None
    if tag_list:
        _validate_tags(tag_list)
    run_store = _run_store()
    index = MasterIndex.build(IdentifierMapStore(settings.identifier_map_path)) if market == "auto" else None
    run_id = create_xbrl_run(companies, tag_list, refresh, run_store, market=market, index=index)
    asyncio.run(execute_xbrl_run(
        run_id, companies, settings=settings, run_store=run_store, tags=tag_list, refresh=refresh,
        market=market, source=build_source(settings, refresh=refresh) if market == "sec" else None,
    ))
    rows = run_store.read_results(run_id)
    counts = Counter(r["status"] for r in rows)
    typer.echo("  ".join(f"{k}={v}" for k, v in sorted(counts.items())) or "no companies fetched")
    typer.echo(f"Run: {run_id}")


@xbrl_app.command("screen")
def screen(universe: Path = typer.Option(...)) -> None:
    """Show which source each company would be fetched from; writes no run."""
    index = MasterIndex.build(IdentifierMapStore(get_settings().identifier_map_path))
    routes = route_universe(load_company_universe(universe), index)
    for r in routes:
        typer.echo(f"{r.company.company_id}  {r.market or r.status}  {r.basis or '-'}  {r.detail}")
    counts = Counter(r.market or r.status for r in routes)
    typer.echo("  ".join(f"{k}={counts[k]}" for k in ("sec", "esef", "no_source", "unrouted")))


def _key_for(store: XbrlStore, company_id: str) -> str | None:
    return next((k for k in store.ciks() if company_id in store.company_ids(k)), None)


@xbrl_app.command("segments")
def segments(company_id: str,
             axis: Literal["segment", "product", "geography"] = typer.Option("segment", "--axis")) -> None:
    """Segment rows (revenue, capex, opex, ...) of a company's latest annual filing."""
    store = _store()
    key = _key_for(store, company_id)
    if key is None:
        typer.echo(f"No XBRL data for {company_id}", err=True)
        raise typer.Exit(1)
    level = axis == "product"
    typer.echo("year  segment  level  metric  value  unit  concept  sum_check" if level
               else "year  segment  metric  value  unit  concept  sum_check")
    for r in store.read_segments(key):
        if r.axis_kind != axis:
            continue
        value = int(r.value) if r.value.is_integer() else r.value
        typer.echo(f"{r.fiscal_year}  {r.segment}  {f'{r.level}  ' if level else ''}{r.metric}  {value}  {r.unit}  "
                   f"{r.concept}  {str(r.sum_matches_total).lower()}")


@xbrl_app.command("segment-note")
def segment_note(company_id: str) -> None:
    """The segment note text of a company's latest annual filing."""
    store = _store()
    key = _key_for(store, company_id)
    note = store.read_segment_note(key) if key else None
    if note is None:
        typer.echo(f"No segment note for {company_id}", err=True)
        raise typer.Exit(1)
    typer.echo(note)
