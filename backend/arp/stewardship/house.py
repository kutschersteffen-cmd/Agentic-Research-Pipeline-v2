"""House stewardship universe loader (no vote/alert feed dependency, breaking any cycle)."""

from __future__ import annotations

import json

from arp.stewardship import universe
from arp.stewardship.universe import (
    HouseBuild,
    HouseUniverseSetting,
    copy_build,
    from_portfolio,
    kept_build,
    latest_observations,
)


def house_build() -> HouseBuild:
    """The issuers the house program covers: portfolio holdings (default) or the synthetic sample."""
    from arp.config import get_settings

    settings = get_settings()

    def build() -> HouseBuild:
        from arp.storage.portfolio_store_factory import build_portfolio_store

        if HouseUniverseSetting(settings.stewardship_streams_dir).get()["source"] == "sample":
            return HouseBuild(json.loads(universe.SAMPLE_PATH.read_text()), {}, None)
        store = build_portfolio_store(settings)
        observations, held = latest_observations(store), {}
        return HouseBuild(from_portfolio(store, observations=observations, held_isins_out=held), held, observations)

    return copy_build(kept_build(settings, build))


def house_universe() -> dict:
    """`house_build().universe`."""
    return house_build().universe


def house_isins() -> dict[str, str]:
    """ISIN -> house issuer id for the portfolio universe; empty for the sample, whose issuers have no ISINs."""
    return house_build().held
