"""Bounded Form XObject generation for text and choice widget flattening."""

from dataclasses import dataclass
import math
import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import pdf_number
from .form_appearance_style import (
    DefaultAppearance,
    WidgetStyle,
    color_operator,
    escape_pdf_string,
    parse_default_appearance,
    parse_widget_style,
    require_supported_field_flags,
    unsupported,
)
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel
from .object_serialization import serialize_pdf_value


@dataclass
class _PageResources:
    object_number: int
    value: PdfDict
    xobjects: PdfDict


class FormAppearanceManager:
    """Generate appearances and attach per-page, non-shared resource clones."""

    def __init__(
        self,
        model: PdfObjectModel,
        added_objects: dict[int, bytes],
    ) -> None:
        self._model = model
        self._added_objects = added_objects
        self._pages: dict[int, _PageResources] = {}

    def add_text_widget(
        self,
        *,
        page_object: int,
        page_resources: PdfDict | None,
        field: PdfObject,
        widget: PdfObject,
        field_type: str,
        field_flags: int,
        value: str,
        rect: tuple[float, float, float, float],
        font_reference: IndirectReference,
    ) -> bytes:
        """Create one appearance and return its page ``Do`` placement."""
        require_supported_field_flags(field_type, field_flags)
        widget_value = _dictionary(widget, "Form widget")
        field_value = _dictionary(field, "Form field")
        if widget_value.get("/AP") is not None or field_value.get("/AP") is not None:
            unsupported("Existing text/choice appearances cannot be flattened losslessly.")
        quadding = self._effective_field_entry(field, widget, "/Q")
        if quadding not in (None, 0):
            unsupported("Non-left-aligned text/choice appearances are not implemented.")
        default_appearance = parse_default_appearance(
            self._effective_field_entry(field, widget, "/DA")
        )
        style = parse_widget_style(widget_value)
        width = rect[2] - rect[0]
        height = rect[3] - rect[1]
        if width <= 0 or height <= 0:
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Form widget Rect must have positive area.",
                status="invalid_request",
            )
        state = self._page_resources(page_object, page_resources)
        resource_name = self._resource_name(state.xobjects)
        appearance_object = self._allocate()
        bbox = (0.0, 0.0, width, height)
        matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        self._added_objects[appearance_object] = _appearance_object(
            appearance_object,
            value,
            bbox,
            matrix,
            font_reference,
            default_appearance,
            style,
        )
        state.xobjects.entries[resource_name] = IndirectReference(appearance_object, 0)
        self._store_page_resources(state)
        return _placement_operators(value, resource_name, rect, bbox, matrix)

    def rewrites_page(self, page_object: int) -> bool:
        return page_object in self._pages

    def rewrite_page_resources(self, page_object: int, payload: bytes) -> bytes:
        """Point a page at its private resource clone."""
        state = self._pages[page_object]
        page = self._model.objects[page_object]
        page_value = _dictionary(page, "Flatten target page")
        return _replace_page_resources(
            payload,
            page_value.get("/Resources"),
            state.object_number,
        )

    def _effective_field_entry(
        self,
        field: PdfObject,
        widget: PdfObject,
        key: str,
    ) -> Any:
        widget_value = _dictionary(widget, "Form widget")
        if widget_value.get(key) is not None:
            return widget_value.get(key)
        current = field
        visited: set[int] = set()
        while current.obj_num not in visited:
            visited.add(current.obj_num)
            value = _dictionary(current, "Form field")
            if value.get(key) is not None:
                return value.get(key)
            parent = value.get("/Parent")
            if not isinstance(parent, IndirectReference):
                break
            current = self._model.get_object(parent)
        catalog = _dictionary(
            self._model.get_object(self._model.catalog_ref),
            "PDF Catalog",
        )
        acroform = catalog.get("/AcroForm")
        if isinstance(acroform, IndirectReference):
            value = _dictionary(self._model.get_object(acroform), "AcroForm")
            return value.get(key)
        return None

    def _page_resources(
        self,
        page_object: int,
        resources: PdfDict | None,
    ) -> _PageResources:
        existing = self._pages.get(page_object)
        if existing is not None:
            return existing
        if resources is None:
            unsupported("Text/choice flatten requires effective page resources.")
        cloned = PdfDict(dict(resources.entries))
        xobjects = resources.get("/XObject")
        if isinstance(xobjects, IndirectReference):
            resolved = self._model.get_object(xobjects).value
            if not isinstance(resolved, PdfDict):
                unsupported("Page XObject resources are malformed.")
            xobjects = resolved
        if xobjects is None:
            cloned_xobjects = PdfDict()
        elif isinstance(xobjects, PdfDict):
            cloned_xobjects = PdfDict(dict(xobjects.entries))
        else:
            unsupported("Page XObject resources are malformed.")
        cloned.entries["/XObject"] = cloned_xobjects
        state = _PageResources(self._allocate(), cloned, cloned_xobjects)
        self._pages[page_object] = state
        self._store_page_resources(state)
        return state

    def _resource_name(self, xobjects: PdfDict) -> str:
        index = 1
        while f"/DSForm{index}" in xobjects.entries:
            index += 1
        return f"/DSForm{index}"

    def _store_page_resources(self, state: _PageResources) -> None:
        self._added_objects[state.object_number] = (
            f"{state.object_number} 0 obj\n".encode("ascii")
            + serialize_pdf_value(state.value)
            + b"\nendobj"
        )

    def _allocate(self) -> int:
        return max(set(self._model.objects) | set(self._added_objects)) + 1


