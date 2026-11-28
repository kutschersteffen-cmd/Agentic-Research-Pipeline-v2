from __future__ import annotations

from arp.config import get_settings
from arp.db.session import require_dsn
from arp.schemas.transition_barrier import (
    BarrierScore,
    Pillar,
    Region,
    RegistrySource,
)
from arp.storage.run_store import RunStore
from arp.transition_data.data_files import (  # noqa: F401
    check_rule_book,
    data_dir,
    load_criteria,
    load_scores,
    load_source_registry,
    reset_caches,
)


def current_scores() -> list[BarrierScore]:
    """The 105 cells as they stand now: the bundled rating, or the ratified result that replaced it, with flags.

    Read on every call so a new approval shows without a restart. Without a database there are no ratified results.
    """
    settings = get_settings()
    if not settings.postgres_dsn:
        return load_scores()
    from arp.transition_barrier.ratings import Ratings  # ratings imports this module

    book = Ratings(RunStore(require_dsn(settings), settings.runs_dir))
    return [
        BarrierScore.model_validate(book.cell(s.code, s.region.value).model_dump(exclude={"result", "ratified_at"}))
        for s in load_scores()
    ]


def sources_for_criterion(code: str) -> list[RegistrySource]:
    """Resolve the criterion -> source join. criteria_schema.json is
    authoritative for *which* sources back a criterion; the registry is used
    only to return the deduplicated record for each.
    """
    return [s for s in load_source_registry() if code in s.used_by_criteria]


def filter_scores(
    *,
    sector: str | None = None,
    region: Region | None = None,
    pillar: Pillar | None = None,
    rating: str | None = None,
    code: str | None = None,
) -> list[BarrierScore]:
    """Filter the 105 cells. Every argument is optional and ANDed together."""
    rows = current_scores()
    if sector:
        rows = [r for r in rows if r.sector == sector]
    if region:
        rows = [r for r in rows if r.region is region]
    if pillar:
        rows = [r for r in rows if r.category is pillar]
    if rating:
        rows = [r for r in rows if r.rating.value == rating]
    if code:
        rows = [r for r in rows if r.code == code]
    return rows


def build_matrix(scores: list[BarrierScore] | None = None) -> dict[str, dict[str, BarrierScore]]:
    """The 35x3 grid as {criterion_code: {region: score}} -- the shape the
    frontend heatmap consumes. `scores`: current_scores() the caller already read.
    """
    grid: dict[str, dict[str, BarrierScore]] = {}
    for score in current_scores() if scores is None else scores:
        grid.setdefault(score.code, {})[score.region.value] = score
    return grid


def rating_distribution(region: Region | None = None, scores: list[BarrierScore] | None = None) -> dict[str, int]:
    """H/M/L counts, optionally for one region. Always returns all three keys so
    a zero count is visible rather than missing. `scores`: current_scores() the caller already read.
    """
    counts = {"H": 0, "M": 0, "L": 0}
    for score in current_scores() if scores is None else scores:
        if region is None or score.region is region:
            counts[score.rating.value] += 1
    return counts


def sectors() -> list[str]:
    """The 9 sectors, in the order they appear in the criteria schema."""
    seen: list[str] = []
    for criterion in load_criteria():
        if criterion.sector not in seen:
            seen.append(criterion.sector)
    return seen
