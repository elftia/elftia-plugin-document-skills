"""Deep typed-create correspondence checks for native images and charts."""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .chart import prepare_chart
from .constants import NS
from .mapping import map_slides
from .projection import project_charts


def assert_typed_objects(
    package: Any,
    deck: dict[str, Any],
    creation: dict[str, Any] | None,
) -> dict[str, Any]:
    failures: list[str] = []
    slides = map_slides(package)
    image_records = [] if creation is None else creation.get("images", [])
    chart_records = [] if creation is None else creation.get("charts", [])
    _assert_images(package, deck, slides, image_records, failures)
    _assert_charts(package, deck, slides, chart_records, failures)
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Created PPTX native object correspondence failed.",
            details={"missing_or_mismatched": failures},
        )
    return {
        "charts": len(package.chart_parts()),
        "images": len(package.media_parts()),
        "native_object_correspondence": True,
    }


def _assert_images(
    package: Any,
    deck: dict[str, Any],
    slides: list[dict[str, Any]],
    records: list[dict[str, Any]],
    failures: list[str],
) -> None:
    expected = [
        (index, slide["image_reference"])
        for index, slide in enumerate(deck.get("slides", []))
        if slide.get("image_reference")
    ]
    if len(package.media_parts()) != len(expected):
        failures.append("image-part-count")
    if records and len(records) != len(expected):
        failures.append("image-evidence-count")
    for ordinal, (slide_index, request) in enumerate(expected):
        if slide_index >= len(slides) or not slides[slide_index].get("part"):
            failures.append(f"image-{ordinal + 1}-slide")
            continue
        slide_part = slides[slide_index]["part"]
        relationships = [
            rel for rel in package.part_rels(slide_part)
            if rel.relationship_type.endswith("/image")
        ]
        if len(relationships) != 1 or relationships[0].resolved_target is None:
            failures.append(f"image-{ordinal + 1}-relationship")
            continue
        target = relationships[0].resolved_target
        if target not in package.parts:
            failures.append(f"image-{ordinal + 1}-target")
            continue
        if records:
            record = records[ordinal]
            if target != record.get("embedded_media_part"):
                failures.append(f"image-{ordinal + 1}-part")
            if package.part_hashes[target] != record.get("source_asset_sha256"):
                failures.append(f"image-{ordinal + 1}-payload")
            if package.content_type_for(target) != record.get("content_type"):
                failures.append(f"image-{ordinal + 1}-content-type")
            if record.get("fallback") != "native":
                failures.append(f"image-{ordinal + 1}-fallback")
        root = package.xml(slide_part)
        embeds = [node.attrib.get(f"{{{NS['r']}}}embed") for node in root.iter(f"{{{NS['a']}}}blip")]
        if relationships[0].relationship_id not in embeds:
            failures.append(f"image-{ordinal + 1}-drawing")
        requested_alt = request.get("alt_text", "Presentation image")
        alt_texts = [
            node.attrib.get("descr", "")
            for node in root.iter(f"{{{NS['p']}}}cNvPr")
        ]
        if requested_alt not in alt_texts:
            failures.append(f"image-{ordinal + 1}-alt-text")


def _assert_charts(
    package: Any,
    deck: dict[str, Any],
    slides: list[dict[str, Any]],
    records: list[dict[str, Any]],
    failures: list[str],
) -> None:
    expected = [
        (index, prepare_chart(slide["chart_reference"], ordinal + 1))
        for ordinal, (index, slide) in enumerate(
            (item for item in enumerate(deck.get("slides", [])) if item[1].get("chart_reference"))
        )
    ]
    projected = project_charts(package)
    if len(projected) != len(expected):
        failures.append("chart-part-count")
    if records and len(records) != len(expected):
        failures.append("chart-evidence-count")
    by_part = {item["part"]: item for item in projected}
    for ordinal, (slide_index, request) in enumerate(expected):
        if slide_index >= len(slides) or not slides[slide_index].get("part"):
            failures.append(f"chart-{ordinal + 1}-slide")
            continue
        slide_part = slides[slide_index]["part"]
        relationships = [
            rel for rel in package.part_rels(slide_part)
            if rel.relationship_type.endswith("/chart")
        ]
        if len(relationships) != 1 or relationships[0].resolved_target is None:
            failures.append(f"chart-{ordinal + 1}-relationship")
            continue
        target = relationships[0].resolved_target
        actual = by_part.get(target)
        if actual is None:
            failures.append(f"chart-{ordinal + 1}-target")
            continue
        if actual["chart_type"] != request["chart_type"]:
            failures.append(f"chart-{ordinal + 1}-type")
        if actual["title"] != request["title"]:
            failures.append(f"chart-{ordinal + 1}-title")
        if not _series_equal(actual["series"], request["series"], request["categories"]):
            failures.append(f"chart-{ordinal + 1}-series")
        expected_axes = 0 if request["chart_type"] == "pie" else 2
        if len(actual["axes"]) != expected_axes or not _axes_linked(actual["axes"]):
            failures.append(f"chart-{ordinal + 1}-axes")
        if records:
            record = records[ordinal]
            if record.get("chart_part") != target:
                failures.append(f"chart-{ordinal + 1}-part")
            if record.get("editable") is not True or record.get("fallback") != "native":
                failures.append(f"chart-{ordinal + 1}-native")
            if record.get("data_storage") != "literal-cache":
                failures.append(f"chart-{ordinal + 1}-storage")
        root = package.xml(slide_part)
        references = [node.attrib.get(f"{{{NS['r']}}}id") for node in root.iter(f"{{{NS['c']}}}chart")]
        if relationships[0].relationship_id not in references:
            failures.append(f"chart-{ordinal + 1}-drawing")
        chart_root = package.xml(target)
        if not list(chart_root.iter(f"{{{NS['c']}}}numLit")):
            failures.append(f"chart-{ordinal + 1}-cache")


def _series_equal(
    actual: list[dict[str, Any]],
    expected: list[dict[str, Any]],
    categories: list[str],
) -> bool:
    if len(actual) != len(expected):
        return False
    for actual_item, expected_item in zip(actual, expected, strict=True):
        if actual_item.get("name") != expected_item.get("name"):
            return False
        if "y_values" in expected_item:
            if actual_item.get("x_values") != expected_item.get("x_values"):
                return False
            if actual_item.get("y_values") != expected_item.get("y_values"):
                return False
        else:
            if actual_item.get("categories") != categories:
                return False
            if actual_item.get("values") != expected_item.get("values"):
                return False
    return True


def _axes_linked(axes: list[dict[str, Any]]) -> bool:
    if not axes:
        return True
    ids = {axis.get("id") for axis in axes}
    return len(ids) == len(axes) and all(axis.get("cross_axis_id") in ids for axis in axes)
