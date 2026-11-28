"""Shared chart data/styling helpers, dataset summaries, and ReportPlan -> Deck adapter."""

from __future__ import annotations

from arp.errors import ClientInputError
from arp.reporting.design import DesignTheme, categorical_color
from arp.schemas.reporting import (
    ChartSpec,
    ChartType,
    Deck,
    QuantitativeDataset,
    ReportPlan,
    SectionLayoutHint,
    SlideContent,
)

try:
    from pptx.chart.data import CategoryChartData, XyChartData
    from pptx.dml.color import RGBColor
    from pptx.enum.chart import XL_CHART_TYPE, XL_LEGEND_POSITION
    from pptx.util import Pt

    _XL_CHART_TYPE = {
        ChartType.BAR: XL_CHART_TYPE.BAR_CLUSTERED,
        ChartType.COLUMN: XL_CHART_TYPE.COLUMN_CLUSTERED,
        ChartType.STACKED_COLUMN: XL_CHART_TYPE.COLUMN_STACKED,
        ChartType.LINE: XL_CHART_TYPE.LINE_MARKERS,
        ChartType.AREA: XL_CHART_TYPE.AREA,
        ChartType.PIE: XL_CHART_TYPE.PIE,
        ChartType.DOUGHNUT: XL_CHART_TYPE.DOUGHNUT,
        ChartType.RADAR: XL_CHART_TYPE.RADAR_MARKERS,
    }
except ImportError:  # optional extra: arp[reporting]
    CategoryChartData = XyChartData = RGBColor = XL_CHART_TYPE = XL_LEGEND_POSITION = Pt = None  # type: ignore[assignment]
    _XL_CHART_TYPE = {}

_NATIVE_CHART_TYPES = {
    ChartType.BAR,
    ChartType.COLUMN,
    ChartType.STACKED_COLUMN,
    ChartType.LINE,
    ChartType.AREA,
    ChartType.PIE,
    ChartType.DOUGHNUT,
    ChartType.RADAR,
}
_PIE_TYPES = {ChartType.PIE, ChartType.DOUGHNUT}


class ChartDataError(ClientInputError):
    """The ChartSpec references a column/dataset that doesn't actually
    exist, or references a chart shape the data doesn't support -- always a
    bug in the plan (LLM-authored or hand-edited), never a rendering
    failure to hide from the caller."""


def _dataset_by_id(datasets: list[QuantitativeDataset], dataset_id: str) -> QuantitativeDataset:
    for ds in datasets:
        if ds.dataset_id == dataset_id:
            return ds
    raise ChartDataError(f"Chart references unknown dataset_id {dataset_id!r}")


def _column(ds: QuantitativeDataset, name: str | None, *, label: str) -> str:
    if not name:
        raise ChartDataError(f"Chart on dataset {ds.dataset_id!r} is missing required column reference: {label}")
    if name not in ds.column_names():
        raise ChartDataError(f"Column {name!r} ({label}) not found in dataset {ds.dataset_id!r} (has: {ds.column_names()})")
    return name


def _as_float_or_zero(value: object) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def is_native(spec: ChartSpec) -> bool:
    return spec.chart_type in _NATIVE_CHART_TYPES


def _build_scatter_data(spec: ChartSpec, ds: QuantitativeDataset) -> tuple[XL_CHART_TYPE, XyChartData]:
    x_col = _column(ds, spec.x_column, label="x_column")
    if not spec.value_columns:
        raise ChartDataError("Scatter chart needs at least one value_columns entry for the y series.")
    xy_data = XyChartData()
    for y_col in spec.value_columns:
        col_name = _column(ds, y_col, label="value_columns")
        series = xy_data.add_series(col_name)
        for row in ds.rows:
            x_val, y_val = row.get(x_col), row.get(col_name)
            if x_val is None or y_val is None:
                continue
            series.add_data_point(float(x_val), float(y_val))
    return XL_CHART_TYPE.XY_SCATTER, xy_data


def build_native_chart_data(
    spec: ChartSpec, datasets: list[QuantitativeDataset],
) -> tuple[XL_CHART_TYPE, CategoryChartData | XyChartData]:
    """Builds python-pptx CategoryChartData/XyChartData for chart types
    PowerPoint can render natively as editable Office chart objects."""
    ds = _dataset_by_id(datasets, spec.dataset_id)
    if spec.chart_type == ChartType.SCATTER:
        return _build_scatter_data(spec, ds)

    category_col = _column(ds, spec.category_column, label="category_column")
    if not spec.value_columns:
        raise ChartDataError("Chart needs at least one value_columns entry.")
    value_cols = [_column(ds, c, label="value_columns") for c in spec.value_columns]

    chart_data = CategoryChartData()
    chart_data.categories = [str(row.get(category_col, "")) for row in ds.rows]
    for col in value_cols:
        chart_data.add_series(col, [_as_float_or_zero(row.get(col)) for row in ds.rows])
    return _XL_CHART_TYPE[spec.chart_type], chart_data


