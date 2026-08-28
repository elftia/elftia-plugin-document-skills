"""Candidate-derived watermark use and resource scanning."""

from dataclasses import dataclass
import hashlib
import re
from typing import Any

from .content_tokenizer import tokenize_content_stream
from .object_model import PdfDict, PdfObjectModel
from .page_tree import PageInfo
from .watermark_resource_scan import (
    font_resource_record,
    resource_dictionary_entry,
    resource_indirect_object,
    soft_mask_record,
    strict_indirect_object,
)
from .xobject_draws import concatenate_matrix, IDENTITY_MATRIX, unit_square_bbox


_GRAPHICS_NAME = re.compile(r"/DSWMGS(?:[1-9][0-9]*)?\Z")
_IMAGE_NAME = re.compile(r"/DSWMImage(?:[1-9][0-9]*)?\Z")
_FONT_NAME = re.compile(r"/DSWMFont(?:[1-9][0-9]*)?\Z")


@dataclass(frozen=True)
class WatermarkUse:
    """One dedicated watermark drawing use reopened from a content stream."""

    kind: str
    content_object: int
    content_object_generation: int
    content_object_sha256: str
    content_stream_sha256: str
    content_keys: tuple[str, ...]
    content_length: Any
    content_filter: Any
    content_decode_parms: Any
    graphics_state: str | None
    graphics_type: Any = None
    graphics_keys: tuple[str, ...] | None = None
    ca: Any = None
    stroking_ca: Any = None
    text: str | None = None
    font_resource: str | None = None
    font_object: int | None = None
    font_object_generation: int | None = None
    font_object_sha256: str | None = None
    font_dictionary_sha256: str | None = None
    font_keys: tuple[str, ...] | None = None
    font_type: Any = None
    font_subtype: Any = None
    base_font: str | None = None
    font_encoding: str | None = None
    image_resource: str | None = None
    image_object: int | None = None
    image_object_generation: int | None = None
    image_object_sha256: str | None = None
    image_keys: tuple[str, ...] | None = None
    image_type: Any = None
    image_subtype: Any = None
    stream_sha256: str | None = None
    asset_sha256: str | None = None
    width: Any = None
    height: Any = None
    color_space: Any = None
    bits_per_component: Any = None
    filter_name: Any = None
    decode: Any = None
    decode_parms: Any = None
    image_length: Any = None
    image_alt: Any = None
    soft_mask_present: bool = False
    soft_mask_indirect: bool = False
    soft_mask_object: int | None = None
    soft_mask_object_generation: int | None = None
    soft_mask_object_sha256: str | None = None
    soft_mask_keys: tuple[str, ...] | None = None
    soft_mask_type: Any = None
    soft_mask_subtype: Any = None
    soft_mask_width: Any = None
    soft_mask_height: Any = None
    soft_mask_color_space: Any = None
    soft_mask_bits_per_component: Any = None
    soft_mask_filter: Any = None
    soft_mask_decode: Any = None
    soft_mask_decode_parms: Any = None
    soft_mask_length: Any = None
    soft_mask_stream_sha256: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    def semantic_fingerprint(self) -> tuple[Any, ...]:
        """Return identity-independent source-baseline semantics."""
        return (
            self.kind,
            self.content_stream_sha256,
            self.content_keys,
            self.content_length,
            self.content_filter,
            self.content_decode_parms,
            self.graphics_state,
            self.graphics_type,
            self.graphics_keys,
            self.ca,
            self.stroking_ca,
            self.text,
            self.font_resource,
            self.font_dictionary_sha256,
            self.font_keys,
            self.font_type,
            self.font_subtype,
            self.base_font,
            self.font_encoding,
            self.image_resource,
            self.image_type,
            self.image_subtype,
            self.image_keys,
            self.stream_sha256,
            self.asset_sha256,
            self.width,
            self.height,
            self.color_space,
            self.bits_per_component,
            self.filter_name,
            tuple(self.decode) if isinstance(self.decode, list) else self.decode,
            self.decode_parms,
            self.image_length,
            self.image_alt,
            self.soft_mask_present,
            self.soft_mask_indirect,
            self.soft_mask_keys,
            self.soft_mask_type,
            self.soft_mask_subtype,
            self.soft_mask_width,
            self.soft_mask_height,
            self.soft_mask_color_space,
            self.soft_mask_bits_per_component,
            self.soft_mask_filter,
            self.soft_mask_decode,
            self.soft_mask_decode_parms,
            self.soft_mask_length,
            self.soft_mask_stream_sha256,
            self.bbox,
        )


