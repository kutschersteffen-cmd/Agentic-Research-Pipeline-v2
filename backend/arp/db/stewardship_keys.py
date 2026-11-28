"""Stewardship company and meeting key helpers shared by `postgres_schema` and `stewardship.intake`."""

from __future__ import annotations

from arp.core.safe_path import UnsafeIdentifierError, safe_id
from arp.db.company_view import resolve_ref
from arp.db.postgres_models import StwCompanyModel


def _safe(key: str) -> bool:
    try:
        safe_id(key, label="company_id")
    except UnsafeIdentifierError:
        return False
    return True


def _company(s, company_id: str | None, isin: str | None) -> str | None:
    """The stewardship company key this row names: `company_id`, else the normalised ISIN, if a stw_companies
    row or the registry knows it."""
    if company_id and _safe(company_id) and (s.get(StwCompanyModel, company_id) or resolve_ref(s, f"UNIVERSE:{company_id}")):
        return company_id
    if isin:
        isin = "".join(isin.split()).upper()
        key = f"isin_{isin}"
        if _safe(key) and (s.get(StwCompanyModel, key) or resolve_ref(s, f"ISIN:{isin}")):
            return key
    return None


def meeting_key(company_id: str | None, isin: str | None, cusip: str | None) -> str:
    """The listing part of a vote meeting's key: `isin`, else `cusip`, else the company id, one namespace each, so two
    listings of one company (share and ADR) are two meetings (owner, 15 Nov 2026). A company keyed `isin_<ISIN>`
    shares the `isin:` namespace with ISIN-only rows, so both reach one meeting."""
    if not isin and company_id and company_id.startswith("isin_"):
        isin = company_id[5:].upper()
    return next(f"{ns}:{v}" for ns, v in (("isin", isin), ("cusip", cusip), ("cid", company_id)) if v)
