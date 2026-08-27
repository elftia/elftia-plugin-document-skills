"""Inert inventory for advanced PresentationML objects and metadata."""

from typing import Any

from .constants import local_name

_AUDIO_EXTENSIONS = {".aac", ".m4a", ".mp3", ".wav", ".wma"}
_VIDEO_EXTENSIONS = {".avi", ".m4v", ".mov", ".mp4", ".mpeg", ".mpg", ".wmv"}
_DIAGRAM_TYPES = {
    "diagramcolors": "colors",
    "diagramdata": "data",
    "diagramdrawing": "drawing",
    "diagramlayout": "layout",
    "diagramquickstyle": "style",
    "diagramstyle": "style",
}


def project_advanced_inventory(
    package: Any,
    *,
    include_hashes: bool,
) -> dict[str, Any]:
    """Classify unsupported advanced objects without executing or editing them."""

    diagram_parts = _diagram_parts(package, include_hashes)
    diagram_relationships = _relationships(package, set(_DIAGRAM_TYPES))
    equations, animations, transitions = _slide_xml_features(package)
    audio = _media_parts(package, "audio", _AUDIO_EXTENSIONS, include_hashes)
    video = _media_parts(package, "video", _VIDEO_EXTENSIONS, include_hashes)
    ole = _ole_inventory(package, include_hashes)
    comments = _comment_parts(package, include_hashes)
    return {
        "inert_only": True,
        "mutation_supported": False,
        "smartart_diagrams": {
            "count": len(diagram_parts),
            "parts": diagram_parts,
            "relationships": diagram_relationships,
        },
        "equations": {
            "count": sum(item["count"] for item in equations),
            "parts": equations,
        },
        "audio": {
            "count": len(audio),
            "parts": audio,
            "playback_permitted": False,
        },
        "video": {
            "count": len(video),
            "parts": video,
            "playback_permitted": False,
        },
        "ole": {
            "count": len(ole),
            "objects": ole,
            "activation_permitted": False,
        },
        "animations": {
            "count": len(animations),
            "slides": animations,
            "execution_permitted": False,
        },
        "transitions": {
            "count": len(transitions),
            "slides": transitions,
            "execution_permitted": False,
        },
        "comments": {
            "count": len(comments),
            "parts": comments,
            "mutation_supported": False,
        },
    }


def _diagram_parts(package: Any, include_hashes: bool) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for name in sorted(package.parts):
        if name.endswith(".rels") or "/_rels/" in name:
            continue
        content_type = package.content_type_for(name) or ""
        if not name.startswith("ppt/diagrams/") and "drawingml.diagram" not in content_type:
            continue
        kind = next(
            (
                value
                for token, value in _DIAGRAM_TYPES.items()
                if token in content_type.casefold()
            ),
            "unknown",
        )
        records.append(_part_record(package, name, kind, include_hashes))
    return records


def _relationships(package: Any, terminal_types: set[str]) -> list[dict[str, Any]]:
    records = []
    for relationship in package.relationships:
        terminal = relationship.relationship_type.rsplit("/", 1)[-1].casefold()
        if terminal not in terminal_types:
            continue
        records.append({
            "id": relationship.relationship_id,
            "source_part": relationship.source_part,
            "target": relationship.resolved_target or relationship.target,
            "target_mode": relationship.target_mode,
            "type": terminal,
        })
    return sorted(records, key=lambda item: (item["source_part"], item["id"]))


def _slide_xml_features(
    package: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    equations: list[dict[str, Any]] = []
    animations: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    for slide_number, part in enumerate(package.slide_parts(), start=1):
        root = package.xml(part)
        equation_count = sum(1 for node in root.iter() if local_name(node.tag) == "oMath")
        if equation_count:
            equations.append({"count": equation_count, "part": part, "slide": slide_number})
        timing = next((node for node in root if local_name(node.tag) == "timing"), None)
        if timing is not None:
            animations.append({
                "node_count": sum(1 for _node in timing.iter()),
                "part": part,
                "slide": slide_number,
            })
        transition = next(
            (node for node in root if local_name(node.tag) == "transition"),
            None,
        )
        if transition is not None:
            child = next(iter(transition), None)
            transitions.append({
                "attributes": dict(sorted(transition.attrib.items())),
                "kind": "unspecified" if child is None else local_name(child.tag),
                "part": part,
                "slide": slide_number,
            })
    return equations, animations, transitions


def _media_parts(
    package: Any,
    media_type: str,
    extensions: set[str],
    include_hashes: bool,
) -> list[dict[str, Any]]:
    records = []
    for name in package.media_parts():
        content_type = (package.content_type_for(name) or "").casefold()
        suffix = "." + name.rsplit(".", 1)[-1].casefold() if "." in name else ""
        if not content_type.startswith(f"{media_type}/") and suffix not in extensions:
            continue
        records.append(_part_record(package, name, media_type, include_hashes))
    return records


def _ole_inventory(package: Any, include_hashes: bool) -> list[dict[str, Any]]:
    records = []
    terminals = {"oleobject", "package"}
    for relationship in package.relationships:
        terminal = relationship.relationship_type.rsplit("/", 1)[-1].casefold()
        if terminal not in terminals:
            continue
        target = relationship.resolved_target
        record: dict[str, Any] = {
            "id": relationship.relationship_id,
            "source_part": relationship.source_part,
            "target": target or relationship.target,
            "target_mode": relationship.target_mode,
            "type": terminal,
        }
        if target in package.parts:
            record.update(_part_record(package, target, terminal, include_hashes))
            record["target"] = target
        records.append(record)
    return sorted(records, key=lambda item: (item["source_part"], item["id"]))


def _comment_parts(package: Any, include_hashes: bool) -> list[dict[str, Any]]:
    prefixes = (
        "ppt/comments/",
        "ppt/commentAuthors.xml",
        "ppt/threadedComments/",
        "ppt/persons/",
    )
    return [
        _part_record(package, name, "comments", include_hashes)
        for name in sorted(package.parts)
        if name.startswith(prefixes)
    ]


def _part_record(
    package: Any,
    name: str,
    kind: str,
    include_hashes: bool,
) -> dict[str, Any]:
    record = {
        "bytes": len(package.parts[name]),
        "content_type": package.content_type_for(name) or "",
        "kind": kind,
        "part": name,
    }
    if include_hashes:
        record["sha256"] = package.part_hashes[name]
    return record
