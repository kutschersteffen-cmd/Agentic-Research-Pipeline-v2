"""Merges the house universe with live vote ledger and Risk Monitoring alert fields."""

from __future__ import annotations

from pathlib import Path

from arp.stewardship import alerts_feed, vote_ledger_feed
from arp.stewardship.house import house_build
from arp.stewardship.universe import HouseBuild


def vote_items(runs_dir: Path | None = None, house_issuers: list[dict] | None = None, held: dict | None = None) -> list[dict]:
    """Every decision from the vote ledger (`vote_ledger_feed`)."""
    from arp.config import get_settings
    from arp.db.session import require_dsn

    settings = get_settings()
    dsn = require_dsn(settings)
    return vote_ledger_feed.ledger_rows(dsn, settings.vote_monitoring_window_days, house_issuers, held)


def portfolio_alerts() -> list:
    """Every Risk Monitoring alert, current status folded in."""
    from arp.config import get_settings
    from arp.storage.alert_queries import list_alerts
    from arp.storage.portfolio_store_factory import build_portfolio_store

    return list_alerts(build_portfolio_store(get_settings()))


def load_sample(
    _unused: Path | None = None,
    votes: list[dict] | None = None,
    alerts: list | None = None,
    base: dict | None = None,
    build: HouseBuild | None = None,
) -> dict:
    """The house issuers (`house_universe()`, or `base`) with live vote ledger and alert fields merged in."""
    held: dict[str, str] | None = None
    if base is not None:
        sample = base
    else:
        build = house_build() if build is None else build
        sample, held = build.universe, build.held
    if votes is None:
        votes = vote_items(house_issuers=sample["issuers"], held=held)
    merged = [
        vote_ledger_feed.issuer_fields(votes),
        alerts_feed.issuer_fields(portfolio_alerts() if alerts is None else alerts),
    ]
    for fields in merged:
        for issuer in sample["issuers"]:
            issuer["fields"].update(fields.get(issuer["issuer_id"], {}))
    return sample
