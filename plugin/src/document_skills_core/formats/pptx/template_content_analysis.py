"""Bounded, deterministic template content analysis for inspect and promotion."""

from __future__ import annotations

from collections.abc import Iterator
from collections import Counter
import re
from typing import Any

from .constants import MAX_SHAPES_PER_SLIDE, NS, local_name
from .mapping import map_slides
from .object_xml import (
    drawable_elements,
    non_visual_properties,
    object_type,
    slide_shape_tree,
)
from .package import OpcPackage
from .template_content_metrics import (
    content_capacity_finding,
    content_hierarchy_finding,
    group_child_transform,
    object_frame,
)
from .template_content_fonts import (
    resolved_font_sizes,
    slide_font_context,
)
from .template_descriptor import TemplateDescriptor

_A_TEXT = f"{{{NS['a']}}}t"
_PLACEHOLDER = re.compile(r"\{\{[^{}]+\}\}|\[placeholder\]|lorem ipsum|\bTODO\b", re.I)
_PROMOTIONAL = re.compile(r"buy this template|download the full template|template marketplace", re.I)
_NOTES_LEAK = re.compile(r"speaker only|do not share|internal script", re.I)

MAX_CONTENT_LINT_FINDINGS = 64
MAX_CONTENT_LINT_OBJECTS = 10_000
MAX_CONTENT_LINT_CHARACTERS = 1_000_000


