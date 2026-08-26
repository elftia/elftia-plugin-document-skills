"""Bounded styles, numbering, theme, and direct-formatting projection."""

from typing import Any

from .constants import local_name, qn
from .mapping import Story, iter_paragraphs
from .package import OpcPackage
from .style_profiles import identify_style_profile


def project_formatting(package: OpcPackage, stories: list[Story]) -> dict[str, Any]:
    styles, styles_truncated = _styles(package)
    numbering, numbering_truncated = _numbering(package)
    direct = _direct_formatting(stories)
    contaminated = direct["paragraph_count"] > 0 or direct["run_count"] > 0
    return {
        "styles": styles,
        "styles_truncated": styles_truncated,
        "style_profile": identify_style_profile(
            package.parts.get("word/styles.xml", b"")
        ),
        "numbering": numbering,
        "numbering_truncated": numbering_truncated,
        "theme": _theme(package),
        "direct_formatting": direct,
        "normalization_report": {
            "status": "review_required" if contaminated else "clean",
            "automatic_changes_applied": False,
            "recommendation": (
                "Review direct formatting against named styles before normalization."
                if contaminated
                else None
            ),
        },
    }


def _styles(package: OpcPackage) -> tuple[list[dict[str, Any]], bool]:
    part = "word/styles.xml"
    if part not in package.parts:
        return [], False
    result = []
    for style in package.xml(part).findall(qn("w", "style")):
        if len(result) >= 1_000:
            return result, True
        result.append(
            {
                "id": style.attrib.get(qn("w", "styleId")),
                "type": style.attrib.get(qn("w", "type")),
                "custom": style.attrib.get(qn("w", "customStyle")) in {"1", "true"},
                "default": style.attrib.get(qn("w", "default")) in {"1", "true"},
                "name": _value(style, "name"),
                "based_on": _value(style, "basedOn"),
                "next": _value(style, "next"),
                "linked": _value(style, "link"),
                "paragraph_format": _paragraph_format(style),
                "run_format": _run_format(style),
            }
        )
    return result, False


def _numbering(package: OpcPackage) -> tuple[dict[str, Any], bool]:
    part = "word/numbering.xml"
    if part not in package.parts:
        return {"abstract_definitions": [], "instances": []}, False
    root = package.xml(part)
    abstract = []
    instances = []
    truncated = False
    for node in root.findall(qn("w", "abstractNum")):
        if len(abstract) >= 1_000:
            truncated = True
            break
        levels = sorted(
            int(value)
            for level in node.findall(qn("w", "lvl"))
            if (value := level.attrib.get(qn("w", "ilvl"), "")).isdigit()
        )
        abstract.append(
            {
                "id": node.attrib.get(qn("w", "abstractNumId")),
                "levels": levels,
            }
        )
    for node in root.findall(qn("w", "num")):
        if len(instances) >= 1_000:
            truncated = True
            break
        instances.append(
            {
                "num_id": node.attrib.get(qn("w", "numId")),
                "abstract_num_id": _value(node, "abstractNumId"),
            }
        )
    return {"abstract_definitions": abstract, "instances": instances}, truncated


def _theme(package: OpcPackage) -> dict[str, Any] | None:
    part = "word/theme/theme1.xml"
    if part not in package.parts:
        return None
    root = package.xml(part)
    major = next(root.iter(qn("a", "majorFont")), None)
    minor = next(root.iter(qn("a", "minorFont")), None)
    scheme = next(root.iter(qn("a", "clrScheme")), None)
    colors = []
    if scheme is not None:
        for color in list(scheme)[:32]:
            child = next(iter(color), None)
            if child is not None:
                colors.append(
                    {
                        "slot": local_name(color.tag),
                        "type": local_name(child.tag),
                        "value": child.attrib.get("val") or child.attrib.get("lastClr"),
                    }
                )
    return {
        "major_latin": _latin_typeface(major),
        "minor_latin": _latin_typeface(minor),
        "colors": colors,
    }


def _direct_formatting(stories: list[Story]) -> dict[str, Any]:
    paragraphs = []
    runs = []
    for story in stories:
        for paragraph_index, paragraph in enumerate(iter_paragraphs(story.root)):
            properties = paragraph.find(qn("w", "pPr"))
            paragraph_properties = (
                sorted(
                    local_name(child.tag)
                    for child in properties
                    if local_name(child.tag) not in {"numPr", "pStyle", "sectPr"}
                )
                if properties is not None
                else []
            )
            if paragraph_properties and len(paragraphs) < 1_000:
                paragraphs.append(
                    {
                        "story": story.kind,
                        "part": story.part,
                        "paragraph_index": paragraph_index,
                        "properties": paragraph_properties,
                    }
                )
            for run_index, run in enumerate(paragraph.iter(qn("w", "r"))):
                run_properties = run.find(qn("w", "rPr"))
                names = (
                    sorted(
                        local_name(child.tag)
                        for child in run_properties
                        if local_name(child.tag) != "rStyle"
                    )
                    if run_properties is not None
                    else []
                )
                if names and len(runs) < 2_000:
                    runs.append(
                        {
                            "story": story.kind,
                            "part": story.part,
                            "paragraph_index": paragraph_index,
                            "run_index": run_index,
                            "properties": names,
                        }
                    )
    return {
        "paragraph_count": len(paragraphs),
        "run_count": len(runs),
        "paragraphs": paragraphs,
        "runs": runs,
        "truncated": len(paragraphs) >= 1_000 or len(runs) >= 2_000,
    }


def _value(parent, name: str) -> str | None:
    node = parent.find(qn("w", name))
    return node.attrib.get(qn("w", "val")) if node is not None else None


def _paragraph_format(style) -> dict[str, Any]:
    properties = style.find(qn("w", "pPr"))
    if properties is None:
        return {}
    result: dict[str, Any] = {}
    alignment = properties.find(qn("w", "jc"))
    if alignment is not None:
        result["alignment"] = alignment.attrib.get(qn("w", "val"))
    if properties.find(qn("w", "keepNext")) is not None:
        result["keep_with_next"] = True
    if properties.find(qn("w", "keepLines")) is not None:
        result["keep_lines"] = True
    spacing = properties.find(qn("w", "spacing"))
    if spacing is not None:
        for attribute, key in (
            ("before", "space_before_twips"),
            ("after", "space_after_twips"),
            ("line", "line_twips"),
        ):
            value = spacing.attrib.get(qn("w", attribute))
            if value is not None and value.isdigit():
                result[key] = int(value)
        line_rule = spacing.attrib.get(qn("w", "lineRule"))
        if line_rule is not None:
            result["line_rule"] = line_rule
    return result


def _run_format(style) -> dict[str, Any]:
    properties = style.find(qn("w", "rPr"))
    if properties is None:
        return {}
    result: dict[str, Any] = {}
    fonts = properties.find(qn("w", "rFonts"))
    if fonts is not None:
        ascii_font = fonts.attrib.get(qn("w", "ascii"))
        east_asia = fonts.attrib.get(qn("w", "eastAsia"))
        if ascii_font is not None:
            result["font_ascii"] = ascii_font
        if east_asia is not None:
            result["font_east_asia"] = east_asia
    if properties.find(qn("w", "b")) is not None:
        result["bold"] = True
    size = properties.find(qn("w", "sz"))
    if size is not None:
        value = size.attrib.get(qn("w", "val"), "")
        try:
            result["font_size_pt"] = int(value) / 2
        except ValueError:
            pass
    return result


def _latin_typeface(font) -> str | None:
    latin = font.find(qn("a", "latin")) if font is not None else None
    return latin.attrib.get("typeface") if latin is not None else None
