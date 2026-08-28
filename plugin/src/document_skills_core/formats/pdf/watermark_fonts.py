"""Closed Base-14 font planning for Core text watermarks."""

from dataclasses import dataclass
import hashlib
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfDict, PdfObjectModel


SUPPORTED_BASE14_WATERMARK_FONTS = (
    "Courier",
    "Courier-Bold",
    "Courier-BoldOblique",
    "Courier-Oblique",
    "Helvetica",
    "Helvetica-Bold",
    "Helvetica-BoldOblique",
    "Helvetica-Oblique",
    "Times-Bold",
    "Times-BoldItalic",
    "Times-Italic",
    "Times-Roman",
)
_RESOURCE_PREFIX = "DSWMFont"
_MAX_RESOURCE_CANDIDATES = 10_000
_MISSING = object()
_CANONICAL_FONT_KEYS = ("/BaseFont", "/Encoding", "/Subtype", "/Type")


@dataclass(frozen=True)
class WatermarkFontPlan:
    """Resource name and optional newly allocated Base-14 font object."""

    resource_name: str
    object_number: int | None


def plan_watermark_font(
    model: PdfObjectModel,
    pages: list[Any],
    base_font: str,
    added_objects: dict[int, bytes],
) -> WatermarkFontPlan:
    """Reuse a matching dedicated resource or allocate a collision-free one."""
    for suffix in range(_MAX_RESOURCE_CANDIDATES):
        name = _RESOURCE_PREFIX if suffix == 0 else f"{_RESOURCE_PREFIX}{suffix}"
        entries = [_font_entry(model, page, name) for page in pages]
        if entries and all(
            isinstance(entry, IndirectReference)
            and _reference_matches(model, entry, base_font)
            for entry in entries
        ):
            return WatermarkFontPlan(name, None)
        if any(entry is not _MISSING for entry in entries):
            continue
        object_number = _next_object_number(model, added_objects)
        added_objects[object_number] = watermark_font_object_payload(
            object_number,
            base_font,
        )
        return WatermarkFontPlan(name, object_number)
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "No collision-free watermark font resource name is available.",
        status="enhancement_required",
        details={"capability": "pdf.watermark-font-resources"},
    )


def watermark_font_matches(
    model: PdfObjectModel,
    page: Any,
    resource_name: str,
    base_font: str,
) -> bool:
    """Verify an operator resource resolves to the requested Type1 font object."""
    if not resource_name.startswith(f"/{_RESOURCE_PREFIX}"):
        return False
    reference = _font_entry(
        model,
        page,
        resource_name.removeprefix("/"),
    )
    return (
        isinstance(reference, IndirectReference)
        and _reference_matches(model, reference, base_font)
    )


def _font_entry(
    model: PdfObjectModel,
    page: Any,
    resource_name: str,
) -> object:
    resources = page.resources
    if not isinstance(resources, PdfDict):
        return _MISSING
    fonts = resources.get("/Font")
    if isinstance(fonts, IndirectReference):
        fonts = model.get_object(fonts).value
    if not isinstance(fonts, PdfDict):
        return _MISSING
    return fonts.entries.get(f"/{resource_name}", _MISSING)


def _reference_matches(
    model: PdfObjectModel,
    reference: IndirectReference,
    base_font: str,
) -> bool:
    obj = model.objects.get(reference.obj_num)
    if (
        obj is None
        or reference.gen_num != obj.gen_num
        or obj.gen_num != 0
        or not isinstance(obj.value, PdfDict)
    ):
        return False
    value = obj.value
    return (
        tuple(sorted(value.entries)) == _CANONICAL_FONT_KEYS
        and value.get("/Type") == "/Font"
        and value.get("/Subtype") == "/Type1"
        and value.get("/BaseFont") == f"/{base_font}"
        and value.get("/Encoding") == "/WinAnsiEncoding"
        and obj.sha256 == watermark_font_object_sha256(obj.obj_num, base_font)
    )


def canonical_font_record_matches(record: Any, base_font: str) -> bool:
    """Return whether a scanned record is the exact reusable Base-14 object."""
    return (
        record.object_generation == 0
        and record.keys == _CANONICAL_FONT_KEYS
        and record.type_name == "/Font"
        and record.subtype == "/Type1"
        and record.base_font == base_font
        and record.encoding == "/WinAnsiEncoding"
        and record.object_sha256
        == watermark_font_object_sha256(record.object_number, base_font)
    )


def _next_object_number(
    model: PdfObjectModel,
    added_objects: dict[int, bytes],
) -> int:
    occupied = set(model.objects) | set(added_objects) | {model.trailer.size - 1}
    return max(occupied) + 1


def watermark_font_object_sha256(object_number: int, base_font: str) -> str:
    """Hash the canonical object payload for one allocated Base-14 font."""
    return hashlib.sha256(
        watermark_font_object_payload(object_number, base_font)
    ).hexdigest()


def watermark_font_object_payload(object_number: int, base_font: str) -> bytes:
    """Build the canonical object payload for one allocated Base-14 font."""
    if base_font not in SUPPORTED_BASE14_WATERMARK_FONTS:
        raise ValueError("Unsupported Base-14 watermark font reached the writer.")
    return (
        f"{object_number} 0 obj\n"
        f"<< /Type /Font /Subtype /Type1 /BaseFont /{base_font} "
        f"/Encoding /WinAnsiEncoding >>\nendobj"
    ).encode("ascii")
