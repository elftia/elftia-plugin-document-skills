"""Conversion, rendering, comparison, and layout operation contracts."""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .contract_utils import (
    _DEFAULT_PUBLIC_PNG_TOTAL_BYTES,
    _MAX_PUBLIC_PNG_TOTAL_BYTES,
    _SEMANTIC_ID,
    _SHA256,
    _boolean,
    _exact_keys,
    _integer,
    _invalid,
    _text,
)

def _parse_convert_pdf(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"max_output_bytes"})
    return {
        "max_output_bytes": _integer(
            value.get("max_output_bytes", 64 * 1024 * 1024),
            1_024,
            128 * 1024 * 1024,
        )
    }


def _parse_convert_legacy(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(value, {"format", "max_output_bytes"})
    target_format = value.get("format")
    if target_format not in {"docx", "pdf"}:
        _invalid("Legacy DOC target format must be 'docx' or 'pdf'.", field="format")
    return {
        "format": target_format,
        "max_output_bytes": _integer(
            value.get("max_output_bytes", 64 * 1024 * 1024),
            1_024,
            128 * 1024 * 1024,
        ),
    }


def _parse_render(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "dpi",
            "format",
            "include_page_pngs",
            "layout_profile",
            "max_page_bytes",
            "max_pages",
            "max_png_total_bytes",
            "max_total_bytes",
            "page_range",
        },
    )
    output_format = value.get("format", "pdf")
    if output_format == "png":
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Per-page PNG rendering requires an accepted raster provider.",
            status="enhancement_required",
            details={"missing_capabilities": ["docx.render.png"]},
        )
    if output_format != "pdf":
        _invalid("Render format must be 'pdf'.", field="format")
    include_page_pngs = _boolean(
        value.get("include_page_pngs", False),
        "include_page_pngs",
    )
    dpi = value.get("dpi", 96 if include_page_pngs else None)
    if include_page_pngs:
        if dpi != 96:
            _invalid("LibreOffice page PNG evidence uses fixed 96 DPI.", field="dpi")
    elif dpi is not None:
        _invalid("DPI must be null for vector PDF render evidence.", field="dpi")
    layout_profile = value.get("layout_profile", "professional-v1")
    if layout_profile != "professional-v1":
        _invalid("Unsupported layout inspection profile.", field="layout_profile")
    maximum_pages = _integer(value.get("max_pages", 200), 1, 1_000)
    page_range = value.get("page_range", "all")
    if page_range == "all":
        parsed_range: str | dict[str, int] = "all"
    elif type(page_range) is dict:
        _exact_keys(page_range, {"end", "start"})
        if set(page_range) != {"end", "start"}:
            _invalid("Page range requires start and end.", field="page_range")
        start = _integer(page_range.get("start"), 1, 10_000)
        end = _integer(page_range.get("end"), 1, 10_000)
        if end < start:
            _invalid("Page range end must not precede start.", field="page_range")
        if end - start + 1 > maximum_pages:
            _invalid("Page range exceeds max_pages.", field="page_range")
        parsed_range = {"start": start, "end": end}
    else:
        _invalid("Page range must be 'all' or a bounded object.", field="page_range")
    return {
        "format": "pdf",
        "page_range": parsed_range,
        "dpi": dpi,
        "include_page_pngs": include_page_pngs,
        "layout_profile": layout_profile,
        "max_pages": maximum_pages,
        "max_page_bytes": _integer(
            value.get("max_page_bytes", 4 * 1024 * 1024),
            1_024,
            16 * 1024 * 1024,
        ),
        "max_png_total_bytes": _integer(
            value.get("max_png_total_bytes", _DEFAULT_PUBLIC_PNG_TOTAL_BYTES),
            1_024,
            _MAX_PUBLIC_PNG_TOTAL_BYTES,
        ),
        "max_total_bytes": _integer(
            value.get("max_total_bytes", 64 * 1024 * 1024),
            1_024,
            128 * 1024 * 1024,
        ),
    }


