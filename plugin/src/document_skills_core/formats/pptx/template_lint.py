"""Read-only template inheritance and direct-format contamination report."""

from typing import Any

from .constants import NS, PRESENTATION_MAIN, local_name
from .mapping import map_slides
from .object_xml import drawable_elements, non_visual_properties, slide_shape_tree

_R_ID = f"{{{NS['r']}}}id"
_DIRECT_STYLE_TAGS = {
    "blipFill",
    "effectDag",
    "effectLst",
    "gradFill",
    "grpFill",
    "ln",
    "noFill",
    "pattFill",
    "solidFill",
}
_DIRECT_TEXT_ATTRIBUTES = {
    "b", "baseline", "cap", "i", "kern", "normalizeH", "spc", "strike", "sz", "u",
}


def lint_template(package: Any) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    masters = _master_inventory(package, issues)
    layouts = _layout_inventory(package, issues)
    direct_formatting = _direct_formatting(package)
    registered_masters = {item["part"] for item in masters}
    registered_layouts = {item["part"] for item in layouts}
    for part in package.slide_master_parts():
        if part not in registered_masters:
            issues.append({"code": "unregistered-master", "part": part})
    for part in package.slide_layout_parts():
        if part not in registered_layouts:
            issues.append({"code": "unregistered-layout", "part": part})
    return {
        "direct_format_contamination": {
            "count": len(direct_formatting),
            "findings": direct_formatting,
            "present": bool(direct_formatting),
        },
        "inheritance": {
            "issues": issues,
            "valid": not issues,
        },
        "layouts": layouts,
        "masters": masters,
        "mutation_authorized": False,
    }


def _master_inventory(
    package: Any,
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    presentation = package.xml(PRESENTATION_MAIN)
    identifiers = next(
        (node for node in presentation if local_name(node.tag) == "sldMasterIdLst"),
        None,
    )
    relationships = {
        item.relationship_id: item
        for item in package.part_rels(PRESENTATION_MAIN)
        if item.relationship_type.endswith("/slideMaster")
    }
    result = []
    for identifier in [] if identifiers is None else list(identifiers):
        relationship_id = identifier.attrib.get(_R_ID, "")
        relationship = relationships.get(relationship_id)
        part = None if relationship is None else relationship.resolved_target
        if part not in package.parts:
            issues.append({"code": "missing-master", "relationship_id": relationship_id})
            continue
        rels = package.part_rels(part)
        themes = [item.resolved_target for item in rels if item.relationship_type.endswith("/theme")]
        layouts = [item.resolved_target for item in rels if item.relationship_type.endswith("/slideLayout")]
        if len(themes) != 1 or themes[0] not in package.parts:
            issues.append({"code": "master-theme", "part": part})
        root = package.xml(part)
        common = next((node for node in root if local_name(node.tag) == "cSld"), None)
        result.append({
            "layout_parts": sorted(item for item in layouts if item is not None),
            "name": "" if common is None else common.attrib.get("name", ""),
            "part": part,
            "theme_part": themes[0] if len(themes) == 1 else None,
        })
    return result


def _layout_inventory(
    package: Any,
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = []
    registered = {
        item.resolved_target: item.source_part
        for item in package.relationships
        if item.relationship_type.endswith("/slideLayout")
        and item.source_part.startswith("ppt/slideMasters/")
        and item.resolved_target is not None
    }
    for part, registered_master in sorted(registered.items()):
        if part not in package.parts:
            issues.append({"code": "missing-layout", "part": part})
            continue
        inverse = [
            item.resolved_target
            for item in package.part_rels(part)
            if item.relationship_type.endswith("/slideMaster")
        ]
        if inverse != [registered_master]:
            issues.append({"code": "layout-master-inheritance", "part": part})
        root = package.xml(part)
        common = next((node for node in root if local_name(node.tag) == "cSld"), None)
        header_footer = next((node for node in root if local_name(node.tag) == "hf"), None)
        placeholders = []
        if common is not None:
            try:
                elements = drawable_elements(slide_shape_tree(root))
            except Exception:
                elements = []
            for element in elements:
                placeholder = next(
                    (node for node in element.iter() if local_name(node.tag) == "ph"),
                    None,
                )
                if placeholder is not None:
                    placeholders.append({
                        "idx": placeholder.attrib.get("idx", "0"),
                        "type": placeholder.attrib.get("type", "body"),
                    })
        result.append({
            "background": common is not None and any(
                local_name(node.tag) == "bg" for node in list(common)
            ),
            "footer_flags": {} if header_footer is None else dict(sorted(header_footer.attrib.items())),
            "master_part": inverse[0] if len(inverse) == 1 else None,
            "name": "" if common is None else common.attrib.get("name", ""),
            "part": part,
            "placeholders": placeholders,
            "show_master_shapes": root.attrib.get("showMasterSp", "1") != "0",
            "type": root.attrib.get("type", "cust"),
        })
    return result


def _direct_formatting(package: Any) -> list[dict[str, Any]]:
    findings = []
    for slide in map_slides(package):
        part = slide.get("part")
        if not part:
            continue
        root = package.xml(part)
        for element in drawable_elements(slide_shape_tree(root)):
            placeholder = next(
                (node for node in element.iter() if local_name(node.tag) == "ph"),
                None,
            )
            if placeholder is None:
                continue
            properties = sorted(_direct_properties(element))
            if not properties:
                continue
            identity = non_visual_properties(element)
            findings.append({
                "name": identity.attrib.get("name", ""),
                "part": part,
                "properties": properties,
                "shape_id": identity.attrib.get("id", ""),
                "slide": slide["number"],
            })
    return findings


def _direct_properties(element: Any) -> set[str]:
    properties = set()
    for node in element.iter():
        name = local_name(node.tag)
        if name in _DIRECT_STYLE_TAGS:
            properties.add(name)
        if name in {"defRPr", "endParaRPr", "rPr"}:
            properties.update(
                f"text:{attribute}"
                for attribute in node.attrib
                if local_name(attribute) in _DIRECT_TEXT_ATTRIBUTES
            )
            if any(local_name(child.tag) in {"ea", "latin", "sym"} for child in node):
                properties.add("text:typeface")
    return properties
