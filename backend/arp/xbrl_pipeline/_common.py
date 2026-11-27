"""Shared retry/rate-limit and status-row helpers for SEC and ESEF XBRL fetchers."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

import httpx

from arp.xbrl_pipeline.models import CompanyStatus

T = TypeVar("T")
FETCH_DELAY_SECONDS = 0.15


def _retryable(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, httpx.TransportError)


async def with_retry(
    call: Callable[[], Awaitable[T]], *, attempts: int = 3, base_delay: float = 1.0, sleep=asyncio.sleep
) -> T:
    for attempt in range(attempts):
        try:
            return await call()
        except Exception as exc:  # noqa: BLE001 -- re-raised unless retryable
            if not _retryable(exc) or attempt == attempts - 1:
                raise
            await sleep(base_delay * 2**attempt)
    raise AssertionError("unreachable")


def _status(
    company_id: str,
    st: str,
    key: str | None = None,
    sha: str | None = None,
    n: int = 0,
    report: str = "none",
    market: str = "sec",
) -> CompanyStatus:
    return CompanyStatus(
        company_id=company_id,
        cik=key,
        status=st,
        source_sha=sha,
        fact_count=n,
        report=report,
        market=market,
    )