def scan_watermark_uses(
    model: PdfObjectModel,
    page: PageInfo,
) -> list[WatermarkUse]:
    """Scan dedicated watermark uses in page-content order."""
    uses: list[WatermarkUse] = []
    for reference in page.contents:
        obj = strict_indirect_object(model, reference)
        if obj is None:
            continue
        if not isinstance(obj.value, tuple):
            continue
        dictionary, content = obj.value
        if not isinstance(dictionary, PdfDict):
            continue
        for raw in _scan_content(content):
            if not _is_dedicated(raw):
                continue
            uses.append(_enrich_use(
                model,
                page,
                obj.obj_num,
                obj.gen_num,
                obj.sha256,
                hashlib.sha256(content).hexdigest(),
                dictionary,
                raw,
            ))
    return uses


def _scan_content(content: bytes) -> list[dict[str, Any]]:
    uses: list[dict[str, Any]] = []
    graphics_state: str | None = None
    font_resource: str | None = None
    matrix = IDENTITY_MATRIX
    clip: tuple[float, float, float, float] | None = None
    stack: list[tuple[Any, ...]] = []
    path_bbox: tuple[float, float, float, float] | None = None
    clip_pending = False
    for operator, operands in tokenize_content_stream(content):
        if operator == "q":
            stack.append((graphics_state, font_resource, matrix, clip))
        elif operator == "Q":
            if stack:
                graphics_state, font_resource, matrix, clip = stack.pop()
            path_bbox = None
            clip_pending = False
        elif operator == "gs" and operands:
            graphics_state = str(operands[-1])
        elif operator == "Tf" and operands:
            font_resource = str(operands[0])
        elif operator == "cm" and len(operands) >= 6:
            try:
                operand_matrix = tuple(float(value) for value in operands[-6:])
            except (TypeError, ValueError):
                continue
            matrix = concatenate_matrix(operand_matrix, matrix)
        elif operator == "re" and len(operands) >= 4:
            try:
                x, y, width, height = (float(value) for value in operands[-4:])
            except (TypeError, ValueError):
                path_bbox = None
                continue
            rectangle = (width, 0.0, 0.0, height, x, y)
            path_bbox = unit_square_bbox(concatenate_matrix(rectangle, matrix))
        elif operator in {"W", "W*"}:
            clip_pending = True
        elif operator in {"n", "S", "s", "f", "F", "f*", "B", "b"}:
            if clip_pending and path_bbox is not None:
                clip = _intersect_bbox(clip, path_bbox)
            path_bbox = None
            clip_pending = False
        elif operator in {"Tj", "TJ", "'", '"'}:
            text = _text_showing_value(operator, operands)
            if text:
                uses.append({
                    "kind": "text",
                    "graphics_state": graphics_state,
                    "text": text,
                    "font_resource": font_resource,
                })
        elif operator == "Do" and operands:
            bbox = unit_square_bbox(matrix)
            visible = _intersect_bbox(clip, bbox) if clip is not None else bbox
            if visible is not None:
                uses.append({
                    "kind": "image",
                    "graphics_state": graphics_state,
                    "image_resource": str(operands[-1]),
                    "bbox": visible,
                })
    return uses


def _text_showing_value(operator: str, operands: list[Any]) -> str:
    if not operands:
        return ""
    if operator == "TJ" and isinstance(operands[0], list):
        return "".join(
            str(item) for item in operands[0] if isinstance(item, (str, bytes))
        )
    position = 2 if operator == '"' else 0
    return str(operands[position]) if len(operands) > position else ""


def _is_dedicated(use: dict[str, Any]) -> bool:
    return any(
        value is not None and pattern.fullmatch(value) is not None
        for value, pattern in (
            (use.get("graphics_state"), _GRAPHICS_NAME),
            (use.get("image_resource"), _IMAGE_NAME),
            (use.get("font_resource"), _FONT_NAME),
        )
    )


