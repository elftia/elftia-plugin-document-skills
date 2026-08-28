"""PDF page geometry bound to one Poppler raster result."""

import math
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.page_tree import PageInfo


def expected_raster_dimensions(page: PageInfo, dpi: int) -> tuple[int, int]:
    """Return the exact raster extent implied by the effective page box."""
    box = page.crop_box or page.media_box
    width = abs(box[2] - box[0])
    height = abs(box[3] - box[1])
    if _right_angle_rotation(page.rotation) in {90, 270}:
        width, height = height, width
    return math.ceil(width * dpi / 72), math.ceil(height * dpi / 72)


def render_page_record(
    page: PageInfo,
    *,
    dpi: int,
    output_format: str,
    payload_record: dict[str, Any],
    width: int,
    height: int,
) -> dict[str, Any]:
    """Bind page semantics to a verified provider raster."""
    expected_width, expected_height = expected_raster_dimensions(page, dpi)
    if (width, height) != (expected_width, expected_height):
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Poppler raster dimensions do not match the selected PDF page geometry.",
            details={
                "page": page.page_number,
                "expected_width": expected_width,
                "expected_height": expected_height,
                "actual_width": width,
                "actual_height": height,
            },
        )
    return {
        **payload_record,
        "page": page.page_number,
        "format": output_format,
        "media_box": list(page.media_box),
        "crop_box": list(page.crop_box) if page.crop_box is not None else None,
        "rotation": _right_angle_rotation(page.rotation),
        "dpi": dpi,
        "width": width,
        "height": height,
        "pixels": width * height,
        "raster_evidence": {
            "expected_width": expected_width,
            "expected_height": expected_height,
            "bbox": [0, 0, width, height],
            "bounds": [0, 0, expected_width, expected_height],
            "bounded": True,
            "overflow": False,
        },
    }


def _right_angle_rotation(value: int) -> int:
    rotation = value % 360
    if rotation not in {0, 90, 180, 270}:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Render semantics require right-angle PDF page rotation.",
            status="enhancement_required",
            details={"rotation": value},
        )
    return rotation
