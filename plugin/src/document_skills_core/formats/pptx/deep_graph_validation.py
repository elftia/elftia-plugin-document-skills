"""Deep bounded PresentationML part, relationship, and identifier validation."""

from collections import defaultdict, deque
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import CONTENT_TYPES, NS, PRESENTATION_MAIN, local_name

_RELATIONSHIP_ATTRIBUTES = {
    f"{{{NS['r']}}}embed",
    f"{{{NS['r']}}}id",
    f"{{{NS['r']}}}link",
}
_DRAWING_PART_PREFIXES = (
    "ppt/slideLayouts/",
    "ppt/slideMasters/",
    "ppt/slides/",
    "ppt/notesSlides/",
)
_TARGET_POLICIES = {
    "chart": ("ppt/charts/", "drawingml.chart+xml"),
    "image": ("ppt/media/", "image/"),
    "notesMaster": ("ppt/notesMasters/", "presentationml.notesMaster+xml"),
    "notesSlide": ("ppt/notesSlides/", "presentationml.notesSlide+xml"),
    "slide": ("ppt/slides/", "presentationml.slide+xml"),
    "slideLayout": ("ppt/slideLayouts/", "presentationml.slideLayout+xml"),
    "slideMaster": ("ppt/slideMasters/", "presentationml.slideMaster+xml"),
    "theme": ("ppt/theme/", "officedocument.theme+xml"),
}
_MAX_FAILURES = 128


def validate_part_graph(package: Any) -> dict[str, Any]:
    """Validate reachability and required PresentationML dependency chains."""
    failures: list[str] = []
    by_source: dict[str, list[Any]] = defaultdict(list)
    for relationship in package.relationships:
        by_source[relationship.source_part].append(relationship)
        if relationship.source_part and relationship.source_part not in package.parts:
            failures.append(f"relationship-source-missing:{relationship.source_part}")
        _validate_relationship_target(package, relationship, failures)

    _validate_content_types(package, failures)
    reachable = _reachable_parts(by_source)
    orphan_parts = sorted(_content_parts(package) - reachable)
    failures.extend(f"orphan-part:{part}" for part in orphan_parts)
    _validate_required_chains(package, by_source, failures)
    xml_relationship_references = _validate_xml_relationship_ids(
        package,
        by_source,
        failures,
    )
    drawing_ids = _validate_drawing_ids(package, failures)
    slide_ids = _validate_slide_ids(package, failures)
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PPTX deep part-graph validation failed.",
            details={"failures": failures[:_MAX_FAILURES]},
        )
    return {
        "content_parts": len(_content_parts(package)),
        "drawing_ids": drawing_ids,
        "internal_relationships": sum(
            relationship.target_mode == "Internal"
            for relationship in package.relationships
        ),
        "orphan_parts": 0,
        "reachable_parts": len(reachable),
        "slide_ids": slide_ids,
        "xml_relationship_references": xml_relationship_references,
    }


def _validate_content_types(package: Any, failures: list[str]) -> None:
    for part in sorted(_content_parts(package)):
        if package.content_type_for(part) is None:
            failures.append(f"content-type-missing:{part}")
    for declaration in sorted(package.content_types):
        if declaration.startswith("/") and declaration[1:] not in package.parts:
            failures.append(f"content-type-orphan:{declaration}")


def _reachable_parts(by_source: dict[str, list[Any]]) -> set[str]:
    reachable: set[str] = set()
    pending = deque(
        relationship.resolved_target
        for relationship in by_source.get("", [])
        if relationship.target_mode == "Internal"
        and relationship.resolved_target is not None
    )
    while pending:
        part = pending.popleft()
        if part in reachable:
            continue
        reachable.add(part)
        pending.extend(
            relationship.resolved_target
            for relationship in by_source.get(part, [])
            if relationship.target_mode == "Internal"
            and relationship.resolved_target is not None
            and relationship.resolved_target not in reachable
        )
    return reachable


def _content_parts(package: Any) -> set[str]:
    return {
        part
        for part in package.parts
        if part != CONTENT_TYPES and not part.endswith(".rels")
    }


def _validate_required_chains(
    package: Any,
    by_source: dict[str, list[Any]],
    failures: list[str],
) -> None:
    presentation = package.xml(PRESENTATION_MAIN)
    ordered_slide_targets: list[str] = []
    presentation_relationships = {
        relationship.relationship_id: relationship
        for relationship in by_source.get(PRESENTATION_MAIN, [])
    }
    slide_list = next(
        (node for node in presentation if local_name(node.tag) == "sldIdLst"),
        None,
    )
    for node in [] if slide_list is None else list(slide_list):
        relationship_id = node.attrib.get(f"{{{NS['r']}}}id", "")
        relationship = presentation_relationships.get(relationship_id)
        if (
            relationship is None
            or _terminal(relationship) != "slide"
            or relationship.resolved_target is None
        ):
            failures.append(f"slide-order-reference:{relationship_id or 'missing'}")
        else:
            ordered_slide_targets.append(relationship.resolved_target)
    if set(ordered_slide_targets) != set(package.slide_parts()):
        failures.append("slide-order-part-set")

    for part in package.slide_parts():
        _require_relationship_count(by_source, part, "slideLayout", 1, failures)
    for part in package.slide_layout_parts():
        _require_relationship_count(by_source, part, "slideMaster", 1, failures)
    for part in package.slide_master_parts():
        _require_relationship_count(by_source, part, "theme", 1, failures)
    for part in package.notes_slide_parts():
        _require_relationship_count(by_source, part, "notesMaster", 1, failures)
        _require_relationship_count(by_source, part, "slide", 1, failures)


