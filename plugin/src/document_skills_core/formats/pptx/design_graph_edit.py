"""Native PresentationML master, layout, and theme graph mutations."""

import posixpath
from typing import Any
from xml.etree.ElementTree import Element, SubElement, fromstring

from .constants import NS, PRESENTATION_MAIN
from .design_graph_xml import (
    build_layout,
    layout_relationships,
    master_relationships,
    xml_bytes,
)
from .design_graph_support import (
    attach_layout,
    detach_layout,
    invalid,
    register_master,
    remove_master_registration,
    remove_parts,
    require_part,
    slide_dimensions,
    validate_layout_frames,
)
from .mutation import MutablePptxPackage
from .scaffold import _build_slide_master, _build_theme
from .slide_graph import (
    _add_imported_masters,
    _allocate_part_name,
    _copy_part_graph,
    _forward_dependencies,
    _next_relationship_id,
    _rewrite_content_types,
    _root_reachable_without,
    relationship_part_for,
)

_P = NS["p"]
_RELS = NS["rels"]
_MASTER_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"
_LAYOUT_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"
_THEME_TYPE = "application/vnd.openxmlformats-officedocument.theme+xml"


def P(tag: str) -> str:
    return f"{{{_P}}}{tag}"


def RELS(tag: str) -> str:
    return f"{{{_RELS}}}{tag}"


def apply_design_edit(
    target: MutablePptxPackage,
    edit: dict[str, Any],
) -> dict[str, Any]:
    edit_type = edit["type"]
    if edit_type == "master_add":
        return _add_master(target, edit["master"])
    if edit_type == "master_copy":
        return _copy_master(target, edit["master"])
    if edit_type == "master_delete":
        return _delete_master(target, edit["master"])
    if edit_type == "layout_add":
        return _add_layout(target, edit["master"], edit["layout"])
    if edit_type == "layout_copy":
        return _copy_layout(target, edit["layout"], edit["master"])
    if edit_type == "layout_delete":
        return _delete_layout(target, edit["layout"])
    return _update_theme(target, edit["master"], edit["theme"])


def _add_master(target: MutablePptxPackage, value: dict[str, Any]) -> dict[str, Any]:
    width, height = slide_dimensions(target)
    validate_layout_frames(value["layout"], width, height)
    occupied = set(target.parts)
    master = _allocate_part_name("ppt/slideMasters/slideMaster1.xml", occupied)
    occupied.add(master)
    layout = _allocate_part_name("ppt/slideLayouts/slideLayout1.xml", occupied)
    occupied.add(layout)
    theme = _allocate_part_name("ppt/theme/theme1.xml", occupied)

    master_root = fromstring(_build_slide_master(1, width, height, value["theme"]))
    common = master_root.find(P("cSld"))
    if common is not None:
        common.set("name", value["name"])
    target.set_part(master, xml_bytes(master_root))
    target.set_part(layout, build_layout(value["layout"], width, height))
    target.set_part(theme, _build_theme(value["theme"]))
    target.set_part(
        relationship_part_for(master),
        master_relationships(master, layout, theme),
    )
    target.set_part(
        relationship_part_for(layout),
        layout_relationships(layout, master),
    )
    register_master(target, master)
    additions = {master: _MASTER_TYPE, layout: _LAYOUT_TYPE, theme: _THEME_TYPE}
    _rewrite_content_types(target, removed=set(), additions=additions)
    return {
        "added_parts": sorted([
            master,
            relationship_part_for(master),
            layout,
            relationship_part_for(layout),
            theme,
        ]),
        "layout_part": layout,
        "master_part": master,
        "theme_part": theme,
        "type": "master_add",
    }


def _copy_master(target: MutablePptxPackage, source_master: str) -> dict[str, Any]:
    require_part(target, source_master, _MASTER_TYPE)
    destination = _allocate_part_name(source_master, set(target.parts))
    mapping = {source_master: destination}
    _copy_part_graph(
        target,
        target,
        source_master,
        mapping,
        cross_deck=True,
        source_root=source_master,
        existing_notes_master=None,
    )
    _add_imported_masters(target, target, mapping)
    additions = {
        target_part: target.content_type_for(source_part) or ""
        for source_part, target_part in mapping.items()
        if target_part not in target.source.parts and not target_part.endswith(".rels")
    }
    _rewrite_content_types(target, removed=set(), additions=additions)
    return {
        "dependencies": [
            {"source_part": source, "target_part": copied}
            for source, copied in sorted(mapping.items())
        ],
        "master_part": destination,
        "source_master_part": source_master,
        "type": "master_copy",
    }


def _delete_master(target: MutablePptxPackage, master: str) -> dict[str, Any]:
    require_part(target, master, _MASTER_TYPE)
    registered_masters = [
        relationship
        for relationship in target.part_rels(PRESENTATION_MAIN)
        if relationship.relationship_type.endswith("/slideMaster")
    ]
    if len(registered_masters) <= 1:
        invalid("A presentation must retain at least one slide master.")
    layouts = {
        relationship.source_part
        for relationship in target.relationships
        if relationship.relationship_type.endswith("/slideMaster")
        and relationship.resolved_target == master
        and relationship.source_part.startswith("ppt/slideLayouts/")
    }
    used = sorted({
        relationship.source_part
        for relationship in target.relationships
        if relationship.relationship_type.endswith("/slideLayout")
        and relationship.resolved_target in layouts
        and relationship.source_part.startswith("ppt/slides/")
    })
    if used:
        invalid("Cannot delete a master whose layouts are used by slides.", slides=used)
    presentation_relationship = next(
        (
            relationship
            for relationship in target.part_rels(PRESENTATION_MAIN)
            if relationship.relationship_type.endswith("/slideMaster")
            and relationship.resolved_target == master
        ),
        None,
    )
    if presentation_relationship is None:
        invalid("Selected master is not registered by the presentation.", master=master)
    candidates = _forward_dependencies(target.relationships, master)
    reachable = _root_reachable_without(
        target.relationships,
        presentation_relationship.relationship_id,
    )
    removable = {part for part in candidates if part not in reachable}
    removable.add(master)
    remove_master_registration(target, presentation_relationship.relationship_id)
    removed = remove_parts(target, removable)
    _rewrite_content_types(target, removed=removed, additions={})
    return {"master_part": master, "removed_parts": sorted(removed), "type": "master_delete"}