def inspect_template_content(
    candidate: Any,
    *,
    descriptor: TemplateDescriptor | None = None,
    output_object_sources: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Return a non-mutating content report; callers decide whether errors block."""

    package = candidate if isinstance(candidate, OpcPackage) else OpcPackage.open(candidate)
    slots = _descriptor_slots(descriptor, output_object_sources)
    findings: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    metrics = {"characters": 0, "objects": 0, "slides": 0}
    truncated = False
    exhausted = False
    for slide in map_slides(package):
        part = slide.get("part")
        if part is None:
            continue
        metrics["slides"] += 1
        records: list[dict[str, Any]] = []
        root = package.xml(part)
        font_context = slide_font_context(package, slide)
        elements = []
        for element in _content_elements(slide_shape_tree(root)):
            elements.append(element)
            if len(elements) > MAX_SHAPES_PER_SLIDE:
                break
        if len(elements) > MAX_SHAPES_PER_SLIDE:
            truncated = True
            _record_finding(
                findings,
                counts,
                {
                    "actual_shapes_at_least": len(elements),
                    "code": "content-lint-shape-limit",
                    "maximum_shapes": MAX_SHAPES_PER_SLIDE,
                    "part": part,
                    "severity": "error",
                    "slide": slide["number"],
                },
            )
        for element, transform in elements[:MAX_SHAPES_PER_SLIDE]:
            if metrics["objects"] >= MAX_CONTENT_LINT_OBJECTS:
                exhausted = True
                break
            metrics["objects"] += 1
            if local_name(element.tag) == "grpSp":
                continue
            record = _text_record(element, slots, font_context, transform)
            if record is None:
                continue
            metrics["characters"] += len(record["text"])
            if metrics["characters"] > MAX_CONTENT_LINT_CHARACTERS:
                exhausted = True
                break
            records.append(record)
            for finding in _text_findings(record, part, slide["number"]):
                truncated |= _record_finding(findings, counts, finding)
            capacity = content_capacity_finding(record, part, slide["number"])
            if capacity is not None:
                truncated |= _record_finding(findings, counts, capacity)
        if exhausted:
            break
        hierarchy = content_hierarchy_finding(records, part, slide["number"])
        if hierarchy is not None:
            truncated |= _record_finding(findings, counts, hierarchy)
        notes = slide.get("notes")
        notes_part = None if notes is None else notes.get("part")
        if notes_part:
            for text in _part_text(package, notes_part):
                metrics["characters"] += len(text)
                if metrics["characters"] > MAX_CONTENT_LINT_CHARACTERS:
                    exhausted = True
                    break
                if _NOTES_LEAK.search(text):
                    truncated |= _record_finding(
                        findings,
                        counts,
                        _finding("speaker-notes-leak", notes_part, slide["number"], text),
                    )
        if exhausted:
            break
    if exhausted:
        truncated = True
        _record_finding(
            findings,
            counts,
            {
                "code": "content-lint-resource-limit",
                "severity": "error",
                "metrics": dict(metrics),
            },
        )
    error_count = sum(counts.values())
    return {
        "error_count": error_count,
        "finding_count": error_count,
        "findings": findings,
        "limits": {
            "max_characters": MAX_CONTENT_LINT_CHARACTERS,
            "max_findings": MAX_CONTENT_LINT_FINDINGS,
            "max_objects": MAX_CONTENT_LINT_OBJECTS,
            "max_shapes_per_slide": MAX_SHAPES_PER_SLIDE,
        },
        "metrics": metrics,
        "mutation_authorized": False,
        "status": "failed" if error_count else "passed",
        "summary": dict(sorted(counts.items())),
        "truncated": truncated,
    }


def _descriptor_slots(
    descriptor: TemplateDescriptor | None,
    output_object_sources: dict[str, str] | None,
) -> dict[str, dict[str, Any]]:
    if descriptor is None:
        return {}
    slots = {
        slot["sourceObjectId"]: slot
        for slot in descriptor.semantic_slots["slots"]
    }
    for output_id, source_id in (output_object_sources or {}).items():
        slot = slots.get(source_id)
        if slot is not None:
            slots[output_id] = slot
    return slots


def _text_record(
    element: Any,
    slots: dict[str, dict[str, Any]],
    font_context: dict[str, Any],
    transform: tuple[float, float, float, float],
) -> dict[str, Any] | None:
    paragraphs = [
        "".join(node.text or "" for node in paragraph.iter(_A_TEXT))
        for paragraph in element.iter()
        if local_name(paragraph.tag) == "p"
    ]
    visible_paragraphs = [item for item in paragraphs if item]
    text = "\n".join(visible_paragraphs)
    if not text:
        text = "".join(node.text or "" for node in element.iter(_A_TEXT))
    if not text:
        return None
    properties = non_visual_properties(element)
    name = properties.attrib.get("name", "")
    slot = slots.get(name)
    placeholder = next(
        (node for node in element.iter() if local_name(node.tag) == "ph"),
        None,
    )
    return {
        "font_sizes": resolved_font_sizes(
            element,
            context=font_context,
            slot=slot,
        ),
        "frame": object_frame(element, transform),
        "kind": object_type(element),
        "name": name,
        "placeholder_role": None if placeholder is None else placeholder.attrib.get("type", "body"),
        "paragraphs": visible_paragraphs or [text],
        "shape_id": properties.attrib.get("id", ""),
        "slot": slot,
        "text": text,
    }


def _text_findings(
    record: dict[str, Any],
    part: str,
    slide_number: int,
) -> list[dict[str, Any]]:
    text = record["text"]
    findings = []
    for code, pattern in (
        ("placeholder-content", _PLACEHOLDER),
        ("promotional-content", _PROMOTIONAL),
    ):
        if pattern.search(text):
            findings.append(_finding(code, part, slide_number, text, record))
    if any(item.strip() in {"...", "…"} for item in record["paragraphs"]):
        findings.append(_finding("ellipsis-content", part, slide_number, text, record))
    return findings


def _part_text(package: OpcPackage, part: str) -> list[str]:
    root = package.xml(part)
    paragraphs = [
        "".join(node.text or "" for node in paragraph.iter(_A_TEXT))
        for paragraph in root.iter()
        if local_name(paragraph.tag) == "p"
    ]
    returned = [item for item in paragraphs if item]
    if returned:
        return returned
    text = "".join(node.text or "" for node in root.iter(_A_TEXT))
    return [text] if text else []


def _content_elements(
    tree: Any,
    transform: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 0.0),
) -> Iterator[tuple[Any, tuple[float, float, float, float]]]:
    stack = [(iter(drawable_elements(tree)), transform)]
    while stack:
        iterator, current_transform = stack[-1]
        try:
            element = next(iterator)
        except StopIteration:
            stack.pop()
            continue
        yield element, current_transform
        if local_name(element.tag) == "grpSp":
            child_transform = group_child_transform(element, current_transform)
            stack.append((iter(drawable_elements(element)), child_transform))


def _finding(
    code: str,
    part: str,
    slide_number: int,
    text: str,
    record: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = {
        "code": code,
        "part": part,
        "sample": text[:80],
        "severity": "error",
        "slide": slide_number,
    }
    if record is not None:
        result.update({"name": record["name"], "shape_id": record["shape_id"]})
    return result


def _record_finding(
    findings: list[dict[str, Any]],
    counts: Counter[str],
    finding: dict[str, Any],
) -> bool:
    counts[finding["code"]] += 1
    if len(findings) < MAX_CONTENT_LINT_FINDINGS:
        findings.append(finding)
        return False
    return True