def _require_relationship_count(
    by_source: dict[str, list[Any]],
    part: str,
    terminal: str,
    expected: int,
    failures: list[str],
) -> None:
    actual = sum(
        relationship.target_mode == "Internal" and _terminal(relationship) == terminal
        for relationship in by_source.get(part, [])
    )
    if actual != expected:
        failures.append(f"relationship-count:{part}:{terminal}:{actual}")


def _validate_relationship_target(
    package: Any,
    relationship: Any,
    failures: list[str],
) -> None:
    if relationship.target_mode != "Internal" or relationship.resolved_target is None:
        return
    terminal = _terminal(relationship)
    policy = _TARGET_POLICIES.get(terminal)
    if policy is None:
        return
    prefix, content_fragment = policy
    target = relationship.resolved_target
    content_type = package.content_type_for(target) or ""
    if not target.startswith(prefix) or content_fragment.casefold() not in content_type.casefold():
        failures.append(f"relationship-type-target:{relationship.source_part}:{relationship.relationship_id}")


def _validate_xml_relationship_ids(
    package: Any,
    by_source: dict[str, list[Any]],
    failures: list[str],
) -> int:
    references = 0
    for part in sorted(_content_parts(package)):
        content_type = (package.content_type_for(part) or "").casefold()
        if not (part.endswith(".xml") or content_type.endswith("+xml")):
            continue
        root = package.xml(part)
        relationship_ids = {
            relationship.relationship_id
            for relationship in by_source.get(part, [])
        }
        for node in root.iter():
            for name, value in node.attrib.items():
                if name not in _RELATIONSHIP_ATTRIBUTES or not value:
                    continue
                references += 1
                if value not in relationship_ids:
                    failures.append(f"xml-relationship-missing:{part}:{value}")
    return references


def _validate_drawing_ids(package: Any, failures: list[str]) -> int:
    total = 0
    for part in sorted(_content_parts(package)):
        if not part.startswith(_DRAWING_PART_PREFIXES) or not part.endswith(".xml"):
            continue
        identifiers, invalid, duplicate = _drawing_identifier_state(package.xml(part))
        total += len(identifiers)
        if invalid:
            failures.append(f"drawing-id-invalid:{part}")
        if duplicate:
            failures.append(f"drawing-id-duplicate:{part}")
    return total


def _drawing_identifier_state(root: Any) -> tuple[set[str], bool, bool]:
    """Return possible ids plus invalid/duplicate truth across every MC branch."""
    if local_name(root.tag) == "AlternateContent":
        branches = [
            child
            for child in list(root)
            if local_name(child.tag) in {"Choice", "Fallback"}
        ]
        common = [child for child in list(root) if child not in branches]
        common_ids, invalid, duplicate = _combined_identifier_state(common)
        possible = set(common_ids)
        for branch in branches:
            branch_ids, branch_invalid, branch_duplicate = _drawing_identifier_state(
                branch
            )
            invalid = invalid or branch_invalid
            duplicate = (
                duplicate
                or branch_duplicate
                or bool(common_ids.intersection(branch_ids))
            )
            possible.update(branch_ids)
        return possible, invalid, duplicate

    identifiers: set[str] = set()
    invalid = False
    duplicate = False
    if local_name(root.tag) == "cNvPr":
        value = root.attrib.get("id", "")
        identifiers.add(value)
        invalid = not value.isdigit() or int(value) <= 0
    child_ids, child_invalid, child_duplicate = _combined_identifier_state(list(root))
    duplicate = duplicate or child_duplicate or bool(identifiers.intersection(child_ids))
    identifiers.update(child_ids)
    return identifiers, invalid or child_invalid, duplicate


def _combined_identifier_state(nodes: list[Any]) -> tuple[set[str], bool, bool]:
    identifiers: set[str] = set()
    invalid = False
    duplicate = False
    for node in nodes:
        child_ids, child_invalid, child_duplicate = _drawing_identifier_state(node)
        duplicate = (
            duplicate
            or child_duplicate
            or bool(identifiers.intersection(child_ids))
        )
        invalid = invalid or child_invalid
        identifiers.update(child_ids)
    return identifiers, invalid, duplicate


def _validate_slide_ids(package: Any, failures: list[str]) -> int:
    root = package.xml(PRESENTATION_MAIN)
    identifiers = [
        node.attrib.get("id", "")
        for node in root.iter()
        if local_name(node.tag) == "sldId"
    ]
    if any(not value.isdigit() for value in identifiers):
        failures.append("slide-id-invalid")
    if len(identifiers) != len(set(identifiers)):
        failures.append("slide-id-duplicate")
    return len(identifiers)


def _terminal(relationship: Any) -> str:
    return relationship.relationship_type.rsplit("/", 1)[-1]