def _add_layout(
    target: MutablePptxPackage,
    master: str,
    value: dict[str, Any],
) -> dict[str, Any]:
    require_part(target, master, _MASTER_TYPE)
    width, height = slide_dimensions(target)
    validate_layout_frames(value, width, height)
    layout = _allocate_part_name("ppt/slideLayouts/slideLayout1.xml", set(target.parts))
    target.set_part(layout, build_layout(value, width, height))
    target.set_part(relationship_part_for(layout), layout_relationships(layout, master))
    attach_layout(target, master, layout)
    _rewrite_content_types(target, removed=set(), additions={layout: _LAYOUT_TYPE})
    return {
        "layout_part": layout,
        "master_part": master,
        "placeholders": len(value["placeholders"]),
        "type": "layout_add",
    }


def _copy_layout(
    target: MutablePptxPackage,
    source_layout: str,
    master: str,
) -> dict[str, Any]:
    require_part(target, source_layout, _LAYOUT_TYPE)
    require_part(target, master, _MASTER_TYPE)
    layout = _allocate_part_name(source_layout, set(target.parts))
    target.set_part(layout, target.parts[source_layout])
    source_rels = relationship_part_for(source_layout)
    rels = (
        target.xml(source_rels)
        if source_rels in target.parts
        else Element(RELS("Relationships"))
    )
    found_master = False
    for node in rels:
        if node.attrib.get("Type", "").endswith("/slideMaster"):
            node.set("Target", posixpath.relpath(master, posixpath.dirname(layout)))
            found_master = True
    if not found_master:
        SubElement(rels, RELS("Relationship"), {
            "Id": _next_relationship_id(rels, "rIdMaster"),
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster",
            "Target": posixpath.relpath(master, posixpath.dirname(layout)),
        })
    target.set_part(relationship_part_for(layout), xml_bytes(rels))
    attach_layout(target, master, layout)
    _rewrite_content_types(target, removed=set(), additions={layout: _LAYOUT_TYPE})
    return {
        "layout_part": layout,
        "master_part": master,
        "source_layout_part": source_layout,
        "type": "layout_copy",
    }


def _delete_layout(target: MutablePptxPackage, layout: str) -> dict[str, Any]:
    require_part(target, layout, _LAYOUT_TYPE)
    used = sorted({
        relationship.source_part
        for relationship in target.relationships
        if relationship.relationship_type.endswith("/slideLayout")
        and relationship.resolved_target == layout
        and relationship.source_part.startswith("ppt/slides/")
    })
    if used:
        invalid("Cannot delete a layout used by slides.", slides=used)
    master_relationship = next(
        (
            relationship
            for relationship in target.part_rels(layout)
            if relationship.relationship_type.endswith("/slideMaster")
        ),
        None,
    )
    if master_relationship is None or master_relationship.resolved_target is None:
        invalid("Selected layout has no master inheritance relationship.", layout=layout)
    master = master_relationship.resolved_target
    master_layouts = [
        item
        for item in target.part_rels(master)
        if item.relationship_type.endswith("/slideLayout")
    ]
    if len(master_layouts) <= 1:
        invalid("A slide master must retain at least one layout.", master=master)
    relationship = next(
        (item for item in master_layouts if item.resolved_target == layout),
        None,
    )
    if relationship is None:
        invalid("Master does not register the selected layout.", layout=layout, master=master)
    detach_layout(target, master, relationship.relationship_id)
    removed = remove_parts(target, {layout})
    _rewrite_content_types(target, removed=removed, additions={})
    return {"layout_part": layout, "master_part": master, "removed_parts": sorted(removed), "type": "layout_delete"}


def _update_theme(
    target: MutablePptxPackage,
    master: str,
    theme_value: dict[str, Any],
) -> dict[str, Any]:
    require_part(target, master, _MASTER_TYPE)
    relationship = next(
        (
            item
            for item in target.part_rels(master)
            if item.relationship_type.endswith("/theme")
        ),
        None,
    )
    if relationship is None or relationship.resolved_target is None:
        invalid("Selected master has no theme relationship.", master=master)
    theme = relationship.resolved_target
    shared = sum(
        item.resolved_target == theme and item.relationship_type.endswith("/theme")
        for item in target.relationships
    ) > 1
    if shared:
        theme = _allocate_part_name(theme, set(target.parts))
        rels = target.xml(relationship_part_for(master))
        for node in rels:
            if node.attrib.get("Id") == relationship.relationship_id:
                node.set("Target", posixpath.relpath(theme, posixpath.dirname(master)))
        target.set_part(relationship_part_for(master), xml_bytes(rels))
    target.set_part(theme, _build_theme(theme_value))
    _rewrite_content_types(
        target,
        removed=set(),
        additions={theme: _THEME_TYPE} if theme not in target.source.parts else {},
    )
    return {
        "clone_on_write": shared,
        "master_part": master,
        "theme_part": theme,
        "theme": {
            "effects": theme_value["effects"],
            "fonts": theme_value["fonts"],
            "name": theme_value["name"],
            "palette": theme_value["palette"],
        },
        "type": "theme_update",
    }
