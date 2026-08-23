"""Clone and attach editable page resources for PDF watermarks.

Module provenance: original Elftia-authored clean-room implementation.
"""

import re

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .create_layout import pdf_number
from .object_model import IndirectReference, PdfDict, PdfObjectModel


class WatermarkResourceRewriter:
    """Give each targeted page an editable resource dictionary."""

    def __init__(
        self,
        model: PdfObjectModel,
        opacity: float,
        image_object: int | None,
        added_objects: dict[int, bytes],
    ) -> None:
        self._model = model
        self._opacity = opacity
        self._image_object = image_object
        self._added_objects = added_objects
        self._clones: dict[tuple[str, int, int], int] = {}

    def rewrite_page(self, page_object: int, payload: bytes) -> bytes:
        """Inject inline resources or attach a clone of referenced/inherited ones."""
        page = self._model.objects[page_object].value
        if not isinstance(page, PdfDict):
            raise _unsupported_resources()
        local_resources = page.get("/Resources")
        if isinstance(local_resources, PdfDict):
            start, end = _inline_resource_bounds(payload)
            resources = _inject_resource_dictionary(
                payload[start:end],
                self._opacity,
                self._image_object,
            )
            return payload[:start] + resources + payload[end:]

        source_key, resources = self._find_resource_source(page_object)
        clone_object = self._clones.get(source_key)
        if clone_object is None:
            clone_object = self._next_object_number()
            clone = _inject_resource_dictionary(
                resources,
                self._opacity,
                self._image_object,
            )
            self._added_objects[clone_object] = (
                f"{clone_object} 0 obj\n".encode("ascii")
                + clone
                + b"\nendobj"
            )
            self._clones[source_key] = clone_object
        return _attach_page_resources(payload, clone_object, local_resources)

    def _find_resource_source(
        self,
        page_object: int,
    ) -> tuple[tuple[str, int, int], bytes]:
        current_object = page_object
        visited: set[int] = set()
        while current_object not in visited:
            visited.add(current_object)
            obj = self._model.objects.get(current_object)
            if obj is None or not isinstance(obj.value, PdfDict):
                break
            resources = obj.value.get("/Resources")
            if isinstance(resources, IndirectReference):
                resource_obj = self._model.get_object(resources)
                return (
                    ("reference", resources.obj_num, resources.gen_num),
                    _object_dictionary(resource_obj.payload_bytes),
                )
            if isinstance(resources, PdfDict):
                start, end = _inline_resource_bounds(obj.payload_bytes)
                return (
                    ("inline", current_object, 0),
                    obj.payload_bytes[start:end],
                )
            parent = obj.value.get("/Parent")
            if not isinstance(parent, IndirectReference):
                break
            current_object = parent.obj_num
        raise _unsupported_resources()

    def _next_object_number(self) -> int:
        return max(set(self._model.objects) | set(self._added_objects)) + 1


def _attach_page_resources(
    payload: bytes,
    resource_object: int,
    local_resources: object,
) -> bytes:
    entry = f"/Resources {resource_object} 0 R".encode("ascii")
    if isinstance(local_resources, IndirectReference):
        position = payload.find(b"/Resources")
        if position < 0:
            raise _unsupported_resources()
        value_start = position + len(b"/Resources")
        match = re.match(rb"\s*\d+\s+\d+\s+R", payload[value_start:])
        if match is None:
            raise _unsupported_resources()
        return payload[:position] + entry + payload[value_start + match.end():]

    start = payload.find(b"<<")
    end = _matching_dict_end(payload, start)
    if start < 0 or end is None:
        raise _unsupported_resources()
    return payload[:end - 2] + b" " + entry + b" " + payload[end - 2:]


def _object_dictionary(payload: bytes) -> bytes:
    start = payload.find(b"<<")
    end = _matching_dict_end(payload, start)
    if start < 0 or end is None:
        raise _unsupported_resources()
    return payload[start:end]


def _inline_resource_bounds(payload: bytes) -> tuple[int, int]:
    position = payload.find(b"/Resources")
    if position < 0:
        raise _unsupported_resources()
    value_start = position + len(b"/Resources")
    whitespace = re.match(rb"\s*", payload[value_start:])
    assert whitespace is not None
    start = value_start + whitespace.end()
    if payload[start:start + 2] != b"<<":
        raise _unsupported_resources()
    end = _matching_dict_end(payload, start)
    if end is None:
        raise _unsupported_resources()
    return start, end


def _inject_resource_dictionary(
    resources: bytes,
    opacity: float,
    image_object: int | None,
) -> bytes:
    opacity_entry = (
        f" /DSWMGS << /Type /ExtGState /ca {pdf_number(opacity)} "
        f"/CA {pdf_number(opacity)} >>"
    ).encode("ascii")
    resources = _inject_named_resource(resources, b"/ExtGState", opacity_entry)
    if image_object is not None:
        resources = _inject_named_resource(
            resources,
            b"/XObject",
            f" /DSWMImage {image_object} 0 R".encode("ascii"),
        )
    return resources


def _inject_named_resource(resources: bytes, category: bytes, entry: bytes) -> bytes:
    category_position = resources.find(category)
    if category_position >= 0:
        category_start = resources.find(b"<<", category_position + len(category))
        if category_start < 0:
            raise _unsupported_resources()
        category_end = _matching_dict_end(resources, category_start)
        if category_end is None:
            raise _unsupported_resources()
        return resources[:category_end - 2] + entry + resources[category_end - 2:]
    category_entry = b" " + category + b" <<" + entry + b" >>"
    return resources[:-2] + category_entry + resources[-2:]


def _matching_dict_end(data: bytes, start: int) -> int | None:
    if start < 0:
        return None
    depth = 0
    position = start
    while position + 1 < len(data):
        token = data[position:position + 2]
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


def _unsupported_resources() -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Watermark opacity requires an editable page resource dictionary.",
        status="enhancement_required",
        details={"capability": "pdf.watermark-resource-rewrite"},
    )
