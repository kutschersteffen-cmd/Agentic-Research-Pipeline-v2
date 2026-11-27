"""House-deck render model: a slide becomes a flat list of positioned primitives in canvas px.

Both writers (HTML and PPTX) draw from the same list, so the two outputs match box for box.
Spec: docs/superpowers/specs/2026-11-15-slide-components-design.md, "Canvas, zones and spacing" and "Render model".
"""

from __future__ import annotations

from arp.reporting import visuals  # noqa: F401 - registers the visual renderers (strict DAG via primitives)
from arp.reporting.house_style import Mode, Tokens, footer_fits
from arp.reporting.primitives import (
    BODY,
    CHART_LABEL,
    CONTENT_W,
    FULL_BLEED,
    LINE_PAD,
    MARGIN,
    S4,
    S8,
    S12,
    S16,
    S24,
    S32,
    S40,
    S48,
    S64,
    S96,
    SOURCE_RULE_Y,
    STRIP_SQUARE,
    VISUALS,
    ChartPrim,
    ImagePrim,
    Line,
    Primitive,
    Rect,
    RenderCtx,
    Series,
    TablePrim,
    Text,
    VisualDataError,
    bar_label_width,
    bar_plot_x,
    body_box,
    column_plot_y,
    crop,
    decimals,
    family,
    line_point,
    line_scale,
    palette,
    value_range,
    waterfall_bars,
)
from arp.schemas.reporting import Box, Deck, Finding, QuantitativeDataset, SlideContent
from arp.storage.report_images import LoadedImage

__all__ = [
    "BODY",
    "CHART_LABEL",
    "CONTENT_W",
    "FULL_BLEED",
    "LINE_PAD",
    "MARGIN",
    "S4",
    "S8",
    "S12",
    "S16",
    "S24",
    "S32",
    "S40",
    "S48",
    "S64",
    "S96",
    "SOURCE_RULE_Y",
    "STRIP_SQUARE",
    "VISUALS",
    "ChartPrim",
    "ImagePrim",
    "Line",
    "Primitive",
    "Rect",
    "RenderCtx",
    "Series",
    "TablePrim",
    "Text",
    "VisualDataError",
    "anatomy",
    "bar_label_width",
    "bar_plot_x",
    "body_box",
    "column_plot_y",
    "crop",
    "decimals",
    "family",
    "line_point",
    "line_scale",
    "palette",
    "render_slide",
    "source_line",
    "value_range",
    "waterfall_bars",
]


def source_line(slide: SlideContent, datasets: dict[str, QuantitativeDataset]) -> str:
    """`Source: ` and the cited items joined by `; `: dataset names (with `, rows a–b` for a table slice), other refs as written."""
    visual = slide.visual
    table = visual.table if visual is not None and visual.type == "comparison_table" else slide.table
    items = []
    for ref in slide.source_refs:
        ds = datasets.get(ref)
        if ds is None:
            items.append(ref)
            continue
        item = ds.name
        if table is not None and table.dataset_id == ref:
            first, last = table.row_offset, min(table.row_offset + table.max_rows, len(ds.rows))
            if first > 0 or last < len(ds.rows):
                item += f", rows {first + 1}–{last}"
        items.append(item)
    return "Source: " + "; ".join(items) if items else ""


def anatomy(slide: SlideContent, index: int, tokens: Tokens, mode: Mode) -> list[Primitive]:
    """Strip, kicker, title, subtitle, source rule and text, page number. Under a frame, title and subtitle take its
    boxes and the strip sits 40 px above the headline box; the source zone is left out when the frame body reaches below
    y 928 (the writers then append `slide.source_line` to the notes, see `footer_fits`)."""
    c, f = palette(tokens, mode), tokens.frame
    heading = family(tokens.fonts.heading_dark if mode == "dark" and tokens.fonts.heading_dark else tokens.fonts.heading)
    body = family(tokens.fonts.body)
    mono = family(tokens.fonts.mono or tokens.fonts.body)
    if f is None:
        title = Text("title", MARGIN, 104, CONTENT_W, 128, slide.headline, 56, 600, heading, c["ink"],
                     leading=tokens.type["headline"].line_height)  # 1.12: two lines fit the 128 px band, 1.2 did not
        subtitle = Text("subtitle", MARGIN, 248, CONTENT_W, 40, slide.subheading, 28, 400, body, c["muted"])
    else:
        h, s = f.headline, f.subheading
        title = Text("title", h.x, h.y, h.w, h.h, slide.headline, f.headline_font.size_px,
                     700 if f.headline_font.bold else 400, family(f.headline_font.family), c["ink"])
        subtitle = Text("subtitle", s.x, s.y, s.w, s.h, slide.subheading, f.subheading_font.size_px,
                        700 if f.subheading_font.bold else 400, family(f.subheading_font.family), c["muted"])
    left, top = title.x, title.y - S40
    out: list[Primitive] = [
        Rect(f"strip:{i}", left + (i - 1) * (STRIP_SQUARE + S4), top, STRIP_SQUARE, STRIP_SQUARE, c["highlight" if i == 3 else "ink"])
        for i in range(1, 6)
    ]
    kicker_x = left + 5 * STRIP_SQUARE + 4 * S4 + S16
    out += [
        Text("kicker", kicker_x, top, title.x + title.w - kicker_x, S24, slide.kicker.upper(), 20, 400, mono, c["muted"]),
        title,
        subtitle,
    ]
    if footer_fits(tokens):
        text_y = SOURCE_RULE_Y + S16
        out += [
            Line("source:rule", [(MARGIN, SOURCE_RULE_Y), (MARGIN + CONTENT_W, SOURCE_RULE_Y)], c["line"], 1),
            Text("source", MARGIN, text_y, CONTENT_W - S96, S24, slide.source_line, 18, 400, mono, c["muted"]),
            Text("page", MARGIN + CONTENT_W - S96, text_y, S96, S24, str(index + 1), 18, 400, mono, c["muted"], align="right"),
        ]
    return out


def render_slide(slide: SlideContent, index: int, deck: Deck, tokens: Tokens, datasets: dict[str, QuantitativeDataset],
                 mode: Mode = "light", findings: list[Finding] | None = None, *,
                 images: dict[str, LoadedImage] | None = None, cover_image: str | None = None) -> list[Primitive]:
    """The slide's primitives: anatomy plus its visual in the body box; cover and section are full-bleed.
    `findings`, when given, collects what the visual renderer found (a capped chart, a clipped category label).
    `images` holds the report's registered images by name; an image visual naming one missing from it is a VisualDataError.
    `cover_image` names the registered image drawn behind a `cover` visual."""
    ctx = RenderCtx(tokens, mode, deck, index, datasets, slide.type_step, findings if findings is not None else [], images or {},
                    cover_image)
    visual = slide.visual
    if visual.type in FULL_BLEED:
        return VISUALS[visual.type](visual, Box(x=0, y=0, w=tokens.canvas.width, h=tokens.canvas.height), ctx)
    slide = slide.model_copy(update={"source_line": source_line(slide, datasets)})
    return anatomy(slide, index, tokens, mode) + VISUALS[visual.type](visual, body_box(tokens), ctx)
