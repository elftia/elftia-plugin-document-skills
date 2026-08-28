"""Expected-region planning for automatic PDF mutation visual validation."""

from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .form_graph import collect_form_fields
from .form_widget_layout import widget_page_layout
from .object_model import PdfDict, PdfObjectModel
from .page_tree import PageInfo, walk_pages

_NONVISUAL_EDIT_TYPES = frozenset({"metadata_update", "outline", "page_labels"})
_PRECISE_EDIT_TYPES = frozenset(
    {"annotation", "form_fill", "redact_text", "watermark"}
)


@dataclass(frozen=True)
class MutationVisualPlan:
    pages: tuple[int, ...]
    regions: tuple[dict[str, Any], ...]
    basis: tuple[str, ...]
    unavailable_reason: str | None = None
    includes_full_page: bool = False


def derive_mutation_visual_plan(
    operation: str,
    source_model: PdfObjectModel,
    candidate_model: PdfObjectModel,
    arguments: dict[str, Any],
    operation_result: dict[str, Any],
) -> MutationVisualPlan:
    """Derive affected pages and expected regions from trusted mutation inputs."""
    source_pages = walk_pages(source_model)
    candidate_pages = walk_pages(candidate_model)
    regions: list[dict[str, Any]] = []
    basis: list[str] = []
    includes_full_page = False
    if operation == "pdf.rewrite.apply":
        for rewrite in arguments["rewrites"]:
            block = arguments["blocks"][rewrite["block_index"]]
            _add_region(regions, block["page"], block["bbox"])
        basis.append("rewrite-selector-bbox")
    else:
        results = _primitive_results(operation_result)
        primitive_types = {primitive["type"] for primitive in arguments["primitives"]}
        for index, primitive in enumerate(arguments["primitives"]):
            primitive_type = primitive["type"]
            result = results.get(index, {})
            if primitive_type == "watermark":
                for number in primitive["pages"]:
                    _add_region(regions, number, _page_box(source_pages, number))
                includes_full_page = True
                basis.append("watermark-full-page")
            elif primitive_type == "redact_text":
                bbox = result.get("bbox")
                if not _bbox(bbox):
                    _failed("Redaction visual validation lacks a trusted result bbox.")
                _add_region(regions, primitive["page"], bbox)
                basis.append("redaction-result-bbox")
            elif primitive_type == "annotation":
                rectangles = _annotation_rectangles(
                    primitive,
                    result,
                    source_model,
                    candidate_model,
                )
                if not rectangles:
                    _failed("Annotation visual validation could not resolve its rectangle.")
                for rectangle in rectangles:
                    _add_region(regions, primitive["page"], rectangle)
                basis.append("annotation-rectangle")
            elif primitive_type == "form_fill":
                for page, rectangle in _form_regions(source_model, primitive["fields"]):
                    _add_region(regions, page, rectangle)
                basis.append("form-widget-rectangle")
        fallback = primitive_types - _PRECISE_EDIT_TYPES - _NONVISUAL_EDIT_TYPES
        if fallback:
            impact = operation_result.get("page_impact", {})
            source_impact = impact.get("source_pages", [])
            output_impact = impact.get("output_pages", [])
            if source_impact != output_impact:
                return MutationVisualPlan(
                    (),
                    (),
                    tuple(sorted(set(basis) | {"page-impact"})),
                    "Affected pages have no stable pre/post page mapping.",
                )
            for number in source_impact:
                _add_region(regions, number, _page_box(candidate_pages, number))
            includes_full_page = includes_full_page or bool(source_impact)
            basis.append("page-impact")
    pages = tuple(sorted({int(region["page"]) for region in regions}))
    return MutationVisualPlan(
        pages,
        tuple(regions),
        tuple(sorted(set(basis))),
        includes_full_page=includes_full_page,
    )


def _primitive_results(operation_result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    records = operation_result.get("primitives")
    if isinstance(records, list):
        return {
            record["index"]: record
            for record in records
            if isinstance(record, dict) and type(record.get("index")) is int
        }
    return {0: operation_result}


def _annotation_rectangles(
    primitive: dict[str, Any],
    result: dict[str, Any],
    source_model: PdfObjectModel,
    candidate_model: PdfObjectModel,
) -> list[list[float]]:
    rectangles: list[list[float]] = []
    if _bbox(primitive.get("rectangle")):
        rectangles.append(list(primitive["rectangle"]))
    object_number = result.get("annotation_object")
    if type(object_number) is not int:
        return rectangles
    for model in (source_model, candidate_model):
        obj = model.objects.get(object_number)
        value = obj.value if obj is not None else None
        rectangle = value.get("/Rect") if isinstance(value, PdfDict) else None
        if _bbox(rectangle):
            rectangles.append([float(item) for item in rectangle])
    return rectangles


def _form_regions(
    model: PdfObjectModel,
    requested: dict[str, Any],
) -> list[tuple[int, list[float]]]:
    pages = walk_pages(model)
    page_numbers = {page.obj_num: page.page_number for page in pages}
    regions: list[tuple[int, list[float]]] = []
    matched: set[str] = set()
    for field in collect_form_fields(model):
        if field.qualified_name not in requested:
            continue
        matched.add(field.qualified_name)
        for widget in field.widgets:
            rectangle, page_object = widget_page_layout(
                widget,
                field.qualified_name,
                page_numbers,
            )
            regions.append((page_numbers[page_object], list(rectangle)))
    if matched != set(requested):
        _failed("Form visual validation could not resolve every requested widget.")
    return regions


def _page_box(pages: list[PageInfo], number: int) -> list[float]:
    if not 1 <= number <= len(pages):
        _failed("Mutation visual validation references a page outside the candidate.")
    box = pages[number - 1].crop_box or pages[number - 1].media_box
    return list(box)


def _add_region(regions: list[dict[str, Any]], page: int, bbox: Any) -> None:
    if not _bbox(bbox):
        _failed("Mutation visual validation received an invalid expected bbox.")
    region = {"page": int(page), "bbox": [float(item) for item in bbox]}
    if region not in regions:
        regions.append(region)


def _bbox(value: Any) -> bool:
    return (
        isinstance(value, (list, tuple))
        and len(value) == 4
        and all(type(item) in {int, float} for item in value)
        and float(value[0]) < float(value[2])
        and float(value[1]) < float(value[3])
    )


def _failed(message: str) -> None:
    raise DocumentSkillsError(ErrorCode.PROVIDER_FAILED, message)
