"""Leaf primitives, geometry constants, and visual registry for the house-deck render model.

Kept separate from `render_model.py` so `arp.reporting.visuals.*` and `render_model.py` form a strict DAG.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from arp.reporting.house_style import Mode, Tokens
from arp.schemas.reporting import Box, Deck, Finding, QuantitativeDataset
from arp.storage.report_images import LoadedImage

# The spacing scale: every gap and padding is one of these.
S4, S8, S12, S16, S24, S32, S40, S48, S64, S96 = 4, 8, 12, 16, 24, 32, 40, 48, 64, 96

MARGIN = S96
CONTENT_W = 1920 - 2 * MARGIN
STRIP_SQUARE = S12
SOURCE_RULE_Y = 952
BODY = Box(x=MARGIN, y=328, w=CONTENT_W, h=592)
FULL_BLEED = {"cover", "section"}


@dataclass(frozen=True)
class Rect:
    name: str
    x: float
    y: float
    w: float
    h: float
    fill: str | None
    line: str | None = None
    line_w: float = 0
    emphasis: bool = False


@dataclass(frozen=True)
class Text:
    name: str
    x: float
    y: float
    w: float
    h: float
    text: str
    size: float
    weight: int
    family: str
    color: str
    align: Literal["left", "center", "right"] = "left"
    anchor: Literal["top", "middle", "bottom"] = "top"
    fill_under: str | None = None
    outline: bool = False
    emphasis: bool = False
    leading: float = 1.2  # line height as a multiple of size


@dataclass(frozen=True)
class Line:
    name: str
    points: list[tuple[float, float]]
    color: str
    width: float
    arrow: bool = False
    emphasis: bool = False
    start: str | None = None  # the primitive this line starts on (a flow arrow's `step:<source>`); the PPTX glues to it
    end: str | None = None  # the primitive it ends on (`step:<target>`)


@dataclass(frozen=True)
class Series:
    name: str
    values: list[float | None]  # None: an empty heatmap cell
    colors: list[str]  # one fill per point (a heatmap's fills come from its values, in vega.heatmap_layers)


@dataclass(frozen=True)
class ChartPrim:
    name: str
    x: float
    y: float
    w: float
    h: float
    kind: str
    categories: list[str]
    series: list[Series]
    unit: str
    labels: bool
    emphasis: bool = False


@dataclass(frozen=True)
class TablePrim:
    name: str
    x: float
    y: float
    w: float
    h: float
    header: list[str]
    rows: list[list[str]]
    total: list[str] | None
    highlight_col: int | None
    style: dict[str, str]
    emphasis: bool = False
    align: list[Literal["left", "right"]] | None = None  # per column; None = all left (numbers go right)
    mono: list[bool] | None = None  # per column: set in the mono face (number columns)


@dataclass(frozen=True)
class ImagePrim:
    """A registered image in a box, cropped to the box's aspect (spec 2026-11-18-house-deck-image-slides, "Crop")."""

    name: str
    x: float
    y: float
    w: float
    h: float
    image: str  # registered name
    media_type: str
    crop: tuple[float, float, float, float]  # left, top, right, bottom, fractions of the source
    alt: str
    emphasis: bool = False


Primitive = Rect | Text | Line | ChartPrim | TablePrim | ImagePrim


def crop(src_w: float, src_h: float, w: float, h: float, focus: tuple[float, float] | None = None) -> tuple[float, float, float, float]:
    """The crop that fills a `w` x `h` slot from a `src_w` x `src_h` source without stretching, centred on `focus`
    (fractions of the source, default the centre) as far as the source allows."""
    fx, fy = focus or (0.5, 0.5)
    if src_w / src_h > w / h:  # too wide: cut the width
        cw = src_h * w / h
        left = min(max(fx * src_w - cw / 2, 0), src_w - cw)
        return left / src_w, 0, (src_w - left - cw) / src_w, 0
    ch = src_w * h / w
    top = min(max(fy * src_h - ch / 2, 0), src_h - ch)
    return 0, top / src_h, 0, (src_h - top - ch) / src_h