def _parse_semantic_compare(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "allowed_changes",
            "baseline",
            "document_spec",
            "expected_baseline_sha256",
        },
    )
    document_spec = value.get("document_spec")
    baseline = value.get("baseline")
    if (document_spec is None) == (baseline is None):
        _invalid("Semantic comparison requires exactly one comparison source.")
    if document_spec is not None:
        if set(value) != {"document_spec"}:
            _invalid("Spec/output comparison does not accept baseline arguments.")
        from .document_spec import parse_document_spec

        return {"mode": "spec-output", "report": parse_document_spec(document_spec)}
    raw_baseline = _text(baseline, "baseline", allow_empty=False)
    if "://" in raw_baseline or raw_baseline.startswith(("\\\\", "//")):
        _invalid("Semantic comparison baseline must be a local path.")
    baseline_path = Path(raw_baseline).expanduser().resolve(strict=False)
    if baseline_path.suffix.casefold() != ".docx":
        _invalid("Semantic comparison baseline must use .docx.")
    digest = value.get("expected_baseline_sha256")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        _invalid("Semantic comparison baseline SHA-256 is invalid.")
    allowed = value.get("allowed_changes", [])
    if (
        type(allowed) is not list
        or len(allowed) > 256
        or any(type(item) is not str or _SEMANTIC_ID.fullmatch(item) is None for item in allowed)
        or len(set(allowed)) != len(allowed)
    ):
        _invalid("Semantic comparison allowed_changes is invalid.")
    return {
        "mode": "before-after",
        "baseline": baseline_path,
        "expected_baseline_sha256": digest.casefold(),
        "allowed_changes": sorted(allowed),
    }


def _parse_visual_compare(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "expected_reference_sha256",
            "max_pages",
            "max_png_total_bytes",
            "max_total_bytes",
            "page_pairs",
            "reference",
            "render_profile",
        },
    )
    raw_reference = _text(value.get("reference"), "reference", allow_empty=False)
    if "://" in raw_reference or raw_reference.startswith(("\\\\", "//")):
        _invalid("Visual comparison reference must be a local path.")
    reference = Path(raw_reference).expanduser().resolve(strict=False)
    if reference.suffix.casefold() not in {".docx", ".pdf", ".png"}:
        _invalid("Visual comparison reference must use .docx, .pdf, or .png.")
    digest = value.get("expected_reference_sha256")
    if type(digest) is not str or _SHA256.fullmatch(digest) is None:
        _invalid("Visual comparison reference SHA-256 is invalid.")
    if value.get("render_profile") != "libreoffice-96dpi-v1":
        _invalid("Unsupported fixed visual comparison profile.")
    maximum_pages = _integer(value.get("max_pages", 20), 1, 50)
    pairs = value.get("page_pairs")
    if type(pairs) is not list or not 1 <= len(pairs) <= maximum_pages:
        _invalid("Visual comparison requires bounded explicit page_pairs.")
    parsed_pairs = []
    actual_seen: set[int] = set()
    reference_seen: set[int] = set()
    for index, pair in enumerate(pairs):
        if type(pair) is not dict:
            _invalid("Visual comparison page pair must be an object.")
        _exact_keys(pair, {"actual", "reference"})
        actual = _integer(pair.get("actual"), 1, 1_000)
        reference_page = _integer(pair.get("reference"), 1, 1_000)
        if actual in actual_seen or reference_page in reference_seen:
            _invalid("Visual comparison page_pairs must be one-to-one.", index=index)
        actual_seen.add(actual)
        reference_seen.add(reference_page)
        parsed_pairs.append({"actual": actual, "reference": reference_page})
    return {
        "reference": reference,
        "expected_reference_sha256": digest.casefold(),
        "render_profile": "libreoffice-96dpi-v1",
        "page_pairs": parsed_pairs,
        "max_pages": maximum_pages,
        "max_total_bytes": _integer(
            value.get("max_total_bytes", 64 * 1024 * 1024),
            1_024,
            128 * 1024 * 1024,
        ),
        "max_png_total_bytes": _integer(
            value.get("max_png_total_bytes", 16 * 1024 * 1024),
            1_024,
            64 * 1024 * 1024,
        ),
    }


def _parse_layout_repair(value: dict[str, Any]) -> dict[str, Any]:
    _exact_keys(
        value,
        {
            "finding_codes",
            "max_pages",
            "max_png_total_bytes",
            "max_rounds",
            "max_total_bytes",
        },
    )
    codes = value.get(
        "finding_codes",
        ["DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH"],
    )
    allowed = {"DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH"}
    if (
        type(codes) is not list
        or not 1 <= len(codes) <= len(allowed)
        or any(type(code) is not str or code not in allowed for code in codes)
        or len(set(codes)) != len(codes)
    ):
        _invalid("Layout repair finding_codes are invalid or unsupported.")
    return {
        "finding_codes": sorted(codes),
        "max_rounds": _integer(value.get("max_rounds", 2), 1, 3),
        "max_pages": _integer(value.get("max_pages", 20), 1, 20),
        "max_total_bytes": _integer(
            value.get("max_total_bytes", 64 * 1024 * 1024),
            1_024,
            128 * 1024 * 1024,
        ),
        "max_png_total_bytes": _integer(
            value.get("max_png_total_bytes", 16 * 1024 * 1024),
            1_024,
            64 * 1024 * 1024,
        ),
    }
