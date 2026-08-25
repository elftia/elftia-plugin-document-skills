"""Bounded full-page and expected-region raster difference evidence."""

from io import BytesIO
from typing import Any

from PIL import Image, ImageChops, ImageDraw

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode


def compare_rendered_page(
    candidate_payload: bytes,
    reference_payload: bytes,
    page: Any,
    regions: list[dict[str, Any]],
    *,
    channel_tolerance: int,
) -> dict[str, Any]:
    candidate = _decode(candidate_payload)
    reference = _decode(reference_payload)
    if candidate.size != reference.size:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Rendered candidate and reference page dimensions differ.",
            details={
                "page": page.page_number,
                "candidate_dimensions": list(candidate.size),
                "reference_dimensions": list(reference.size),
            },
        )
    difference = ImageChops.difference(candidate, reference)
    changed = _changed_mask(difference, channel_tolerance)
    expected = _expected_mask(candidate.size, page, regions)
    expected_changed = _count_mask(ImageChops.multiply(changed, expected))
    changed_samples = _count_mask(changed)
    expected_samples = _count_mask(expected)
    total_samples = candidate.width * candidate.height
    unexpected_changed = changed_samples - expected_changed
    unexpected_samples = total_samples - expected_samples
    return {
        "page": page.page_number,
        "width": candidate.width,
        "height": candidate.height,
        "samples": total_samples,
        "changed_samples": changed_samples,
        "changed_sample_ratio": round(changed_samples / max(total_samples, 1), 8),
        "expected_samples": expected_samples,
        "expected_changed_samples": expected_changed,
        "expected_change_ratio": round(expected_changed / max(expected_samples, 1), 8),
        "unexpected_samples": unexpected_samples,
        "unexpected_changed_samples": unexpected_changed,
        "unexpected_change_ratio": round(
            unexpected_changed / max(unexpected_samples, 1),
            8,
        ),
    }


def aggregate_render_diff(
    page_records: list[dict[str, Any]],
    *,
    reference_sha256: str,
    channel_tolerance: int,
    max_unexpected_change_ratio: float,
    minimum_expected_change_ratio: float,
) -> dict[str, Any]:
    totals = {
        key: sum(int(record[key]) for record in page_records)
        for key in (
            "samples",
            "changed_samples",
            "expected_samples",
            "expected_changed_samples",
            "unexpected_samples",
            "unexpected_changed_samples",
        )
    }
    expected_ratio = totals["expected_changed_samples"] / max(totals["expected_samples"], 1)
    unexpected_ratio = totals["unexpected_changed_samples"] / max(totals["unexpected_samples"], 1)
    expected_pass = (
        totals["expected_samples"] == 0
        or expected_ratio >= minimum_expected_change_ratio
    )
    unexpected_pass = unexpected_ratio <= max_unexpected_change_ratio
    return {
        "provider": "poppler",
        "reference_sha256": reference_sha256,
        "channel_tolerance": channel_tolerance,
        "max_unexpected_change_ratio": max_unexpected_change_ratio,
        "minimum_expected_change_ratio": minimum_expected_change_ratio,
        **totals,
        "changed_sample_ratio": round(
            totals["changed_samples"] / max(totals["samples"], 1),
            8,
        ),
        "expected_change_ratio": round(expected_ratio, 8),
        "unexpected_change_ratio": round(unexpected_ratio, 8),
        "expected_change_pass": expected_pass,
        "unexpected_change_pass": unexpected_pass,
        "policy_pass": expected_pass and unexpected_pass,
        "pages": page_records,
    }


def _decode(payload: bytes) -> Image.Image:
    try:
        with Image.open(BytesIO(payload)) as image:
            image.load()
            return image.convert("RGB")
    except Exception as error:
        raise DocumentSkillsError(
            ErrorCode.PROVIDER_FAILED,
            "Rendered page could not be decoded for visual comparison.",
            details={"reason": type(error).__name__},
        ) from None


def _changed_mask(difference: Image.Image, tolerance: int) -> Image.Image:
    channels = [
        channel.point(lambda value: 255 if value > tolerance else 0)
        for channel in difference.split()
    ]
    mask = channels[0]
    for channel in channels[1:]:
        mask = ImageChops.lighter(mask, channel)
    return mask


def _expected_mask(
    dimensions: tuple[int, int],
    page: Any,
    regions: list[dict[str, Any]],
) -> Image.Image:
    mask = Image.new("L", dimensions, 0)
    page_regions = [region for region in regions if region["page"] == page.page_number]
    if not page_regions:
        return mask
    rotation = int(page.rotation) % 360
    if rotation not in {0, 90, 180, 270}:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Expected-change raster regions require a right-angle page rotation.",
            status="enhancement_required",
            details={"page": page.page_number, "rotation": page.rotation},
        )
    box = page.crop_box or page.media_box
    page_width = float(box[2]) - float(box[0])
    page_height = float(box[3]) - float(box[1])
    display_width = page_height if rotation in {90, 270} else page_width
    display_height = page_width if rotation in {90, 270} else page_height
    draw = ImageDraw.Draw(mask)
    for region in page_regions:
        x0, y0, x1, y1 = region["bbox"]
        corners = [
            _display_point(
                x - float(box[0]),
                y - float(box[1]),
                page_width,
                page_height,
                rotation,
            )
            for x, y in ((x0, y0), (x0, y1), (x1, y0), (x1, y1))
        ]
        left = round(min(point[0] for point in corners) / display_width * dimensions[0])
        right = round(max(point[0] for point in corners) / display_width * dimensions[0])
        top = round(min(point[1] for point in corners) / display_height * dimensions[1])
        bottom = round(max(point[1] for point in corners) / display_height * dimensions[1])
        clipped = (
            max(0, min(dimensions[0], left)),
            max(0, min(dimensions[1], top)),
            max(0, min(dimensions[0], right)),
            max(0, min(dimensions[1], bottom)),
        )
        if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Expected change region is outside the rendered page.",
                status="invalid_request",
                details={"page": page.page_number, "bbox": region["bbox"]},
            )
        draw.rectangle((clipped[0], clipped[1], clipped[2] - 1, clipped[3] - 1), fill=255)
    return mask


def _display_point(
    x: float,
    y: float,
    width: float,
    height: float,
    rotation: int,
) -> tuple[float, float]:
    if rotation == 90:
        return y, x
    if rotation == 180:
        return width - x, y
    if rotation == 270:
        return height - y, width - x
    return x, height - y


def _count_mask(mask: Image.Image) -> int:
    histogram = mask.histogram()
    return histogram[255]
