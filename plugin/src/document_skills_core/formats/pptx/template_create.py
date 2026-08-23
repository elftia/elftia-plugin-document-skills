"""Create a typed deck while reusing an existing PPTX design graph."""

from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS, local_name
from .design_contracts import DEFAULT_THEME
from .mapping import map_slides
from .mutation import MutablePptxPackage
from .package import OpcPackage
from .projection import project_slide_size, project_theme
from .scaffold import _build_app_props, _build_core_props, _to_xml_bytes
from .slide_graph import add_slide, delete_slide

_P = NS["p"]
_CONTENT_TYPES_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
_PRESENTATION_MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"
)
_TEMPLATE_MAIN_TYPE = (
    "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml"
)


def create_pptx_from_template(
    destination: Path,
    deck: dict[str, Any],
    template_path: Path,
) -> dict[str, Any]:
    if not template_path.is_file():
        _invalid("The PPTX template must be an existing local file.", template=str(template_path))
    source_hash = sha256(template_path.read_bytes()).hexdigest()
    source = open_template_package(template_path)
    target = MutablePptxPackage(source)
    source_slide_size = project_slide_size(source)
    requested_size = deck.get("slide_size")
    if requested_size is not None and not _same_slide_size(requested_size, source_slide_size):
        _invalid(
            "Template-as-base cannot change the template slide size.",
            requested=requested_size,
            template=source_slide_size,
        )
    effective_size = source_slide_size or {
        "cx": "9144000",
        "cy": "6858000",
        "type": "screen4x3",
    }
    theme = _template_theme(source)

    while map_slides(target):
        delete_slide(target, len(map_slides(target)))

    lifecycle = []
    image_records = []
    chart_records = []
    for position, slide in enumerate(deck["slides"], 1):
        evidence = add_slide(
            target,
            slide,
            position,
            theme=theme,
            layout_tokens=deck["layout_tokens"],
        )
        lifecycle.append(evidence)
        if evidence.get("image") is not None:
            image_records.append(evidence["image"])
        if evidence.get("chart") is not None:
            chart_records.append(evidence["chart"])

    if "docProps/core.xml" in target.parts:
        target.set_part("docProps/core.xml", _build_core_props(deck["metadata"]))
    if "docProps/app.xml" in target.parts:
        target.set_part("docProps/app.xml", _build_app_props(deck["slides"]))
    normalized_main_type = _normalize_presentation_content_type(target)
    manifest = target.emit(destination)
    if sha256(template_path.read_bytes()).hexdigest() != source_hash:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "The PPTX template changed during template-as-base creation.",
            status="failed",
        )

    candidate = OpcPackage.open(destination)
    return {
        "charts": chart_records,
        "has_chart": bool(chart_records),
        "has_image": bool(image_records),
        "has_notes": any(slide.get("notes") is not None for slide in deck["slides"]),
        "has_table": any(slide.get("table") is not None for slide in deck["slides"]),
        "images": image_records,
        "layout_recipes": [
            {
                "layout_part": evidence["layout_part"],
                "name": slide["recipe"],
                "slide": index,
            }
            for index, (slide, evidence) in enumerate(
                zip(deck["slides"], lifecycle, strict=True),
                1,
            )
        ],
        "layouts": len(candidate.slide_layout_parts()),
        "metadata": deck["metadata"],
        "slide_size": effective_size,
        "slides": len(deck["slides"]),
        "template_reuse": {
            "added_parts": len(manifest.added),
            "changed_parts": len(manifest.changed),
            "master_parts": candidate.slide_master_parts(),
            "preserved_parts": len(manifest.preserved),
            "removed_parts": len(manifest.removed),
            "source_sha256": source_hash,
            "source_extension": template_path.suffix.casefold(),
            "template": str(template_path),
            "theme_parts": candidate.theme_parts(),
            "presentation_content_type": candidate.content_type_for(
                "ppt/presentation.xml"
            ),
            "template_main_type_normalized": normalized_main_type,
        },
        "theme": project_theme(candidate),
    }


def _template_theme(package: OpcPackage) -> dict[str, Any]:
    projected = project_theme(package) or {}
    result = deepcopy(DEFAULT_THEME)
    if projected.get("name"):
        result["name"] = projected["name"]
    result["palette"].update({
        key: value
        for key, value in projected.get("palette", {}).items()
        if key in result["palette"] and _is_color(value)
    })
    result["fonts"].update({
        key: value
        for key, value in projected.get("fonts", {}).items()
        if key in result["fonts"] and value
    })
    masters = package.slide_master_parts()
    if masters:
        root = package.xml(masters[0])
        common = root.find(f"{{{_P}}}cSld")
        background = None if common is None else common.find(f"{{{_P}}}bg")
        color = next(
            (
                node.attrib.get("val", "")
                for node in ([] if background is None else background.iter())
                if local_name(node.tag) == "srgbClr"
            ),
            "",
        )
        if _is_color(color):
            result["background"] = color
    result["default_chart"]["colors"] = [
        result["palette"][f"accent{index}"] for index in range(1, 7)
    ]
    return result


def open_template_package(template_path: Path) -> OpcPackage:
    suffix = template_path.suffix.casefold()
    if suffix == ".pptx":
        return OpcPackage.open(template_path)
    if suffix != ".potx":
        _invalid("Template-as-base requires a .pptx or .potx file.")
    source = OpcPackage.open(template_path, allow_dangerous_inventory=True)
    if source.content_type_for("ppt/presentation.xml") != _TEMPLATE_MAIN_TYPE:
        _invalid("A .potx template must declare the PresentationML template main type.")
    categories = source.security.get("categories", {})
    unexpected = {
        name: records
        for name, records in categories.items()
        if name != "templates" and records
    }
    template_records = categories.get("templates", [])
    expected_record = {
        "part": "/ppt/presentation.xml",
        "kind": "content-type",
        "type": _TEMPLATE_MAIN_TYPE,
    }
    if unexpected or template_records != [expected_record]:
        _invalid(
            "POTX template contains unsupported active or external inventory.",
            unexpected_categories=sorted(unexpected),
            template_records=template_records,
        )
    return source


def _normalize_presentation_content_type(target: MutablePptxPackage) -> bool:
    root = target.xml("[Content_Types].xml")
    matches = [
        node
        for node in root
        if node.tag == f"{{{_CONTENT_TYPES_NS}}}Override"
        and node.attrib.get("PartName") == "/ppt/presentation.xml"
    ]
    if len(matches) != 1:
        _invalid("Template must declare one presentation main content type.")
    changed = matches[0].attrib.get("ContentType") != _PRESENTATION_MAIN_TYPE
    matches[0].set("ContentType", _PRESENTATION_MAIN_TYPE)
    if changed:
        target.set_part("[Content_Types].xml", _to_xml_bytes(root))
    return changed


def _same_slide_size(
    requested: dict[str, Any],
    actual: dict[str, Any] | None,
) -> bool:
    if actual is None:
        return False
    return (
        str(requested.get("cx")) == str(actual.get("cx"))
        and str(requested.get("cy")) == str(actual.get("cy"))
    )


def _is_color(value: Any) -> bool:
    return (
        type(value) is str
        and len(value) == 6
        and all(character in "0123456789ABCDEFabcdef" for character in value)
    )


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
