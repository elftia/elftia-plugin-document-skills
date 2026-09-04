"""Built-in, versioned style profiles for semantic DOCX roles."""

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.paths import (
    assert_source_preserved,
    file_record,
)

from .constants import MAX_HEADING_LEVEL, NS, qn
from .contracts import _exact_keys, _invalid
from .package import OpcPackage
from .xml_utils import xml_bytes

PROFESSIONAL_GENERIC = {"id": "professional-generic", "version": "1.0"}
ACADEMIC_PACK = {"id": "academic-pack", "version": "1.0"}
_SHA256 = re.compile(r"^[0-9A-Fa-f]{64}$")
_STYLE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,127}$")
_ROLE_KEYS = frozenset(
    {
        "abstract",
        "affiliations",
        "authors",
        "bibliography",
        "bibliography_heading",
        "caption",
        "citation",
        "equation",
        "figure",
        "keywords",
        "paragraph",
        "subtitle",
        "table",
        "title",
        *(f"heading.{level}" for level in range(1, MAX_HEADING_LEVEL + 1)),
    }
)


@dataclass(frozen=True)
class StyleDefinition:
    style_id: str
    name: str
    style_type: str = "paragraph"
    based_on: str | None = None
    next_style: str | None = None
    size_half_points: int = 22
    bold: bool = False
    alignment: str | None = None
    keep_with_next: bool = False
    keep_lines: bool = False
    space_before_twips: int | None = None
    space_after_twips: int | None = None
    line_twips: int | None = None
    outline_level: int | None = None
    latin_font: str = "Arial"
    east_asia_font: str = "Microsoft YaHei"
    first_line_chars: int | None = None
    hanging_twips: int | None = None
    left_twips: int | None = None