def _enrich_use(
    model: PdfObjectModel,
    page: PageInfo,
    content_object: int,
    content_generation: int,
    content_hash: str,
    content_stream_hash: str,
    content_dictionary: PdfDict,
    use: dict[str, Any],
) -> WatermarkUse:
    state = resource_dictionary_entry(
        model,
        page,
        "/ExtGState",
        use.get("graphics_state"),
    )
    font = font_resource_record(model, page, use.get("font_resource"))
    image = resource_indirect_object(
        model,
        page,
        "/XObject",
        use.get("image_resource"),
    )
    image_dict, stream = (
        image.value
        if image is not None and isinstance(image.value, tuple)
        else (None, None)
    )
    soft_mask = soft_mask_record(model, image_dict)
    return WatermarkUse(
        kind=use["kind"],
        content_object=content_object,
        content_object_generation=content_generation,
        content_object_sha256=content_hash,
        content_stream_sha256=content_stream_hash,
        content_keys=tuple(sorted(content_dictionary.entries)),
        content_length=content_dictionary.get("/Length"),
        content_filter=content_dictionary.get("/Filter"),
        content_decode_parms=content_dictionary.get("/DecodeParms"),
        graphics_state=use.get("graphics_state"),
        graphics_type=state.get("/Type") if state is not None else None,
        graphics_keys=(tuple(sorted(state.entries)) if state is not None else None),
        ca=state.get("/ca") if state is not None else None,
        stroking_ca=state.get("/CA") if state is not None else None,
        text=use.get("text"),
        font_resource=use.get("font_resource"),
        font_object=font.object_number if font is not None else None,
        font_object_generation=(
            font.object_generation if font is not None else None
        ),
        font_object_sha256=font.object_sha256 if font is not None else None,
        font_dictionary_sha256=(
            font.dictionary_sha256 if font is not None else None
        ),
        font_keys=font.keys if font is not None else None,
        font_type=font.type_name if font is not None else None,
        font_subtype=font.subtype if font is not None else None,
        base_font=(f"/{font.base_font}" if font is not None else None),
        font_encoding=font.encoding if font is not None else None,
        image_resource=use.get("image_resource"),
        image_object=image.obj_num if image is not None else None,
        image_object_generation=image.gen_num if image is not None else None,
        image_object_sha256=image.sha256 if image is not None else None,
        image_keys=(
            tuple(sorted(image_dict.entries))
            if isinstance(image_dict, PdfDict)
            else None
        ),
        image_type=image_dict.get("/Type") if isinstance(image_dict, PdfDict) else None,
        image_subtype=(
            image_dict.get("/Subtype") if isinstance(image_dict, PdfDict) else None
        ),
        stream_sha256=hashlib.sha256(stream).hexdigest() if stream is not None else None,
        asset_sha256=(
            image_dict.get("/DSAssetSHA256")
            if isinstance(image_dict, PdfDict)
            else None
        ),
        width=image_dict.get("/Width") if isinstance(image_dict, PdfDict) else None,
        height=image_dict.get("/Height") if isinstance(image_dict, PdfDict) else None,
        color_space=(
            image_dict.get("/ColorSpace") if isinstance(image_dict, PdfDict) else None
        ),
        bits_per_component=(
            image_dict.get("/BitsPerComponent")
            if isinstance(image_dict, PdfDict)
            else None
        ),
        filter_name=image_dict.get("/Filter") if isinstance(image_dict, PdfDict) else None,
        decode=image_dict.get("/Decode") if isinstance(image_dict, PdfDict) else None,
        decode_parms=(
            image_dict.get("/DecodeParms") if isinstance(image_dict, PdfDict) else None
        ),
        image_length=(
            image_dict.get("/Length") if isinstance(image_dict, PdfDict) else None
        ),
        image_alt=(
            image_dict.get("/Alt") if isinstance(image_dict, PdfDict) else None
        ),
        soft_mask_present=soft_mask["present"],
        soft_mask_indirect=soft_mask["indirect"],
        soft_mask_object=soft_mask.get("object"),
        soft_mask_object_generation=soft_mask.get("object_generation"),
        soft_mask_object_sha256=soft_mask.get("object_sha256"),
        soft_mask_keys=soft_mask.get("keys"),
        soft_mask_type=soft_mask.get("type"),
        soft_mask_subtype=soft_mask.get("subtype"),
        soft_mask_width=soft_mask.get("width"),
        soft_mask_height=soft_mask.get("height"),
        soft_mask_color_space=soft_mask.get("color_space"),
        soft_mask_bits_per_component=soft_mask.get("bits_per_component"),
        soft_mask_filter=soft_mask.get("filter"),
        soft_mask_decode=soft_mask.get("decode"),
        soft_mask_decode_parms=soft_mask.get("decode_parms"),
        soft_mask_length=soft_mask.get("length"),
        soft_mask_stream_sha256=soft_mask.get("stream_sha256"),
        bbox=use.get("bbox"),
    )


def _intersect_bbox(
    left: tuple[float, float, float, float] | None,
    right: tuple[float, float, float, float],
) -> tuple[float, float, float, float] | None:
    if left is None:
        return right
    intersection = (
        max(left[0], right[0]),
        max(left[1], right[1]),
        min(left[2], right[2]),
        min(left[3], right[3]),
    )
    if intersection[0] >= intersection[2] or intersection[1] >= intersection[3]:
        return None
    return intersection
