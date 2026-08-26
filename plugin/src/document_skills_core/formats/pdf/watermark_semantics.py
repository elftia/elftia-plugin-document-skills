"""Source-baselined semantic promotion checks for PDF watermarks."""

from typing import Any

from .object_model import PdfObjectModel
from .page_tree import PageInfo
from .watermark_expectations import ExpectedWatermark, PageWatermarkState
from .watermark_image_semantics import image_use_matches
from .watermark_report_semantics import opacity_matches, report_matches
from .watermark_scan import scan_watermark_uses, WatermarkUse


_IDENTITY_REPLACEMENT_PRIMITIVES = {
    "merge",
    "split",
    "page_insert",
    "page_sequence",
}


def assert_watermarks(
    model: PdfObjectModel,
    pages: list[PageInfo],
    expected_pages: list[Any],
    failures: list[str],
    operation_result: dict[str, Any],
    primitives: list[dict[str, Any]],
    watermark_stage_hashes: object,
) -> int:
    """Require baseline preservation plus one dedicated use per request/page."""
    reports = _watermark_reports(operation_result)
    count = 0
    requested_content_objects: set[int] = set()
    image_owners: dict[int, int] = {}
    soft_mask_owners: dict[int, int] = {}
    has_requests = any(_state(page).expected for page in expected_pages)
    if not has_requests:
        return 0
    if not _report_sequence_matches(operation_result, primitives):
        failures.append("watermark-report-sequence")
    for page, wanted_page in zip(pages, expected_pages):
        wanted = _state(wanted_page)
        actual = scan_watermark_uses(model, page)
        baseline_count = len(wanted.baseline)
        if [
            use.semantic_fingerprint() for use in actual[:baseline_count]
        ] != wanted.baseline:
            failures.append(f"watermark-baseline:{page.page_number}")
        requested = actual[baseline_count:]
        if len(requested) != len(wanted.expected):
            failures.append(f"watermark-occurrence:{page.page_number}")
        for use, expected in zip(requested, wanted.expected):
            if use.content_object in requested_content_objects:
                failures.append(f"watermark-content-ownership:{page.page_number}")
            requested_content_objects.add(use.content_object)
            if expected.kind == "image":
                _record_image_ownership(
                    use,
                    expected,
                    page.page_number,
                    image_owners,
                    soft_mask_owners,
                    failures,
                )
            if not _use_matches(use, expected):
                suffix = "image" if expected.kind == "image" else "binding"
                failures.append(f"watermark-{suffix}:{page.page_number}")
            report = reports.get(expected.primitive_index)
            if not report_matches(
                report,
                expected,
                use,
                identity_replaced=_identity_replaced_after(
                    primitives,
                    expected.primitive_index,
                ),
                trusted_stage_hashes=_trusted_stage_hashes(
                    watermark_stage_hashes,
                    expected.primitive_index,
                ),
            ):
                failures.append(f"watermark-evidence:{page.page_number}")
        count += len(wanted.expected)
    return count


def _record_image_ownership(
    use: WatermarkUse,
    expected: ExpectedWatermark,
    page_number: int,
    image_owners: dict[int, int],
    soft_mask_owners: dict[int, int],
    failures: list[str],
) -> None:
    _record_object_owner(
        use.image_object,
        expected.primitive_index,
        page_number,
        "image",
        image_owners,
        failures,
    )
    if use.soft_mask_present:
        _record_object_owner(
            use.soft_mask_object,
            expected.primitive_index,
            page_number,
            "soft-mask",
            soft_mask_owners,
            failures,
        )


def _record_object_owner(
    object_number: int | None,
    primitive_index: int,
    page_number: int,
    kind: str,
    owners: dict[int, int],
    failures: list[str],
) -> None:
    if object_number is None:
        return
    owner = owners.setdefault(object_number, primitive_index)
    if owner != primitive_index:
        failures.append(f"watermark-{kind}-ownership:{page_number}")


def _use_matches(use: WatermarkUse, expected: ExpectedWatermark) -> bool:
    if (
        use.graphics_state != expected.graphics_state
        or use.graphics_type != "/ExtGState"
        or use.graphics_keys != ("/CA", "/Type", "/ca")
        or not opacity_matches(use.ca, expected.opacity)
        or not opacity_matches(use.stroking_ca, expected.opacity)
        or use.content_object_generation != 0
        or use.content_stream_sha256 != expected.content_stream_sha256
        or use.content_keys != ("/Length",)
        or use.content_length != expected.content_length
        or use.content_filter is not None
        or use.content_decode_parms is not None
    ):
        return False
    if expected.kind == "image":
        return image_use_matches(use, expected)
    return (
        use.kind == "text"
        and use.text == expected.text
        and use.font_resource == expected.font_resource
        and use.font_type == "/Font"
        and use.font_subtype == "/Type1"
        and use.base_font == f"/{expected.base_font}"
        and use.font_encoding == "/WinAnsiEncoding"
        and _font_matches(use, expected)
    )


def _font_matches(use: WatermarkUse, expected: ExpectedWatermark) -> bool:
    if expected.font_source_dictionary_sha256 is not None:
        return (
            use.font_dictionary_sha256
            == expected.font_source_dictionary_sha256
            and use.font_keys == expected.font_source_keys
        )
    return (
        use.font_object_generation == 0
        and use.font_keys
        == ("/BaseFont", "/Encoding", "/Subtype", "/Type")
    )


def _watermark_reports(operation_result: dict[str, Any]) -> dict[int, dict[str, Any]]:
    if operation_result.get("primitive") == "watermark":
        return {0: operation_result}
    primitives = operation_result.get("primitives")
    if not isinstance(primitives, list):
        return {}
    return {
        item["index"]: item
        for item in primitives
        if isinstance(item, dict)
        and item.get("primitive") == "watermark"
        and type(item.get("index")) is int
    }


def _identity_replaced_after(
    primitives: list[dict[str, Any]],
    primitive_index: int,
) -> bool:
    return any(
        index > primitive_index
        and primitive.get("type") in _IDENTITY_REPLACEMENT_PRIMITIVES
        for index, primitive in enumerate(primitives)
    )


def _report_sequence_matches(
    operation_result: dict[str, Any],
    primitives: list[dict[str, Any]],
) -> bool:
    if len(primitives) == 1:
        return operation_result.get("primitive") == primitives[0].get("type")
    reports = operation_result.get("primitives")
    return (
        isinstance(reports, list)
        and len(reports) == len(primitives)
        and all(
            isinstance(report, dict)
            and report.get("index") == index
            and report.get("primitive") == primitive.get("type")
            for index, (report, primitive) in enumerate(zip(reports, primitives))
        )
    )


def _trusted_stage_hashes(
    commitments: object,
    primitive_index: int,
) -> dict[str, str]:
    if not isinstance(commitments, dict):
        return {}
    hashes = commitments.get(primitive_index)
    if not isinstance(hashes, dict):
        return {}
    return {
        key: value
        for key, value in hashes.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _state(page: Any) -> PageWatermarkState:
    state = page.watermark_state
    if not isinstance(state, PageWatermarkState):
        raise ValueError("Page watermark expectation state is missing.")
    return state
