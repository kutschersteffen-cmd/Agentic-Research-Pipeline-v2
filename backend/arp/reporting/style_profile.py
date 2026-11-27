from __future__ import annotations

import shutil
from pathlib import Path

from lxml import etree
from pptx import Presentation

from arp.reporting.template_frame import _A_NS, _theme_fonts, _theme_xml, extract_frame, font_family_of
from arp.schemas.reporting import TemplateLayoutInfo, TemplateStyleProfile
from arp.storage.reporting_store import ReportingStore

# Maps python-pptx's placeholder type enum names to short, stable labels
# used in TemplateStyleProfile.layouts[].placeholder_types -- the Content
# Planner only needs to know a layout *has* a title/body/chart/picture slot,
# not python-pptx's internal enum values.
_PLACEHOLDER_LABELS = {
    "TITLE": "title",
    "CENTER_TITLE": "title",
    "SUBTITLE": "subtitle",
    "BODY": "body",
    "OBJECT": "object",
    "PICTURE": "picture",
    "CHART": "chart",
    "TABLE": "table",
    "DATE": "date",
    "FOOTER": "footer",
    "SLIDE_NUMBER": "slide_number",
}


def _theme_colors(prs: Presentation) -> dict[str, str]:
    """Reads the 12 named theme colors (dk1/lt1/dk2/lt2/accent1-6/hlink/
    folHlink) straight from the template's theme XML -- the same palette
    PowerPoint itself offers when a user picks "Theme Colors" for any
    shape, so charts/text built against these hex values visually match
    the template without guessing at screenshots or embedding a whole
    separate palette.
    """
    colors: dict[str, str] = {}
    theme_elm = _theme_xml(prs)
    if theme_elm is None:
        return colors
    scheme = theme_elm.find(".//a:clrScheme", _A_NS)
    if scheme is None:
        return colors
    for child in scheme:
        tag = etree.QName(child.tag).localname
        srgb = child.find("a:srgbClr", _A_NS)
        if srgb is not None and srgb.get("val"):
            colors[tag] = srgb.get("val").upper()
        else:
            sys_clr = child.find("a:sysClr", _A_NS)
            if sys_clr is not None and sys_clr.get("lastClr"):
                colors[tag] = sys_clr.get("lastClr").upper()
    return colors


def extract_style_profile(pptx_path: Path, source_filename: str) -> TemplateStyleProfile:
    """Deterministically inspects an uploaded .pptx template -- slide
    dimensions, every slide layout's name and placeholder types, theme
    colors, and theme fonts. Nothing here is LLM-inferred: this is exactly
    the metadata DeckBuilder needs to build new slides that visually match
    the template, read straight from the OOXML the same way PowerPoint
    itself would.
    """
    prs = Presentation(str(pptx_path))
    layouts = []
    for idx, layout in enumerate(prs.slide_layouts):
        placeholder_types = []
        for ph in layout.placeholders:
            try:
                label = _PLACEHOLDER_LABELS.get(ph.placeholder_format.type.name, ph.placeholder_format.type.name.lower())
            except (AttributeError, ValueError):
                label = "unknown"
            placeholder_types.append(label)
        layouts.append(TemplateLayoutInfo(index=idx, name=layout.name, placeholder_types=placeholder_types))

    major_font, minor_font = _theme_fonts(prs)
    return TemplateStyleProfile(
        source_filename=source_filename,
        slide_width_emu=prs.slide_width,
        slide_height_emu=prs.slide_height,
        layouts=layouts,
        theme_colors=_theme_colors(prs),
        major_font=major_font,
        minor_font=minor_font,
        stored_path="",  # filled in by ingest_template once the file is saved
    )


def ingest_template(
    store: ReportingStore, source_path: Path, source_filename: str, fonts: list[tuple[str, Path]] = (), layout_name: str | None = None,
) -> TemplateStyleProfile:
    """Extracts the style profile, then copies the original template file
    into the store keyed by the new template_id -- DeckBuilder clones this
    exact file as its render base, so every downstream slide inherits its
    masters/layouts/theme byte-for-byte rather than an approximation.
    """
    style = extract_style_profile(source_path, source_filename)
    dest = store.template_source_path(style.template_id, "original.pptx")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, dest)
    style.stored_path = str(dest)
    if fonts:
        font_dir = store.template_font_dir(style.template_id)
        font_dir.mkdir(exist_ok=True)
        for name, path in fonts:
            shutil.copyfile(path, font_dir / name)
        style.font_dir = str(font_dir)
    style.frame, style.frame_error = extract_frame(
        Presentation(str(source_path)), layout_name, {f for name, _ in fonts if (f := font_family_of(name))},
    )
    store.save_template_style(style)
    return style