def _appearance_object(
    object_number: int,
    value: str,
    bbox: tuple[float, float, float, float],
    matrix: tuple[float, float, float, float, float, float],
    font_reference: IndirectReference,
    default: DefaultAppearance,
    style: WidgetStyle,
) -> bytes:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    operators = ["q", f"0 0 {pdf_number(width)} {pdf_number(height)} re W n"]
    if style.background is not None:
        operators.extend([
            color_operator(style.background, stroke=False),
            f"0 0 {pdf_number(width)} {pdf_number(height)} re f",
        ])
    if style.border_width > 0:
        inset = style.border_width / 2.0
        operators.extend([
            color_operator(style.border, stroke=True),
            f"{pdf_number(style.border_width)} w",
            (
                f"{pdf_number(inset)} {pdf_number(inset)} "
                f"{pdf_number(max(0.0, width - style.border_width))} "
                f"{pdf_number(max(0.0, height - style.border_width))} re S"
            ),
        ])
    padding = max(2.0, style.border_width + 1.0)
    baseline = max(padding, (height - default.font_size) / 2.0 + 1.0)
    operators.extend([
        "BT",
        f"/Helv {pdf_number(default.font_size)} Tf",
        color_operator(default.color, stroke=False),
        f"{pdf_number(padding)} {pdf_number(baseline)} Td",
        f"({escape_pdf_string(value)}) Tj",
        "ET",
        "Q",
    ])
    stream = "\n".join(operators).encode("latin-1", errors="strict")
    bbox_text = " ".join(pdf_number(component) for component in bbox)
    matrix_text = " ".join(pdf_number(component) for component in matrix)
    dictionary = (
        f"<< /Type /XObject /Subtype /Form /FormType 1 /BBox [{bbox_text}] "
        f"/Matrix [{matrix_text}] /Resources << /Font << /Helv "
        f"{font_reference.obj_num} {font_reference.gen_num} R >> >> "
        f"/Length {len(stream)} >>"
    ).encode("ascii")
    return (
        f"{object_number} 0 obj\n".encode("ascii")
        + dictionary
        + b"\nstream\n"
        + stream
        + b"\nendstream\nendobj"
    )


def _placement_operators(
    value: str,
    resource_name: str,
    rect: tuple[float, float, float, float],
    bbox: tuple[float, float, float, float],
    matrix: tuple[float, float, float, float, float, float],
) -> bytes:
    transform = _placement_matrix(rect, bbox, matrix)
    transform_text = " ".join(pdf_number(component) for component in transform)
    actual_text = value.encode("latin-1", errors="strict").hex().upper()
    return (
        f"\n/Span << /ActualText <{actual_text}> >> BDC\nq\n{transform_text} cm\n"
        f"{resource_name} Do\nQ\nEMC\n"
    ).encode("latin-1", errors="strict")


def _placement_matrix(
    rect: tuple[float, float, float, float],
    bbox: tuple[float, float, float, float],
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    target = (
        (rect[2] - rect[0]) / width,
        0.0,
        0.0,
        (rect[3] - rect[1]) / height,
        rect[0] - bbox[0] * ((rect[2] - rect[0]) / width),
        rect[1] - bbox[1] * ((rect[3] - rect[1]) / height),
    )
    return _compose(target, _inverse(matrix))


def _inverse(
    matrix: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    a, b, c, d, e, f = matrix
    determinant = a * d - b * c
    if not math.isfinite(determinant) or abs(determinant) < 1e-12:
        unsupported("Form appearance Matrix is not invertible.")
    return (
        d / determinant,
        -b / determinant,
        -c / determinant,
        a / determinant,
        (c * f - d * e) / determinant,
        (b * e - a * f) / determinant,
    )


def _compose(
    left: tuple[float, float, float, float, float, float],
    right: tuple[float, float, float, float, float, float],
) -> tuple[float, float, float, float, float, float]:
    la, lb, lc, ld, le, lf = left
    ra, rb, rc, rd, re, rf = right
    return (
        la * ra + lc * rb,
        lb * ra + ld * rb,
        la * rc + lc * rd,
        lb * rc + ld * rd,
        la * re + lc * rf + le,
        lb * re + ld * rf + lf,
    )


def _replace_page_resources(
    payload: bytes,
    local_resources: Any,
    resource_object: int,
) -> bytes:
    entry = f"/Resources {resource_object} 0 R".encode("ascii")
    if isinstance(local_resources, IndirectReference):
        pattern = (
            rb"/Resources\s+"
            + str(local_resources.obj_num).encode("ascii")
            + rb"\s+"
            + str(local_resources.gen_num).encode("ascii")
            + rb"\s+R"
        )
        updated, count = re.subn(pattern, entry, payload, count=1)
        if count == 1:
            return updated
        unsupported("Referenced page resources cannot be rewritten safely.")
    if isinstance(local_resources, PdfDict):
        position = payload.find(b"/Resources")
        start = payload.find(b"<<", position + len(b"/Resources"))
        end = _matching_dictionary_end(payload, start)
        if position >= 0 and start >= 0 and end is not None:
            return payload[:position] + entry + payload[end:]
        unsupported("Inline page resources cannot be rewritten safely.")
    if local_resources is None:
        end = payload.rfind(b">>")
        if end >= 0:
            return payload[:end] + b" " + entry + b" " + payload[end:]
    unsupported("Page resources cannot be rewritten safely.")


def _matching_dictionary_end(payload: bytes, start: int) -> int | None:
    if start < 0:
        return None
    depth = 0
    position = start
    while position + 1 < len(payload):
        token = payload[position:position + 2]
        if token == b"<<":
            depth += 1
            position += 2
            continue
        if token == b">>":
            depth -= 1
            position += 2
            if depth == 0:
                return position
            continue
        position += 1
    return None


def _dictionary(obj: PdfObject, label: str) -> PdfDict:
    if not isinstance(obj.value, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, f"{label} is not a dictionary.")
    return obj.value