@dataclass
class RenderCtx:
    tokens: Tokens
    mode: Mode
    deck: Deck
    index: int
    datasets: dict[str, QuantitativeDataset]
    type_step: int = 0
    findings: list[Finding] = field(default_factory=list)
    images: dict[str, LoadedImage] = field(default_factory=dict)
    cover_image: str | None = None  # the registered image drawn behind the cover (`DeckSettings.cover_image`)


VISUALS: dict[str, Callable[[object, Box, RenderCtx], list[Primitive]]] = {}
"""Visual renderers by `visual.type`, registered by the visual modules."""


def palette(tokens: Tokens, mode: Mode) -> dict[str, str]:
    return tokens.graphite_dark if mode == "dark" else tokens.graphite


def family(stack: str) -> str:
    """The first family of a CSS font stack, unquoted."""
    return stack.split(",")[0].strip().strip("'\"")


def body_box(tokens: Tokens) -> Box:
    return tokens.frame.body if tokens.frame else BODY


class VisualDataError(ValueError):
    """A visual's data reference does not resolve: unknown dataset or column, or a non-numeric value column."""


CHART_LABEL = 24  # chart label size, px (the PPTX chart font)


def value_range(p: ChartPrim) -> tuple[float, float]:
    """A bar or column chart's value axis, zero always in range (stacks by their totals); both writers use it."""
    if p.kind == "waterfall":
        tops = lows = [v for ab in waterfall_bars(p) for v in ab]
    elif p.kind == "stacked_column":
        tops = [sum(max(s.values[i], 0) for s in p.series) for i in range(len(p.categories))]
        lows = [sum(min(s.values[i], 0) for s in p.series) for i in range(len(p.categories))]
    else:
        tops = lows = [v for s in p.series for v in s.values]
    lo, hi = min(0, *lows), max(0, *tops)
    return lo, hi if hi > lo else lo + 1


def waterfall_bars(p: ChartPrim) -> list[tuple[float, float]]:
    """A component waterfall's bars as (from, to) on the value scale: the first and last rows are totals from 0, each
    row between a signed change from the running total before it to the one after it. Both writers use it."""
    values = p.series[0].values
    out, run = [(0.0, values[0])], values[0]
    for v in values[1:-1]:
        out.append((run, run + v))
        run += v
    return [*out, (0.0, values[-1])]


def bar_label_width(p: ChartPrim) -> float:
    """Width left of a bar chart's bars for its right-aligned category labels."""
    return min(0.3 * p.w, 240)


def bar_plot_x(p: ChartPrim) -> tuple[float, float]:
    """A bar chart's plot area, left and right, inside its box (value labels sit right of the bars)."""
    return bar_label_width(p) + S16, p.w - (96 if p.labels else 0)


def column_plot_y(p: ChartPrim) -> tuple[float, float]:
    """A column chart's plot area, top and bottom, inside its box (value labels above, category labels below)."""
    return (32 if p.labels else 0), p.h - 40


LINE_PAD = (S32, 240, 56)  # top, right (series labels at the line ends), bottom (category labels) inside a line chart's box


def line_scale(p: ChartPrim) -> tuple[float, float]:
    """A line chart's value range: min to max with 10% headroom, so a flat-ish series is not squashed against zero."""
    values = [v for s in p.series for v in s.values]
    lo, hi = min(values), max(values)
    pad = (hi - lo) * 0.1 or 1
    return lo - pad, hi + pad


def line_point(p: ChartPrim, i: int, v: float) -> tuple[float, float]:
    """Canvas position of category `i` at value `v` on a line chart; both writers and the callout use it."""
    top, right, bottom = LINE_PAD
    lo, hi = line_scale(p)
    return p.x + (i + 0.5) * (p.w - right) / len(p.categories), p.y + top + (hi - v) / (hi - lo) * (p.h - top - bottom)


def decimals(values: list[float]) -> int:
    """Decimal places the values carry; chart labels and number formats keep them."""
    return max((len(f"{v:g}".partition(".")[2]) for v in values), default=0)
