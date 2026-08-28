"""Staged-model preflight and final composite assertions for PDF edits."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .content_streams import extract_content_stream, walk_text_operators
from .edit_form_semantics import assert_form_semantics
from .mapping import map_annotations
from .object_model import PdfObjectModel, parse_pdf
from .page_tree import PageInfo, walk_pages
from .watermark_expectations import (
    new_page_watermark_state,
    PageWatermarkState,
    plan_watermark_expectation,
)
from .watermark_semantics import assert_watermarks


@dataclass
class _PageExpectation:
    media_box: tuple[float, float, float, float]
    crop_box: tuple[float, float, float, float] | None
    bleed_box: tuple[float, float, float, float] | None
    trim_box: tuple[float, float, float, float] | None
    art_box: tuple[float, float, float, float] | None
    rotation: int
    watermark_state: PageWatermarkState
    annotations: list[dict[str, Any]] = field(default_factory=list)
    redacted_text: set[str] = field(default_factory=set)


@dataclass
class _EditExpectation:
    pages: list[_PageExpectation]
    form_values: dict[str, Any] = field(default_factory=dict)
    flattened_fields: set[str] = field(default_factory=set)
    counts: dict[str, int] = field(default_factory=dict)
    watermark_baselines_valid: bool = True


def preflight_edit_primitive(
    model: PdfObjectModel,
    primitive: dict[str, Any],
) -> None:
    """Reject page selections against the current staged document model."""
    pages = walk_pages(model)
    page_count = len(pages)
    primitive_type = primitive["type"]
    if primitive_type == "split":
        ranges = primitive["page_ranges"]
        invalid = [
            [start, end]
            for start, end in ranges
            if start > end or end > page_count
        ]
        selected = {
            number
            for start, end in ranges
            if start <= end
            for number in range(start, end + 1)
            if number <= page_count
        }
        if invalid or not selected:
            _invalid_pages(primitive_type, page_count, invalid or ranges)
        return
    if primitive_type == "page_insert":
        if primitive["at"] > page_count + 1:
            _invalid_pages(primitive_type, page_count, [primitive["at"]])
        return
    selected = _selected_pages(primitive)
    if selected is None:
        return
    outside = sorted({number for number in selected if number > page_count})
    if outside:
        _invalid_pages(primitive_type, page_count, outside)


def edit_semantic_assertion(
    source: Path,
    primitives: list[dict[str, Any]],
    operation_result: dict[str, Any],
    watermark_stage_hashes: object,
    watermark_source_objects: object,
) -> Callable[[Path], dict[str, Any]]:
    """Build the mandatory final assertion from source state and requests."""
    expectation = _initial_expectation(parse_pdf(source))
    for primitive_index, primitive in enumerate(primitives):
        _apply_expectation(
            expectation,
            primitive,
            primitive_index,
            watermark_source_objects,
        )

    def assert_candidate(candidate: Path) -> dict[str, Any]:
        return _assert_candidate(
            parse_pdf(candidate),
            expectation,
            operation_result,
            primitives,
            watermark_stage_hashes,
        )

    return assert_candidate


def _initial_expectation(model: PdfObjectModel) -> _EditExpectation:
    pages = walk_pages(model)
    annotations: dict[int, list[dict[str, Any]]] = {
        page.page_number: [] for page in pages
    }
    for item in map_annotations(model, pages):
        if item.subtype != "/Text":
            continue
        annotations[item.page].append({
            "subtype": item.subtype,
            "rectangle": item.rectangle,
            "contents": item.contents,
            "title": item.title,
            "color": item.color,
            "action_kind": item.action_kind,
        })
    return _EditExpectation([
        _PageExpectation(
            page.media_box,
            page.crop_box,
            page.bleed_box,
            page.trim_box,
            page.art_box,
            page.rotation,
            new_page_watermark_state(model, page),
            annotations=annotations[page.page_number],
        )
        for page in pages
    ])


def _apply_expectation(
    expected: _EditExpectation,
    primitive: dict[str, Any],
    primitive_index: int,
    watermark_source_objects: object,
) -> None:
    primitive_type = primitive["type"]
    expected.counts[primitive_type] = expected.counts.get(primitive_type, 0) + 1
    if primitive_type == "merge":
        expected.pages.extend(
            page
            for item in primitive["inputs"][1:]
            for page in _initial_expectation(parse_pdf(item["input"])).pages
        )
    elif primitive_type == "split":
        wanted = {
            number
            for start, end in primitive["page_ranges"]
            for number in range(start, end + 1)
        }
        expected.pages = [
            page for number, page in enumerate(expected.pages, start=1)
            if number in wanted
        ]
    elif primitive_type == "page_sequence":
        expected.pages = [expected.pages[number - 1] for number in primitive["pages"]]
    elif primitive_type == "page_insert":
        donor = _initial_expectation(parse_pdf(primitive["input"]))
        selected = primitive["pages"] or list(range(1, len(donor.pages) + 1))
        insertion = primitive["at"] - 1
        expected.pages[insertion:insertion] = [
            donor.pages[number - 1] for number in selected
        ]
    elif primitive_type == "rotate":
        for number in primitive["pages"]:
            expected.pages[number - 1].rotation = primitive["degrees"]
    elif primitive_type == "watermark":
        source_objects = _watermark_source_object_set(
            watermark_source_objects,
            primitive_index,
        )
        if source_objects is None:
            expected.watermark_baselines_valid = False
        plan_watermark_expectation(
            expected.pages,
            primitive,
            primitive_index,
            source_objects,
        )
    elif primitive_type == "annotation":
        _apply_annotation(expected.pages[primitive["page"] - 1], primitive)
    elif primitive_type == "redact_text":
        expected.pages[primitive["page"] - 1].redacted_text.add(primitive["text"])
    elif primitive_type == "form_fill":
        if primitive["flatten"]:
            expected.flattened_fields.update(primitive["fields"])
            for name in primitive["fields"]:
                expected.form_values.pop(name, None)
        else:
            expected.form_values.update(primitive["fields"])
            expected.flattened_fields.difference_update(primitive["fields"])


def _apply_annotation(
    page: _PageExpectation,
    primitive: dict[str, Any],
) -> None:
    action = primitive["action"]
    if action == "add":
        page.annotations.append({
            "subtype": "/Text",
            "rectangle": tuple(primitive["rectangle"]),
            "contents": primitive["contents"],
            "title": primitive.get("title"),
            "color": tuple(primitive["color"]),
            "action_kind": None,
        })
        return
    index = primitive["index"] - 1
    if action == "delete":
        page.annotations.pop(index)
        return
    annotation = page.annotations[index]
    for request_key, expected_key in (
        ("rectangle", "rectangle"),
        ("contents", "contents"),
        ("title", "title"),
        ("color", "color"),
    ):
        value = primitive.get(request_key)
        if value is not None:
            annotation[expected_key] = tuple(value) if isinstance(value, list) else value


def _assert_candidate(
    model: PdfObjectModel,
    expected: _EditExpectation,
    operation_result: dict[str, Any],
    primitives: list[dict[str, Any]],
    watermark_stage_hashes: object,
) -> dict[str, Any]:
    pages = walk_pages(model)
    failures: list[str] = []
    if not expected.watermark_baselines_valid:
        failures.append("watermark-stage-baseline")
    if len(pages) != len(expected.pages):
        failures.append("page-count")
    for page, wanted in zip(pages, expected.pages):
        if _page_signature(page) != _expected_page_signature(wanted):
            failures.append(f"page-tree:{page.page_number}")
    _assert_annotations(model, pages, expected.pages, failures)
    watermark_count = assert_watermarks(
        model,
        pages,
        expected.pages,
        failures,
        operation_result,
        primitives,
        watermark_stage_hashes,
    )
    redaction_count = _assert_redactions(model, pages, expected.pages, failures)
    form_count = assert_form_semantics(
        model,
        expected.form_values,
        expected.flattened_fields,
        failures,
    )
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Edited PDF does not satisfy the composite mutation request.",
            details={"semantic_mismatches": sorted(set(failures))},
        )
    return {
        "page_tree": True,
        "rotate": expected.counts.get("rotate", 0),
        "watermark": watermark_count,
        "form_fill": form_count,
        "annotation": expected.counts.get("annotation", 0),
        "redaction": redaction_count,
        "primitive_count": sum(expected.counts.values()),
    }


def _assert_annotations(
    model: PdfObjectModel,
    pages: list[PageInfo],
    expected_pages: list[_PageExpectation],
    failures: list[str],
) -> None:
    actual: dict[int, list[dict[str, Any]]] = {page.page_number: [] for page in pages}
    for item in map_annotations(model, pages):
        if item.subtype != "/Text":
            continue
        actual[item.page].append({
            "subtype": item.subtype,
            "rectangle": item.rectangle,
            "contents": item.contents,
            "title": item.title,
            "color": item.color,
            "action_kind": item.action_kind,
        })
    for number, wanted in enumerate(expected_pages, start=1):
        if actual.get(number, []) != wanted.annotations:
            failures.append(f"annotation:{number}")


def _assert_redactions(
    model: PdfObjectModel,
    pages: list[PageInfo],
    expected_pages: list[_PageExpectation],
    failures: list[str],
) -> int:
    count = 0
    for page, wanted in zip(pages, expected_pages):
        if not wanted.redacted_text:
            continue
        content = extract_content_stream(model, page.contents, page.page_number)
        texts = {block.text for block in walk_text_operators(content, page.page_number)}
        for text in wanted.redacted_text:
            literal = b"(" + _escape_literal(text).encode("latin-1") + b")"
            if text in texts or literal in model.raw:
                failures.append(f"redaction:{page.page_number}")
            count += 1
    return count


def _page_signature(page: PageInfo) -> tuple[Any, ...]:
    return (
        page.media_box,
        page.crop_box,
        page.bleed_box,
        page.trim_box,
        page.art_box,
        page.rotation,
    )


def _expected_page_signature(page: _PageExpectation) -> tuple[Any, ...]:
    return (
        page.media_box,
        page.crop_box,
        page.bleed_box,
        page.trim_box,
        page.art_box,
        page.rotation,
    )


def _selected_pages(primitive: dict[str, Any]) -> list[int] | None:
    primitive_type = primitive["type"]
    if primitive_type in {"rotate", "watermark", "page_sequence"}:
        return primitive["pages"]
    if primitive_type in {"annotation", "redact_text"}:
        return [primitive["page"]]
    if primitive_type == "outline" and primitive.get("page") is not None:
        return [primitive["page"]]
    if primitive_type == "page_labels":
        return [item["page"] for item in primitive["ranges"]]
    return None


def _watermark_source_object_set(
    commitments: object,
    primitive_index: int,
) -> frozenset[int] | None:
    if not isinstance(commitments, dict):
        return None
    values = commitments.get(primitive_index)
    if (
        type(values) is not list
        or any(type(value) is not int or value < 1 for value in values)
        or values != sorted(set(values))
    ):
        return None
    return frozenset(values)


def _invalid_pages(primitive: str, page_count: int, values: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.REQUEST_INVALID,
        "PDF edit page selection is outside the current staged document.",
        status="invalid_request",
        details={"primitive": primitive, "page_count": page_count, "selection": values},
    )


def _escape_literal(value: str) -> str:
    return value.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
