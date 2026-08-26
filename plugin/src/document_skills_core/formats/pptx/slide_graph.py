"""Slide lifecycle operations and relationship-graph copying."""

from dataclasses import dataclass
import posixpath
import re
from typing import Any
from xml.etree.ElementTree import Element, SubElement, tostring

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .chart import build_chart_part, prepare_chart, public_chart_record
from .constants import CONTENT_TYPES_NS, NS
from .design_contracts import DEFAULT_LAYOUT_TOKENS, DEFAULT_THEME
from .create import (
    _build_notes_master,
    _build_notes_slide,
    _build_slide,
)
from .image import load_pptx_image, public_image_record
from .layout_recipes import layout_recipe
from .mapping import map_slides
from .mutation import MutablePptxPackage

_P = NS["p"]
_R = NS["r"]
_RELS = NS["rels"]
_TRAILING_NUMBER = re.compile(r"^(.*?)(\d+)$")
_SHARED_SAME_DECK = {"notesMaster", "slideLayout", "slideMaster", "theme"}


def P(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def R(tag: str) -> str:
    return f"{{{_R}}}{tag}"


def RELS(tag: str) -> str:
    return f"{{{_RELS}}}{tag}"


@dataclass(frozen=True)
class SlideCopyResult:
    source_slide_part: str
    target_slide_part: str
    source_position: int
    target_position: int
    cross_deck: bool
    dependency_mapping: dict[str, str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "cross_deck": self.cross_deck,
            "dependencies": [
                {"source_part": source, "target_part": target}
                for source, target in sorted(self.dependency_mapping.items())
            ],
            "source_position": self.source_position,
            "source_slide_part": self.source_slide_part,
            "target_position": self.target_position,
            "target_slide_part": self.target_slide_part,
        }


def add_slide(
    target: MutablePptxPackage,
    slide: dict[str, Any],
    position: int | None,
    *,
    theme: dict[str, Any] | None = None,
    layout_tokens: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_position = _bounded_insert_position(position, len(map_slides(target)) + 1)
    slide_part = _allocate_part_name("ppt/slides/slide1.xml", set(target.parts))
    prepared = dict(slide)
    mapped = map_slides(target)
    slide_size = (
        mapped[0].get("slide_size")
        if mapped
        else {"cx": "9144000", "cy": "6858000"}
    )
    recipe = layout_recipe(
        slide.get("recipe", "cover" if slide.get("layout") == "title" else "content"),
        slide_size,
        layout_tokens or DEFAULT_LAYOUT_TOKENS,
        len(slide.get("shapes", [])),
    )
    prepared["_layout_recipe"] = recipe
    selected_theme = theme or DEFAULT_THEME
    prepared["_theme"] = selected_theme
    additions: dict[str, str] = {
        slide_part: "application/vnd.openxmlformats-officedocument.presentationml.slide+xml"
    }
    created_parts = [slide_part]
    image_record = None
    chart_record = None
    image = None
    chart = None
    if slide.get("image_reference") is not None:
        image_reference = dict(slide["image_reference"])
        if image_reference.get("frame") is None:
            image_reference["frame"] = recipe["media"]
        image_index = _next_part_index(target.parts, "ppt/media/image")
        image = load_pptx_image(image_reference, image_index)
        while image["part"] in target.parts:
            image_index += 1
            image = load_pptx_image(image_reference, image_index)
        prepared["_image"] = image
        target.set_part(image["part"], image["bytes"])
        additions[image["part"]] = image["content_type"]
        created_parts.append(image["part"])
        image_record = public_image_record(image)
    if slide.get("chart_reference") is not None:
        chart_index = _next_part_index(target.parts, "ppt/charts/chart")
        chart_reference = dict(slide["chart_reference"])
        if not chart_reference.get("colors"):
            chart_reference["colors"] = list(selected_theme["default_chart"]["colors"])
        chart = prepare_chart(chart_reference, chart_index)
        while chart["part"] in target.parts:
            chart_index += 1
            chart = prepare_chart(chart_reference, chart_index)
        prepared["_chart"] = chart
        target.set_part(chart["part"], build_chart_part(chart))
        additions[chart["part"]] = "application/vnd.openxmlformats-officedocument.drawingml.chart+xml"
        created_parts.append(chart["part"])
        chart_record = public_chart_record(chart)
    requested_layout = slide.get("layout", "content")
    if recipe["name"] != "content" and requested_layout in {"content", "title"}:
        requested_layout = recipe["name"]
    layout_part = _select_layout(target, requested_layout)
    notes_part = None
    notes_master = None
    if slide.get("notes") is not None:
        notes_master = _ensure_notes_master(target, additions, created_parts)
        notes_part = _allocate_part_name("ppt/notesSlides/notesSlide1.xml", set(target.parts))
        target.set_part(notes_part, _build_notes_slide(target_position, slide["notes"] or ""))
        additions[notes_part] = "application/vnd.openxmlformats-officedocument.presentationml.notesSlide+xml"
        created_parts.append(notes_part)
    target.set_part(slide_part, _build_slide(prepared, target_position))
    target.set_part(
        relationship_part_for(slide_part),
        _new_slide_relationships(
            slide_part,
            layout_part,
            image=image,
            chart=chart,
            notes_part=notes_part,
        ),
    )
    created_parts.append(relationship_part_for(slide_part))
    if notes_part is not None and notes_master is not None:
        notes_rels = Element(RELS("Relationships"))
        SubElement(notes_rels, RELS("Relationship"), {
            "Id": "rIdSlide",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
            "Target": posixpath.relpath(slide_part, posixpath.dirname(notes_part)),
        })
        SubElement(notes_rels, RELS("Relationship"), {
            "Id": "rIdNotesMaster",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster",
            "Target": posixpath.relpath(notes_master, posixpath.dirname(notes_part)),
        })
        target.set_part(relationship_part_for(notes_part), _xml_bytes(notes_rels))
        created_parts.append(relationship_part_for(notes_part))
    _add_slide_to_presentation(target, slide_part, target_position)
    _rewrite_content_types(target, removed=set(), additions=additions)
    return {
        "chart": chart_record,
        "created_parts": sorted(created_parts),
        "image": image_record,
        "layout_part": layout_part,
        "position": target_position,
        "slide_part": slide_part,
    }


def delete_slide(target: MutablePptxPackage, position: int) -> dict[str, Any]:
    slides = map_slides(target)
    slide = _slide_at(slides, position)
    slide_part = slide["part"]
    relationship_id = slide["relationship_id"]
    assert slide_part is not None

    relationships = target.relationships
    candidates = _forward_dependencies(relationships, slide_part)
    reachable = _root_reachable_without(relationships, relationship_id)
    removable = {part for part in candidates if part not in reachable}
    removable.add(slide_part)

    presentation = target.xml("ppt/presentation.xml")
    slide_ids = presentation.find(P("sldIdLst"))
    if slide_ids is None:
        _invalid("Presentation slide list is missing.")
    for node in list(slide_ids):
        if node.attrib.get(R("id")) == relationship_id:
            slide_ids.remove(node)
            break
    target.set_part("ppt/presentation.xml", _xml_bytes(presentation))

    presentation_rels = target.xml("ppt/_rels/presentation.xml.rels")
    for node in list(presentation_rels):
        if node.attrib.get("Id") == relationship_id:
            presentation_rels.remove(node)
            break
    target.set_part("ppt/_rels/presentation.xml.rels", _xml_bytes(presentation_rels))

    removed: set[str] = set()
    for part in sorted(removable):
        if part in target.parts:
            target.remove_part(part)
            removed.add(part)
        rels_part = relationship_part_for(part)
        if rels_part in target.parts:
            target.remove_part(rels_part)
            removed.add(rels_part)
    _rewrite_content_types(target, removed=removed, additions={})
    return {
        "position": position,
        "removed_parts": sorted(removed),
        "slide_part": slide_part,
    }


def copy_slide(
    target: MutablePptxPackage,
    source: Any,
    source_position: int,
    target_position: int | None,
    *,
    cross_deck: bool,
) -> SlideCopyResult:
    source_slides = map_slides(source)
    source_slide = _slide_at(source_slides, source_position)
    source_part = source_slide["part"]
    if source_part is None:
        _invalid("Source slide part is missing.")
    position = _bounded_insert_position(
        target_position,
        len(map_slides(target)) + 1,
    )
    occupied_before_copy = set(target.parts)
    mapping: dict[str, str] = {
        source_part: _allocate_part_name(source_part, set(target.parts))
    }
    existing_notes_master = _first_relationship_target(target, "notesMaster")
    _copy_part_graph(
        source,
        target,
        source_part,
        mapping,
        cross_deck=cross_deck,
        source_root=source_part,
        existing_notes_master=existing_notes_master,
    )
    target_slide_part = mapping[source_part]
    _add_imported_masters(target, source, mapping)
    _add_slide_to_presentation(target, target_slide_part, position)
    additions = {
        destination: source.content_type_for(source_name) or ""
        for source_name, destination in mapping.items()
        if destination not in occupied_before_copy and not destination.endswith(".rels")
    }
    _rewrite_content_types(target, removed=set(), additions=additions)
    return SlideCopyResult(
        source_part,
        target_slide_part,
        source_position,
        position,
        cross_deck,
        dict(mapping),
    )


def relationship_part_for(part_name: str) -> str:
    directory, filename = posixpath.split(part_name)
    return posixpath.join(directory, "_rels", f"{filename}.rels")


def _new_slide_relationships(
    slide_part: str,
    layout_part: str,
    *,
    image: dict[str, Any] | None,
    chart: dict[str, Any] | None,
    notes_part: str | None,
) -> bytes:
    root = Element(RELS("Relationships"))
    directory = posixpath.dirname(slide_part)
    SubElement(root, RELS("Relationship"), {
        "Id": "rIdLayout",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout",
        "Target": posixpath.relpath(layout_part, directory),
    })
    if chart is not None:
        SubElement(root, RELS("Relationship"), {
            "Id": chart["relationship_id"],
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart",
            "Target": posixpath.relpath(chart["part"], directory),
        })
    if image is not None:
        SubElement(root, RELS("Relationship"), {
            "Id": image["relationship_id"],
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": posixpath.relpath(image["part"], directory),
        })
    if notes_part is not None:
        SubElement(root, RELS("Relationship"), {
            "Id": "rIdNotes",
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesSlide",
            "Target": posixpath.relpath(notes_part, directory),
        })
    return _xml_bytes(root)


def _select_layout(target: MutablePptxPackage, requested: str) -> str:
    layouts = target.source.slide_layout_parts()
    if requested in target.parts and requested.startswith("ppt/slideLayouts/"):
        return requested
    requested_key = requested.casefold().replace("-", " ")
    if requested_key == "title":
        requested_key = "cover"
    for layout in layouts:
        try:
            root = target.xml(layout)
            common = root.find(P("cSld"))
            name = "" if common is None else common.attrib.get("name", "")
            if name.casefold().replace("-", " ") == requested_key:
                return layout
        except Exception:
            continue
    if not layouts:
        _invalid("Target deck has no reusable slide layout.")
    if requested_key == "cover":
        return layouts[0]
    if requested_key == "content":
        return layouts[0]
    _invalid("Requested slide layout was not found.", layout=requested)


def _ensure_notes_master(
    target: MutablePptxPackage,
    additions: dict[str, str],
    created_parts: list[str],
) -> str:
    existing = _first_relationship_target(target, "notesMaster")
    if existing is not None:
        return existing
    notes_master = _allocate_part_name("ppt/notesMasters/notesMaster1.xml", set(target.parts))
    theme = _first_theme_part(target)
    target.set_part(notes_master, _build_notes_master())
    additions[notes_master] = "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"
    created_parts.append(notes_master)
    rels = Element(RELS("Relationships"))
    SubElement(rels, RELS("Relationship"), {
        "Id": "rIdTheme",
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme",
        "Target": posixpath.relpath(theme, posixpath.dirname(notes_master)),
    })
    target.set_part(relationship_part_for(notes_master), _xml_bytes(rels))
    created_parts.append(relationship_part_for(notes_master))
    presentation_rels = target.xml("ppt/_rels/presentation.xml.rels")
    relationship_id = _next_relationship_id(presentation_rels, "rIdNotesMaster")
    SubElement(presentation_rels, RELS("Relationship"), {
        "Id": relationship_id,
        "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster",
        "Target": posixpath.relpath(notes_master, "ppt"),
    })
    target.set_part("ppt/_rels/presentation.xml.rels", _xml_bytes(presentation_rels))
    presentation = target.xml("ppt/presentation.xml")
    notes_master_ids = Element(P("notesMasterIdLst"))
    SubElement(notes_master_ids, P("notesMasterId"), {R("id"): relationship_id})
    slide_ids = presentation.find(P("sldIdLst"))
    insertion = list(presentation).index(slide_ids) if slide_ids is not None else len(presentation)
    presentation.insert(insertion, notes_master_ids)
    target.set_part("ppt/presentation.xml", _xml_bytes(presentation))
    return notes_master


def _first_theme_part(target: MutablePptxPackage) -> str:
    theme = next(
        (
            relationship.resolved_target
            for relationship in target.relationships
            if relationship.relationship_type.endswith("/theme")
            and relationship.resolved_target is not None
        ),
        None,
    )
    if theme is None:
        _invalid("Target deck has no theme for a notes master.")
    return theme


def _next_part_index(parts: dict[str, bytes], prefix: str) -> int:
    indices = []
    for name in parts:
        if not name.startswith(prefix):
            continue
        stem = posixpath.splitext(name)[0]
        suffix = stem[len(prefix):]
        if suffix.isdigit():
            indices.append(int(suffix))
    return max(indices, default=0) + 1


def _copy_part_graph(
    source: Any,
    target: MutablePptxPackage,
    source_part: str,
    mapping: dict[str, str],
    *,
    cross_deck: bool,
    source_root: str,
    existing_notes_master: str | None,
) -> str:
    destination = mapping.get(source_part)
    if destination is None:
        destination = _allocate_part_name(source_part, set(target.parts).union(mapping.values()))
        mapping[source_part] = destination
    if destination not in target.parts:
        target.set_part(destination, source.parts[source_part])

    relationships = source.part_rels(source_part)
    if not relationships:
        return destination
    rels_root = Element(RELS("Relationships"))
    for relationship in relationships:
        attributes = {
            "Id": relationship.relationship_id,
            "Type": relationship.relationship_type,
        }
        if relationship.target_mode == "External":
            attributes["Target"] = relationship.target
            attributes["TargetMode"] = "External"
            SubElement(rels_root, RELS("Relationship"), attributes)
            continue
        source_target = relationship.resolved_target
        if source_target is None:
            _invalid("Copied slide has an unresolved internal relationship.")
        relationship_kind = relationship.relationship_type.rsplit("/", 1)[-1]
        if source_target == source_root:
            destination_target = mapping[source_root]
        elif relationship_kind == "notesMaster" and existing_notes_master is not None:
            destination_target = existing_notes_master
            mapping.setdefault(source_target, existing_notes_master)
        elif not cross_deck and relationship_kind in _SHARED_SAME_DECK:
            destination_target = source_target
            mapping.setdefault(source_target, source_target)
        else:
            destination_target = mapping.get(source_target)
            if destination_target is None:
                destination_target = _allocate_part_name(
                    source_target,
                    set(target.parts).union(mapping.values()),
                )
                mapping[source_target] = destination_target
                _copy_part_graph(
                    source,
                    target,
                    source_target,
                    mapping,
                    cross_deck=cross_deck,
                    source_root=source_root,
                    existing_notes_master=existing_notes_master,
                )
        attributes["Target"] = posixpath.relpath(
            destination_target,
            posixpath.dirname(destination),
        )
        SubElement(rels_root, RELS("Relationship"), attributes)
    target.set_part(relationship_part_for(destination), _xml_bytes(rels_root))
    return destination


def _add_slide_to_presentation(
    target: MutablePptxPackage,
    slide_part: str,
    position: int,
) -> None:
    rels = target.xml("ppt/_rels/presentation.xml.rels")
    relationship_id = _next_relationship_id(rels, "rIdSlide")
    SubElement(
        rels,
        RELS("Relationship"),
        {
            "Id": relationship_id,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide",
            "Target": posixpath.relpath(slide_part, "ppt"),
        },
    )
    target.set_part("ppt/_rels/presentation.xml.rels", _xml_bytes(rels))

    presentation = target.xml("ppt/presentation.xml")
    slide_ids = presentation.find(P("sldIdLst"))
    if slide_ids is None:
        slide_ids = SubElement(presentation, P("sldIdLst"))
    numeric_ids = [int(node.attrib["id"]) for node in slide_ids if node.attrib.get("id", "").isdigit()]
    node = Element(
        P("sldId"),
        {"id": str(max(numeric_ids, default=255) + 1), R("id"): relationship_id},
    )
    slide_ids.insert(position - 1, node)
    target.set_part("ppt/presentation.xml", _xml_bytes(presentation))


def _add_imported_masters(
    target: MutablePptxPackage,
    source: Any,
    mapping: dict[str, str],
) -> None:
    imported_masters = [
        destination
        for source_part, destination in mapping.items()
        if source.content_type_for(source_part) == "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
        and destination != source_part
    ]
    imported_notes_masters = [
        destination
        for source_part, destination in mapping.items()
        if source.content_type_for(source_part) == "application/vnd.openxmlformats-officedocument.presentationml.notesMaster+xml"
        and destination not in target.source.parts
    ]
    if not imported_masters and not imported_notes_masters:
        return
    rels = target.xml("ppt/_rels/presentation.xml.rels")
    presentation = target.xml("ppt/presentation.xml")
    master_ids = presentation.find(P("sldMasterIdLst"))
    if master_ids is None:
        master_ids = Element(P("sldMasterIdLst"))
        presentation.insert(0, master_ids)
    numeric_ids = [int(node.attrib["id"]) for node in master_ids if node.attrib.get("id", "").isdigit()]
    next_master_id = max(numeric_ids, default=2_147_483_647) + 1
    for master_part in sorted(set(imported_masters)):
        relationship_id = _next_relationship_id(rels, "rIdImportedMaster")
        SubElement(
            rels,
            RELS("Relationship"),
            {
                "Id": relationship_id,
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
                "Target": posixpath.relpath(master_part, "ppt"),
            },
        )
        SubElement(
            master_ids,
            P("sldMasterId"),
            {"id": str(next_master_id), R("id"): relationship_id},
        )
        next_master_id += 1
    if imported_notes_masters and presentation.find(P("notesMasterIdLst")) is None:
        notes_master_part = sorted(set(imported_notes_masters))[0]
        relationship_id = _next_relationship_id(rels, "rIdImportedNotesMaster")
        SubElement(
            rels,
            RELS("Relationship"),
            {
                "Id": relationship_id,
                "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/notesMaster",
                "Target": posixpath.relpath(notes_master_part, "ppt"),
            },
        )
        notes_master_ids = Element(P("notesMasterIdLst"))
        SubElement(notes_master_ids, P("notesMasterId"), {R("id"): relationship_id})
        slide_ids = presentation.find(P("sldIdLst"))
        insertion = list(presentation).index(slide_ids) if slide_ids is not None else len(presentation)
        presentation.insert(insertion, notes_master_ids)
    target.set_part("ppt/_rels/presentation.xml.rels", _xml_bytes(rels))
    target.set_part("ppt/presentation.xml", _xml_bytes(presentation))


def _rewrite_content_types(
    target: MutablePptxPackage,
    *,
    removed: set[str],
    additions: dict[str, str],
) -> None:
    root = target.xml("[Content_Types].xml")
    removed_keys = {f"/{part}" for part in removed}
    for node in list(root):
        if node.tag == f"{{{CONTENT_TYPES_NS}}}Override" and node.attrib.get("PartName") in removed_keys:
            root.remove(node)
    defaults = {
        node.attrib.get("Extension", "").casefold(): node.attrib.get("ContentType", "")
        for node in root
        if node.tag == f"{{{CONTENT_TYPES_NS}}}Default"
    }
    overrides = {
        node.attrib.get("PartName", "")
        for node in root
        if node.tag == f"{{{CONTENT_TYPES_NS}}}Override"
    }
    for part, content_type in sorted(additions.items()):
        if not content_type:
            _invalid("Copied dependency lacks a content type.", part=part)
        extension = part.rsplit(".", 1)[-1].casefold() if "." in part.rsplit("/", 1)[-1] else ""
        if defaults.get(extension) == content_type:
            continue
        override = f"/{part}"
        if override not in overrides:
            SubElement(
                root,
                f"{{{CONTENT_TYPES_NS}}}Override",
                {"PartName": override, "ContentType": content_type},
            )
            overrides.add(override)
    target.set_part("[Content_Types].xml", _xml_bytes(root))


def _forward_dependencies(relationships: list[Any], root_part: str) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for relationship in relationships:
        if relationship.resolved_target is not None:
            adjacency.setdefault(relationship.source_part, set()).add(relationship.resolved_target)
    seen: set[str] = set()
    pending = [root_part]
    while pending:
        part = pending.pop()
        if part in seen:
            continue
        seen.add(part)
        pending.extend(adjacency.get(part, ()))
    return seen


def _root_reachable_without(
    relationships: list[Any],
    removed_presentation_relationship_id: str,
) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for relationship in relationships:
        if (
            relationship.source_part == "ppt/presentation.xml"
            and relationship.relationship_id == removed_presentation_relationship_id
        ):
            continue
        if relationship.resolved_target is not None:
            adjacency.setdefault(relationship.source_part, set()).add(relationship.resolved_target)
    seen: set[str] = set()
    pending = list(adjacency.get("", ()))
    while pending:
        part = pending.pop()
        if part in seen:
            continue
        seen.add(part)
        pending.extend(adjacency.get(part, ()))
    return seen


def _allocate_part_name(source_part: str, occupied: set[str]) -> str:
    directory, filename = posixpath.split(source_part)
    stem, extension = posixpath.splitext(filename)
    match = _TRAILING_NUMBER.match(stem)
    prefix = match.group(1) if match else f"{stem}_copy"
    index = 1
    while True:
        candidate = posixpath.join(directory, f"{prefix}{index}{extension}")
        if candidate not in occupied:
            return candidate
        index += 1


def _first_relationship_target(target: MutablePptxPackage, kind: str) -> str | None:
    return next(
        (
            relationship.resolved_target
            for relationship in target.part_rels("ppt/presentation.xml")
            if relationship.relationship_type.endswith(f"/{kind}")
        ),
        None,
    )


def _next_relationship_id(root: Element, prefix: str) -> str:
    used = {node.attrib.get("Id", "") for node in root}
    index = 1
    while f"{prefix}{index}" in used:
        index += 1
    return f"{prefix}{index}"


def _slide_at(slides: list[dict[str, Any]], position: int) -> dict[str, Any]:
    if position < 1 or position > len(slides):
        _invalid("Slide position is outside the current deck.", position=position, slides=len(slides))
    return slides[position - 1]


def _bounded_insert_position(value: int | None, maximum: int) -> int:
    position = maximum if value is None else value
    if position < 1 or position > maximum:
        _invalid("Slide insertion position is outside the target deck.", position=position, maximum=maximum)
    return position


def _xml_bytes(root: Element) -> bytes:
    return tostring(root, encoding="UTF-8", xml_declaration=True)


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