def parse_style_profile(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if type(value) is not dict:
        _invalid("style_profile must be an object.", field="style_profile")
    profile_id = value.get("id")
    if profile_id == "professional-generic":
        _exact_keys(value, {"id", "version"})
        if value != PROFESSIONAL_GENERIC:
            _invalid(
                "Unsupported DOCX style profile or version.",
                field="style_profile",
            )
        return dict(PROFESSIONAL_GENERIC)
    if profile_id != "template-mapped":
        _invalid(
            "Unsupported DOCX style profile or version.",
            field="style_profile",
        )
    _exact_keys(
        value,
        {
            "expected_source_sha256",
            "id",
            "role_styles",
            "source",
            "version",
        },
    )
    if value.get("version") != "1.0":
        _invalid("Unsupported template-mapped profile version.")
    raw_source = value.get("source")
    if (
        type(raw_source) is not str
        or not raw_source
        or len(raw_source.encode("utf-8", errors="strict")) > 32_768
        or "://" in raw_source
        or raw_source.startswith(("\\\\", "//"))
    ):
        _invalid("Template style source must be a bounded local path.")
    source = Path(raw_source).expanduser().resolve(strict=False)
    if source.suffix.casefold() not in {".docx", ".dotx"}:
        _invalid("Template style source must use .docx or .dotx.")
    digest = value.get("expected_source_sha256")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        _invalid("Template style source SHA-256 must be hexadecimal.")
    role_styles = value.get("role_styles")
    if type(role_styles) is not dict or not 1 <= len(role_styles) <= len(_ROLE_KEYS):
        _invalid("role_styles must be a non-empty bounded object.")
    parsed_roles: dict[str, str] = {}
    for role, style_id in role_styles.items():
        if role not in _ROLE_KEYS:
            _invalid("Unknown semantic style role.", field=f"role_styles.{role}")
        if type(style_id) is not str or _STYLE_ID.fullmatch(style_id) is None:
            _invalid("Mapped Word style id is invalid.", field=f"role_styles.{role}")
        parsed_roles[role] = style_id
    return {
        "id": "template-mapped",
        "version": "1.0",
        "source": source,
        "expected_source_sha256": digest.casefold(),
        "role_styles": parsed_roles,
    }


def style_id_for(
    profile: dict[str, Any] | None,
    role: str,
    *,
    heading_level: int | None = None,
) -> str | None:
    if profile is None:
        if role == "title":
            return "Title"
        if role == "heading" and heading_level is not None:
            return f"Heading{heading_level}"
        return {
            "paragraph": "Normal",
            "table": "TableGrid",
        }.get(role)
    if profile["id"] == "professional-generic":
        if role == "heading" and heading_level is not None:
            return f"ElftiaHeading{heading_level}"
        return {
            "abstract": "ElftiaAbstract",
            "affiliations": "ElftiaAffiliations",
            "authors": "ElftiaAuthors",
            "bibliography": "ElftiaBibliography",
            "bibliography_heading": "ElftiaHeading1",
            "caption": "ElftiaCaption",
            "citation": "ElftiaCitation",
            "equation": "ElftiaEquation",
            "figure": "ElftiaFigure",
            "keywords": "ElftiaKeywords",
            "paragraph": "ElftiaBody",
            "subtitle": "ElftiaSubtitle",
            "table": "ElftiaTable",
            "title": "ElftiaTitle",
        }.get(role)
    key = f"heading.{heading_level}" if role == "heading" else role
    style_id = profile["role_styles"].get(key)
    if style_id is None:
        _invalid("Style profile does not map a used semantic role.", role=key)
    return style_id


def render_style_profile(profile: dict[str, Any]) -> bytes:
    if profile.get("id") == "template-mapped":
        return _template_style_payload(profile)
    if profile != PROFESSIONAL_GENERIC and profile != ACADEMIC_PACK:
        raise ValueError("Unknown style profile.")
    root = Element(qn("w", "styles"))
    _append_defaults(root)
    definitions = (
        _academic_definitions()
        if profile == ACADEMIC_PACK
        else _professional_definitions()
    )
    for definition in definitions:
        _append_style(root, definition)
    return xml_bytes(root)


def identify_style_profile(payload: bytes) -> dict[str, str] | None:
    expected = render_style_profile(PROFESSIONAL_GENERIC)
    if sha256(payload).digest() == sha256(expected).digest():
        return dict(PROFESSIONAL_GENERIC)
    return None


def public_style_profile(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    result = {"id": profile["id"], "version": profile["version"]}
    if profile["id"] == "template-mapped":
        result.update(
            {
                "source": str(profile["source"]),
                "expected_source_sha256": profile["expected_source_sha256"],
                "role_styles": dict(sorted(profile["role_styles"].items())),
            }
        )
    return result


def _template_style_payload(profile: dict[str, Any]) -> bytes:
    source = profile["source"]
    record = file_record(source, "style_profile_source")
    if record.sha256 != profile["expected_source_sha256"]:
        _profile_precondition("source-sha256")
    package = OpcPackage.open(
        source,
        allow_template_main=source.suffix.casefold() == ".dotx",
    )
    assert_source_preserved(source, record.sha256)
    styles = package.xml("word/styles.xml")
    style_map = {
        node.attrib.get(qn("w", "styleId")): node
        for node in styles.findall(qn("w", "style"))
        if node.attrib.get(qn("w", "styleId"))
    }
    for role, style_id in profile["role_styles"].items():
        style = style_map.get(style_id)
        expected_type = "table" if role == "table" else "paragraph"
        if style is None or style.attrib.get(qn("w", "type")) != expected_type:
            _profile_precondition(
                "role-style-missing-or-wrong-type",
                role=role,
                style_id=style_id,
            )
    relationship_prefix = f"{{{NS['r']}}}"
    if any(
        name.startswith(relationship_prefix)
        for node in styles.iter()
        for name in node.attrib
    ):
        _profile_unsupported("relationship-bound-style")
    if next(styles.iter(qn("w", "numId")), None) is not None:
        _profile_unsupported("numbering-bound-style")
    available = set(style_map)
    for style_id, style in style_map.items():
        dependencies = {
            value
            for name in ("basedOn", "link", "next")
            if (node := style.find(qn("w", name))) is not None
            if (value := node.attrib.get(qn("w", "val")))
        }
        missing = sorted(dependencies - available)
        if missing:
            _profile_precondition(
                "style-dependency-missing",
                style_id=style_id,
                dependencies=missing,
            )
    for role, role_format in profile.get("role_formats", {}).items():
        _apply_role_format(style_map[profile["role_styles"][role]], role_format)
    if profile.get("role_formats"):
        return xml_bytes(styles)
    return package.parts["word/styles.xml"]


def _apply_role_format(style: Element, role_format: dict[str, Any]) -> None:
    run = style.find(qn("w", "rPr"))
    if run is None:
        run = SubElement(style, qn("w", "rPr"))
    _remove_children(run, "rFonts")
    SubElement(
        run,
        qn("w", "rFonts"),
        {
            qn("w", "ascii"): role_format["latin_font"],
            qn("w", "hAnsi"): role_format["latin_font"],
            qn("w", "eastAsia"): role_format["east_asia_font"],
            qn("w", "cs"): role_format["latin_font"],
        },
    )
    size = str(role_format["size_half_points"])
    for name in ("sz", "szCs"):
        _remove_children(run, name)
        SubElement(run, qn("w", name), {qn("w", "val"): size})
    if "bold" in role_format:
        _remove_children(run, "b")
        if role_format["bold"]:
            SubElement(run, qn("w", "b"))
    paragraph_keys = {
        "alignment",
        "first_line_chars",
        "hanging_twips",
        "left_twips",
        "space_before_twips",
        "space_after_twips",
        "line_twips",
    }
    if not paragraph_keys.intersection(role_format):
        return
    paragraph = style.find(qn("w", "pPr"))
    if paragraph is None:
        paragraph = Element(qn("w", "pPr"))
        run_index = list(style).index(run)
        style.insert(run_index, paragraph)
    if "alignment" in role_format:
        _remove_children(paragraph, "jc")
        SubElement(
            paragraph,
            qn("w", "jc"),
            {qn("w", "val"): role_format["alignment"]},
        )
    indentation_values = {
        "firstLineChars": role_format.get("first_line_chars"),
        "hanging": role_format.get("hanging_twips"),
        "left": role_format.get("left_twips"),
    }
    if any(value is not None for value in indentation_values.values()):
        indentation = paragraph.find(qn("w", "ind"))
        if indentation is None:
            indentation = SubElement(paragraph, qn("w", "ind"))
        for name, value in indentation_values.items():
            if value is not None:
                indentation.attrib[qn("w", name)] = str(value)
    spacing_values = {
        "before": role_format.get("space_before_twips"),
        "after": role_format.get("space_after_twips"),
        "line": role_format.get("line_twips"),
    }
    if any(value is not None for value in spacing_values.values()):
        spacing = paragraph.find(qn("w", "spacing"))
        if spacing is None:
            spacing = SubElement(paragraph, qn("w", "spacing"))
        for name, value in spacing_values.items():
            if value is not None:
                spacing.attrib[qn("w", name)] = str(value)
        if spacing_values["line"] is not None:
            spacing.attrib[qn("w", "lineRule")] = "auto"


def _remove_children(parent: Element, name: str) -> None:
    for child in list(parent.findall(qn("w", name))):
        parent.remove(child)


def _profile_precondition(reason: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.VALIDATION_FAILED,
        "Template style profile precondition did not match its source.",
        details={"reason": reason, **details},
    )


def _profile_unsupported(reason: str) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Template style profile requires unsupported Word style dependencies.",
        status="enhancement_required",
        details={"reason": reason},
    )


def _professional_definitions() -> tuple[StyleDefinition, ...]:
    headings = tuple(
        StyleDefinition(
            style_id=f"ElftiaHeading{level}",
            name=f"Elftia Heading {level}",
            based_on="Normal",
            next_style="ElftiaBody",
            size_half_points=(32, 28, 26, 24, 22, 22)[level - 1],
            bold=True,
            keep_with_next=True,
            keep_lines=True,
            space_before_twips=240 if level <= 2 else 180,
            space_after_twips=120 if level <= 2 else 80,
            outline_level=level - 1,
        )
        for level in range(1, MAX_HEADING_LEVEL + 1)
    )
    return (
        StyleDefinition("Normal", "Normal"),
        StyleDefinition(
            "ElftiaBody",
            "Elftia Body",
            based_on="Normal",
            next_style="ElftiaBody",
            space_after_twips=120,
            line_twips=276,
        ),
        StyleDefinition(
            "ElftiaTitle",
            "Elftia Title",
            based_on="Normal",
            next_style="ElftiaBody",
            size_half_points=48,
            bold=True,
            alignment="center",
            keep_with_next=True,
            space_after_twips=240,
        ),
        StyleDefinition(
            "ElftiaSubtitle",
            "Elftia Subtitle",
            based_on="ElftiaBody",
            next_style="ElftiaAuthors",
            size_half_points=28,
            alignment="center",
            keep_with_next=True,
            space_after_twips=160,
        ),
        StyleDefinition(
            "ElftiaAuthors",
            "Elftia Authors",
            based_on="ElftiaBody",
            next_style="ElftiaAffiliations",
            alignment="center",
            keep_with_next=True,
            space_after_twips=80,
        ),
        StyleDefinition(
            "ElftiaAffiliations",
            "Elftia Affiliations",
            based_on="ElftiaBody",
            next_style="ElftiaAbstract",
            size_half_points=20,
            alignment="center",
            keep_with_next=True,
            space_after_twips=160,
        ),
        StyleDefinition(
            "ElftiaAbstract",
            "Elftia Abstract",
            based_on="ElftiaBody",
            next_style="ElftiaKeywords",
            size_half_points=21,
            keep_lines=True,
            space_after_twips=100,
            line_twips=252,
        ),
        StyleDefinition(
            "ElftiaKeywords",
            "Elftia Keywords",
            based_on="ElftiaBody",
            next_style="ElftiaBody",
            size_half_points=21,
            keep_with_next=True,
            space_after_twips=180,
        ),
        *headings,
        StyleDefinition(
            "ElftiaFigure",
            "Elftia Figure",
            based_on="ElftiaBody",
            next_style="ElftiaBody",
            alignment="center",
            keep_with_next=True,
            space_after_twips=80,
        ),
        StyleDefinition(
            "ElftiaCaption",
            "Elftia Caption",
            based_on="ElftiaBody",
            next_style="ElftiaBody",
            size_half_points=18,
            alignment="center",
            keep_lines=True,
            space_after_twips=120,
        ),
        StyleDefinition(
            "ElftiaEquation",
            "Elftia Equation",
            based_on="ElftiaBody",
            next_style="ElftiaCaption",
            alignment="center",
            keep_with_next=True,
            keep_lines=True,
            space_after_twips=80,
        ),
        StyleDefinition(
            "ElftiaCitation",
            "Elftia Citation",
            based_on="ElftiaBody",
            next_style="ElftiaBody",
            space_after_twips=120,
        ),
        StyleDefinition(
            "ElftiaBibliography",
            "Elftia Bibliography",
            based_on="ElftiaBody",
            next_style="ElftiaBibliography",
            size_half_points=20,
            keep_lines=True,
            space_after_twips=80,
        ),
        StyleDefinition(
            "ElftiaTable",
            "Elftia Table",
            style_type="table",
            size_half_points=20,
        ),
    )


def _academic_definitions() -> tuple[StyleDefinition, ...]:
    definitions = []
    for definition in _professional_definitions():
        east_asia = (
            "SimHei"
            if definition.style_id == "ElftiaTitle"
            or definition.style_id.startswith("ElftiaHeading")
            else "SimSun"
        )
        changes: dict[str, Any] = {
            "latin_font": "Times New Roman",
            "east_asia_font": east_asia,
        }
        if definition.style_id in {"ElftiaBody", "ElftiaAbstract"}:
            changes["first_line_chars"] = 200
        if definition.style_id == "ElftiaBody":
            changes["alignment"] = "both"
        if definition.style_id == "ElftiaBibliography":
            changes.update({"hanging_twips": 360, "left_twips": 360})
        definitions.append(replace(definition, **changes))
    return tuple(definitions)


def _append_defaults(root: Element) -> None:
    defaults = SubElement(root, qn("w", "docDefaults"))
    run_default = SubElement(defaults, qn("w", "rPrDefault"))
    run_properties = SubElement(run_default, qn("w", "rPr"))
    _append_fonts(run_properties, StyleDefinition("Normal", "Normal"))
    SubElement(run_properties, qn("w", "sz"), {qn("w", "val"): "22"})
    SubElement(run_properties, qn("w", "szCs"), {qn("w", "val"): "22"})
    SubElement(
        run_properties,
        qn("w", "lang"),
        {qn("w", "val"): "en-US", qn("w", "eastAsia"): "zh-CN"},
    )


def _append_style(root: Element, definition: StyleDefinition) -> None:
    attributes = {
        qn("w", "type"): definition.style_type,
        qn("w", "styleId"): definition.style_id,
    }
    if definition.style_id == "Normal":
        attributes[qn("w", "default")] = "1"
    style = SubElement(root, qn("w", "style"), attributes)
    SubElement(style, qn("w", "name"), {qn("w", "val"): definition.name})
    if definition.based_on is not None:
        SubElement(
            style,
            qn("w", "basedOn"),
            {qn("w", "val"): definition.based_on},
        )
    if definition.next_style is not None:
        SubElement(
            style,
            qn("w", "next"),
            {qn("w", "val"): definition.next_style},
        )
    SubElement(style, qn("w", "qFormat"))
    paragraph_properties = _paragraph_properties(style, definition)
    run_properties = SubElement(style, qn("w", "rPr"))
    _append_fonts(run_properties, definition)
    if definition.bold:
        SubElement(run_properties, qn("w", "b"))
    size = str(definition.size_half_points)
    SubElement(run_properties, qn("w", "sz"), {qn("w", "val"): size})
    SubElement(run_properties, qn("w", "szCs"), {qn("w", "val"): size})
    if definition.style_type == "table":
        _append_table_properties(style)
    if paragraph_properties is not None and not list(paragraph_properties):
        style.remove(paragraph_properties)


def _paragraph_properties(
    style: Element,
    definition: StyleDefinition,
) -> Element | None:
    if definition.style_type != "paragraph":
        return None
    properties = SubElement(style, qn("w", "pPr"))
    if definition.keep_with_next:
        SubElement(properties, qn("w", "keepNext"))
    if definition.keep_lines:
        SubElement(properties, qn("w", "keepLines"))
    spacing = {}
    if definition.space_before_twips is not None:
        spacing[qn("w", "before")] = str(definition.space_before_twips)
    if definition.space_after_twips is not None:
        spacing[qn("w", "after")] = str(definition.space_after_twips)
    if definition.line_twips is not None:
        spacing[qn("w", "line")] = str(definition.line_twips)
        spacing[qn("w", "lineRule")] = "auto"
    if spacing:
        SubElement(properties, qn("w", "spacing"), spacing)
    if definition.alignment is not None:
        SubElement(
            properties,
            qn("w", "jc"),
            {qn("w", "val"): definition.alignment},
        )
    if definition.outline_level is not None:
        SubElement(
            properties,
            qn("w", "outlineLvl"),
            {qn("w", "val"): str(definition.outline_level)},
        )
    indentation = {}
    if definition.first_line_chars is not None:
        indentation[qn("w", "firstLineChars")] = str(definition.first_line_chars)
    if definition.hanging_twips is not None:
        indentation[qn("w", "hanging")] = str(definition.hanging_twips)
    if definition.left_twips is not None:
        indentation[qn("w", "left")] = str(definition.left_twips)
    if indentation:
        SubElement(properties, qn("w", "ind"), indentation)
    return properties


def _append_fonts(properties: Element, definition: StyleDefinition) -> None:
    SubElement(
        properties,
        qn("w", "rFonts"),
        {
            qn("w", "ascii"): definition.latin_font,
            qn("w", "hAnsi"): definition.latin_font,
            qn("w", "eastAsia"): definition.east_asia_font,
            qn("w", "cs"): definition.latin_font,
        },
    )


def _append_table_properties(style: Element) -> None:
    table_properties = SubElement(style, qn("w", "tblPr"))
    borders = SubElement(table_properties, qn("w", "tblBorders"))
    for name in ("top", "left", "bottom", "right", "insideH", "insideV"):
        SubElement(
            borders,
            qn("w", name),
            {
                qn("w", "val"): "single",
                qn("w", "sz"): "4",
                qn("w", "color"): "B8C2CC",
            },
        )
    first_row = SubElement(
        style,
        qn("w", "tblStylePr"),
        {qn("w", "type"): "firstRow"},
    )
    run_properties = SubElement(first_row, qn("w", "rPr"))
    SubElement(run_properties, qn("w", "b"))