def _style_pie_series(plot, series_list: list, theme: DesignTheme, size) -> None:
    for i, point in enumerate(series_list[0].points if series_list else []):
        point.format.fill.solid()
        point.format.fill.fore_color.rgb = RGBColor.from_string(categorical_color(theme, i))
    plot.has_data_labels = True
    plot.data_labels.show_percentage = True
    plot.data_labels.show_category_name = True
    plot.data_labels.show_value = False
    plot.data_labels.font.size = size(11)
    plot.data_labels.font.color.rgb = RGBColor.from_string(theme.ink_primary)


def _style_cartesian_series(series_list: list, spec: ChartSpec, theme: DesignTheme) -> None:
    for i, series in enumerate(series_list):
        color = RGBColor.from_string(categorical_color(theme, i))
        if spec.chart_type == ChartType.LINE:
            series.format.line.color.rgb = color
            series.format.line.width = Pt(2.25)
            series.marker.format.fill.solid()
            series.marker.format.fill.fore_color.rgb = color
        else:
            series.format.fill.solid()
            series.format.fill.fore_color.rgb = color


def _style_axes(plot, theme: DesignTheme, size) -> None:
    for axis in (plot.chart.category_axis, plot.chart.value_axis):
        axis.format.line.color.rgb = RGBColor.from_string(theme.gridline)
        axis.tick_labels.font.size = size(10)
        axis.tick_labels.font.color.rgb = RGBColor.from_string(theme.ink_muted)
    value_axis = plot.chart.value_axis
    if value_axis.has_major_gridlines:
        value_axis.major_gridlines.format.line.color.rgb = RGBColor.from_string(theme.gridline)
        value_axis.major_gridlines.format.line.width = Pt(0.5)


def style_native_chart(chart, spec: ChartSpec, theme: DesignTheme, min_pt: float = 0) -> None:
    """Applies the design theme to a native python-pptx chart."""
    size = lambda pt: Pt(max(pt, min_pt))  # noqa: E731 -- min_pt lifts text for projector decks
    plot = chart.plots[0]
    is_pie = spec.chart_type in _PIE_TYPES
    series_list = list(plot.series)

    if is_pie:
        _style_pie_series(plot, series_list, theme, size)
    else:
        _style_cartesian_series(series_list, spec, theme)

    chart.has_legend = (not is_pie) and len(series_list) > 1
    if chart.has_legend:
        chart.legend.position = XL_LEGEND_POSITION.BOTTOM
        chart.legend.include_in_layout = False
        chart.legend.font.size = size(11)
        chart.legend.font.color.rgb = RGBColor.from_string(theme.ink_secondary)

    if spec.title:
        chart.chart_title.text_frame.paragraphs[0].font.size = size(14)
        chart.chart_title.text_frame.paragraphs[0].font.bold = True
        chart.chart_title.text_frame.paragraphs[0].font.color.rgb = RGBColor.from_string(theme.ink_primary)

    if not is_pie:
        _style_axes(plot, theme, size)


def datasets_context(datasets: list[QuantitativeDataset]) -> str:
    """Compact text summary of supplied quantitative datasets for LLM prompts."""
    if not datasets:
        return "(no quantitative datasets supplied)"
    return "\n\n".join(ds.summary() for ds in datasets)


def deck_from_plan(plan: ReportPlan) -> Deck:
    """ReportPlan -> Deck, so hand-built plans (e.g. stewardship reports) render through the house deck."""
    slides = [SlideContent(headline=plan.title, layout="title", variant="plain", slots={"title": plan.title, "subtitle": plan.subtitle})]
    for sec in plan.sections:
        texts = [c.text for c in sec.narrative]
        base = {"headline": sec.heading, "speaker_notes": sec.speaker_notes}
        if sec.layout_hint == SectionLayoutHint.SECTION_HEADER:
            slides.append(SlideContent(**base, layout="section", variant="default", slots={"title": sec.heading, "subtitle": texts[0] if texts else ""}))
        elif sec.layout_hint == SectionLayoutHint.TEXT_ONLY:
            slides.append(SlideContent(**base, layout="bullets", variant="five", slots={"items": texts}))
        elif sec.layout_hint == SectionLayoutHint.CHART_FOCUS or sec.chart:
            variant = "full" if sec.layout_hint == SectionLayoutHint.CHART_FOCUS else "chart_left"
            takeaway = (sec.chart.notes if sec.chart else "") or (texts[0] if texts else "")
            slides.append(SlideContent(**base, layout="chart_takeaway", variant=variant, slots={"takeaway": takeaway}, chart=sec.chart))
        elif sec.table:
            slides.append(SlideContent(**base, layout="table", variant="compact", table=sec.table))
        else:
            slides.append(SlideContent(**base, layout="bullets", variant="five", slots={"items": texts}))
    return Deck(title=plan.title, subtitle=plan.subtitle, slides=slides)


__all__ = [
    "ChartDataError",
    "build_native_chart_data",
    "datasets_context",
    "deck_from_plan",
    "is_native",
    "style_native_chart",
]
