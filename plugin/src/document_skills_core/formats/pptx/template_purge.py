"""Plan and independently verify physical purge of unselected template content."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import NS
from .deep_validation import validate_deep_package
from .mapping import map_slides
from .package import OpcPackage
from .slide_graph import relationship_part_for

_P = NS["p"]
_R = NS["r"]
_SHARED_KINDS = {"notesMaster", "slideLayout", "slideMaster", "theme"}
_IMPLICIT_PRIVATE_KINDS = {"comment", "comments", "commentAuthors", "notesSlide"}


@dataclass(frozen=True)
class TemplatePurgePlan:
    unselected_slides: tuple[str, ...]
    private_parts: tuple[dict[str, Any], ...]
    selected_hashes: frozenset[str]


def plan_template_purge(
    source: OpcPackage,
    selected_slide_ids: set[str],
) -> TemplatePurgePlan:
    slides = _slides_by_id(source)
    unknown = selected_slide_ids - set(slides)
    if unknown:
        _invalid("Requested source slide id is absent from the template.", slides=sorted(unknown))
    selected_parts = {slides[item] for item in selected_slide_ids}
    unselected = sorted(set(slides) - selected_slide_ids)
    unselected_private = set().union(
        *(_private_closure(source, slides[item]) for item in unselected)
    ) if unselected else set()
    selected_closure = set().union(*(
        _private_closure(
            source,
            item,
            referenced_only=True,
            unselected_private=unselected_private,
        )
        for item in selected_parts
    ))
    selected_hashes = frozenset(
        source.part_hashes[item]
        for item in selected_closure
        if item in source.part_hashes
    )
    records: dict[str, dict[str, Any]] = {}
    for slide_id in unselected:
        for part in sorted(_private_closure(source, slides[slide_id]) - selected_closure):
            if part not in source.parts:
                continue
            digest = source.part_hashes[part]
            if digest in selected_hashes:
                continue
            records[part] = {
                "bytes": len(source.parts[part]),
                "part": part,
                "sha256": digest,
                "source_slide_id": slide_id,
            }
    return TemplatePurgePlan(
        unselected_slides=tuple(unselected),
        private_parts=tuple(records[key] for key in sorted(records)),
        selected_hashes=selected_hashes,
    )


def validate_template_purge(
    candidate_path: Path,
    plan: TemplatePurgePlan,
    *,
    output_slide_ids: list[str],
) -> dict[str, Any]:
    candidate = OpcPackage.open(candidate_path)
    residue = sorted(
        record["part"]
        for record in plan.private_parts
        if not record["part"].endswith(".rels")
        if record["part"] in candidate.parts
        and candidate.part_hashes[record["part"]] == record["sha256"]
    )
    candidate_hashes = set(candidate.part_hashes.values())
    recoverable = sorted(
        record["sha256"]
        for record in plan.private_parts
        if not record["part"].endswith(".rels")
        if record["sha256"] in candidate_hashes
    )
    actual_slide_ids = sorted(_slides_by_id(candidate))
    expected_slide_ids = sorted(output_slide_ids)
    if residue or recoverable or actual_slide_ids != expected_slide_ids:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Unselected template content remains recoverable from the candidate ZIP.",
            status="failed",
            details={
                "actual_slide_ids": actual_slide_ids,
                "expected_slide_ids": expected_slide_ids,
                "part_residue": residue[:64],
                "recoverable_hashes": recoverable[:64],
            },
        )
    return {
        "deep_graph": validate_deep_package(candidate_path),
        "private_parts_absent": True,
        "purged_private_parts": len(plan.private_parts),
        "reopen": "passed",
        "unselected_slide_ids": list(plan.unselected_slides),
    }


def _slides_by_id(package: Any) -> dict[str, str]:
    result: dict[str, str] = {}
    for slide in map_slides(package):
        part = slide.get("part")
        if part is None:
            continue
        root = package.xml(part)
        common = root.find(f"{{{_P}}}cSld")
        slide_id = "" if common is None else common.attrib.get("name", "")
        if not slide_id:
            _invalid("Template slide lacks a stable A-Contract address.", part=part)
        if slide_id in result:
            _invalid("Template slide stable addresses are duplicated.", slide_id=slide_id)
        result[slide_id] = part
    return result


def template_private_closure(package: Any, slide_part: str) -> set[str]:
    """Return the complete non-shared graph copied with one template slide."""

    return _private_closure(package, slide_part)


def _private_closure(
    package: Any,
    slide_part: str,
    *,
    referenced_only: bool = False,
    unselected_private: set[str] | None = None,
) -> set[str]:
    visited: set[str] = set()
    pending = [slide_part]
    excluded = unselected_private or set()
    while pending:
        part = pending.pop()
        if part in visited:
            continue
        visited.add(part)
        rels_part = relationship_part_for(part)
        if rels_part in package.parts:
            visited.add(rels_part)
        referenced = _referenced_relationship_ids(package, part) if referenced_only else set()
        for relationship in package.part_rels(part):
            if relationship.target_mode == "External":
                continue
            kind = relationship.relationship_type.rsplit("/", 1)[-1]
            target = relationship.resolved_target
            if kind in _SHARED_KINDS or target is None:
                continue
            if referenced_only and relationship.relationship_id not in referenced:
                if kind not in _IMPLICIT_PRIVATE_KINDS or target in excluded:
                    continue
            pending.append(target)
    return visited


def _referenced_relationship_ids(package: Any, part: str) -> set[str]:
    content_type = package.content_type_for(part) or ""
    if not (content_type.endswith("+xml") or content_type in {"application/xml", "text/xml"}):
        return set()
    try:
        root = package.xml(part)
    except (DocumentSkillsError, KeyError, ValueError):
        return set()
    prefix = f"{{{_R}}}"
    return {
        value
        for element in root.iter()
        for attribute, value in element.attrib.items()
        if attribute.startswith(prefix) and value
    }


def _invalid(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        message,
        status="invalid_request",
        details=details,
    )
