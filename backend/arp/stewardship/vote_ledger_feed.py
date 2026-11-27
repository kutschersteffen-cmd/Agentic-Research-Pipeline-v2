"""Votes from the vote ledger (vote_meetings, vote_items, vote_decisions) for stewardship monitoring."""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import aliased

from arp.db import models as m
from arp.db.companies import normalise_identifier
from arp.db.session import transaction
from arp.storage.postgres_models import VoteDecisionModel, VoteItemModel, VoteMeetingModel

DEMO_SOURCES = ("mock_voice_seed", "npx_urth_demo", "cockpit_demo")


def ledger_rows_for_settings(settings, house_issuers: list[dict] | None = None, held_isins: dict | None = None) -> list[dict]:
    """`ledger_rows` using the DSN and vote monitoring window from `settings`."""
    from arp.db.session import require_dsn

    return ledger_rows(require_dsn(settings), settings.vote_monitoring_window_days, house_issuers, held_isins)


def ledger_rows(dsn: str, window_days: int, house_issuers: list[dict] | None = None, held_isins: dict | None = None) -> list[dict]:
    """One row per decision on a meeting within `window_days` before the ledger's newest meeting_date.
    `house_issuers`: `house_universe()["issuers"]` when the caller already built it (building it twice is slow)."""
    M, D = VoteMeetingModel, VoteDecisionModel
    with transaction(dsn) as s:
        newest = s.scalar(select(func.max(VoteMeetingModel.meeting_date)))
        if newest is None:
            return []
        q = (
            # columns, not ORM objects: building ~60k objects per read was a third of the worklist's ledger time
            select(
                M.isin, M.company_id, M.issuer_name, M.meeting_date, VoteItemModel.item_number,
                VoteItemModel.management_recommendation, D.run_id, D.vote, D.decided_by, D.against_management,
                M.source.label("meeting_source"), D.source.label("decision_source"),
            )  # fmt: skip
            .join(VoteItemModel, VoteItemModel.meeting_id == VoteMeetingModel.meeting_id)
            .join(VoteDecisionModel, VoteDecisionModel.item_id == VoteItemModel.item_id)
            .where(VoteMeetingModel.meeting_date >= newest - timedelta(days=window_days))
        )
        found = s.execute(q).all()
        if not found:
            return []
        held = {} if held_isins is None else held_isins  # ISIN -> house issuer holding it in the latest snapshot
        # monitoring keys on house issuer ids: the house issuer that holds the ISIN wins; else the stw_companies
        # key (set only for a known company); else the registry's universe id for the ISIN; else `isin_<ISIN>`
        by_isin = _registry_ids(s, {r.isin for r in found if r.isin and not held.get(r.isin) and r.company_id is None}, house_issuers)
        rows = []
        for r in found:
            company_id = held.get(r.isin or "") or r.company_id or by_isin.get(r.isin or "")
            if company_id is None:
                continue
            rows.append(
                {
                    "run_id": r.run_id,
                    "company_id": company_id,
                    "company": r.issuer_name,
                    "meeting_date": r.meeting_date.date().isoformat(),
                    "item": r.item_number,
                    "type": None,
                    "management": r.management_recommendation,
                    "policy": None,
                    "vote": r.vote,
                    "status": "cast",
                    "decided_by": r.decided_by or "",
                    "co_signed_by": None,
                    "note": None,
                    "overrode_policy": False,
                    "against_management": bool(r.against_management),
                    "demo": r.meeting_source in DEMO_SOURCES or r.decision_source in DEMO_SOURCES,
                }
            )
        return rows


def issuer_fields(rows: list[dict]) -> dict[str, dict]:
    """issuer id -> `vote.*` company fields, over decided and cast items only."""
    fields: dict[str, dict] = defaultdict(
        lambda: {
            "vote.decided": 0,
            "vote.against_management": 0,
            "vote.against_management_non_demo": 0,
            "vote.overrode_policy": 0,
            "vote.last_meeting_date": None,
        }
    )
    for r in rows:
        if r["vote"] is None:
            continue
        f = fields[r["company_id"]]
        f["vote.decided"] += 1
        f["vote.against_management"] += r["against_management"]
        f["vote.against_management_non_demo"] += r["against_management"] and not r.get("demo")
        f["vote.overrode_policy"] += r["overrode_policy"]
        f["vote.last_meeting_date"] = max(filter(None, [f["vote.last_meeting_date"], r["meeting_date"]]), default=None)
    return dict(fields)


def _registry_ids(s, isins: set[str], house_issuers: list[dict] | None) -> dict[str, str]:
    """ISIN -> the house issuer the company registry names for it (through the company's active UNIVERSE ids), else
    `isin_<ISIN>`: a company outside the house universe keeps the showcase key. One query for every ISIN."""
    if not isins:
        return {}
    isin, universe = m.CompanyIdentifier, aliased(m.CompanyIdentifier)
    keys = {normalise_identifier(m.IdScheme.ISIN, i) for i in isins}
    q = (
        select(isin.value, universe.value)
        .outerjoin(universe, (universe.company_id == isin.company_id) & (universe.scheme == m.IdScheme.UNIVERSE) & universe.valid_to.is_(None))
        .where(isin.scheme == m.IdScheme.ISIN, isin.value.in_(keys), isin.valid_to.is_(None))
    )
    values: dict[str, list[str]] = {}  # an active ISIN names one company (uq_company_identifiers_active)
    for key, value in s.execute(q):
        if value:
            values.setdefault(key, []).append(value)
    house: dict[str, str] = {}
    if values and house_issuers:  # the registry upper-cases UNIVERSE values; issuer ids keep their case
        house = {i["issuer_id"].upper(): i["issuer_id"] for i in house_issuers}
    out = {}
    for i in isins:
        found = values.get(normalise_identifier(m.IdScheme.ISIN, i), ())
        out[i] = next((house[v.upper()] for v in found if v.upper() in house), f"isin_{i}")
    return out
