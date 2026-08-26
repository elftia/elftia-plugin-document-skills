"""Copy-on-write page resource and content binding for PDF watermarks.

Module provenance: original Elftia-authored clean-room implementation.
"""

from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .object_serialization import serialize_pdf_value


MAX_WATERMARK_RESOURCES = 4_096


def plan_watermark_graphics_state(
    model: PdfObjectModel,
    pages: list[Any],
) -> str:
    """Choose one collision-free ExtGState name across all target pages."""
    return _plan_resource_name(
        model,
        pages,
        category="/ExtGState",
        prefix="DSWMGS",
        capability="pdf.watermark-graphics-state-resources",
    )


def plan_watermark_image_resource(
    model: PdfObjectModel,
    pages: list[Any],
) -> str:
    """Choose one collision-free image XObject name across all target pages."""
    return _plan_resource_name(
        model,
        pages,
        category="/XObject",
        prefix="DSWMImage",
        capability="pdf.watermark-image-resources",
    )


class WatermarkResourceRewriter:
    """Attach dedicated watermark resources and a page-local content stream."""

    def __init__(
        self,
        model: PdfObjectModel,
        opacity: float,
        image_object: int | None,
        added_objects: dict[int, bytes],
        graphics_state_resource: str,
        image_resource: str | None,
        font_resource: str | None,
        font_object: int | None,
    ) -> None:
        self._model = model
        self._opacity = opacity
        self._image_object = image_object
        self._added_objects = added_objects
        self._graphics_state_resource = graphics_state_resource
        self._image_resource = image_resource
        self._font_resource = font_resource
        self._font_object = font_object
        self._clones: dict[tuple[str, int, int], int] = {}

    def rewrite_page(self, page_object: int, content_object: int) -> bytes:
        """Clone resources as needed and append one dedicated content reference."""
        obj = self._model.objects[page_object]
        page = obj.value
        if not isinstance(page, PdfDict):
            raise _unsupported_resources()
        rewritten = PdfDict(dict(page.entries))
        local_resources = page.get("/Resources")
        if isinstance(local_resources, PdfDict):
            rewritten.entries["/Resources"] = self._inject_resource_dictionary(
                local_resources,
            )
        else:
            source_key, resources = self._find_resource_source(page_object)
            clone_object = self._cloned_resources(source_key, resources)
            rewritten.entries["/Resources"] = IndirectReference(clone_object, 0)
        rewritten.entries["/Contents"] = _appended_contents(
            page.get("/Contents"),
            content_object,
        )
        return (
            f"{page_object} {obj.gen_num} obj\n".encode("ascii")
            + serialize_pdf_value(rewritten)
            + b"\nendobj"
        )

    def _cloned_resources(
        self,
        source_key: tuple[str, int, int],
        resources: PdfDict,
    ) -> int:
        clone_object = self._clones.get(source_key)
        if clone_object is not None:
            return clone_object
        clone_object = self._next_object_number()
        clone = serialize_pdf_value(self._inject_resource_dictionary(resources))
        self._added_objects[clone_object] = (
            f"{clone_object} 0 obj\n".encode("ascii")
            + clone
            + b"\nendobj"
        )
        self._clones[source_key] = clone_object
        return clone_object

    def _inject_resource_dictionary(self, resources: PdfDict) -> PdfDict:
        rewritten = PdfDict(dict(resources.entries))
        graphics = self._resource_category(rewritten.get("/ExtGState"))
        graphics_name = f"/{self._graphics_state_resource}"
        if graphics_name in graphics:
            raise _unsupported_resources()
        graphics.entries[graphics_name] = PdfDict({
            "/Type": "/ExtGState",
            "/ca": self._opacity,
            "/CA": self._opacity,
        })
        rewritten.entries["/ExtGState"] = graphics
        if self._image_object is not None and self._image_resource is not None:
            images = self._resource_category(rewritten.get("/XObject"))
            image_name = f"/{self._image_resource}"
            if image_name in images:
                raise _unsupported_resources()
            images.entries[image_name] = IndirectReference(self._image_object, 0)
            rewritten.entries["/XObject"] = images
        if self._font_object is not None and self._font_resource is not None:
            fonts = self._resource_category(rewritten.get("/Font"))
            name = f"/{self._font_resource}"
            if name in fonts:
                raise _unsupported_resources()
            fonts.entries[name] = IndirectReference(self._font_object, 0)
            rewritten.entries["/Font"] = fonts
        return rewritten

    def _resource_category(self, value: object) -> PdfDict:
        if value is None:
            return PdfDict()
        if isinstance(value, IndirectReference):
            value = self._model.get_object(value).value
        if not isinstance(value, PdfDict):
            raise _unsupported_resources()
        return PdfDict(dict(value.entries))

    def _find_resource_source(
        self,
        page_object: int,
    ) -> tuple[tuple[str, int, int], PdfDict]:
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
                if not isinstance(resource_obj.value, PdfDict):
                    raise _unsupported_resources()
                return (
                    ("reference", resources.obj_num, resources.gen_num),
                    resource_obj.value,
                )
            if isinstance(resources, PdfDict):
                return ("inline", current_object, 0), resources
            parent = obj.value.get("/Parent")
            if not isinstance(parent, IndirectReference):
                break
            current_object = parent.obj_num
        raise _unsupported_resources()

    def _next_object_number(self) -> int:
        occupied = (
            set(self._model.objects)
            | set(self._added_objects)
            | {self._model.trailer.size - 1}
        )
        return max(occupied) + 1


def _plan_resource_name(
    model: PdfObjectModel,
    pages: list[Any],
    *,
    category: str,
    prefix: str,
    capability: str,
) -> str:
    occupied: set[str] = set()
    for page in pages:
        resources = _resolved_dictionary(model, page.resources)
        if resources is None:
            continue
        entries = _resolved_dictionary(model, resources.get(category))
        if entries is not None:
            occupied.update(entries.entries)
    for index in range(MAX_WATERMARK_RESOURCES):
        resource = prefix if index == 0 else f"{prefix}{index}"
        if f"/{resource}" not in occupied:
            return resource
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "No collision-free watermark resource name is available.",
        status="enhancement_required",
        details={"capability": capability},
    )


def _resolved_dictionary(
    model: PdfObjectModel,
    value: object,
) -> PdfDict | None:
    if isinstance(value, IndirectReference):
        value = model.get_object(value).value
    return value if isinstance(value, PdfDict) else None


def _appended_contents(value: object, content_object: int) -> list[IndirectReference]:
    new_reference = IndirectReference(content_object, 0)
    if isinstance(value, IndirectReference):
        return [value, new_reference]
    if (
        isinstance(value, list)
        and value
        and all(isinstance(item, IndirectReference) for item in value)
    ):
        return [*value, new_reference]
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Watermarking requires indirect page content streams.",
        status="enhancement_required",
        details={"capability": "pdf.watermark-content-references"},
    )


def _unsupported_resources() -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Watermarking requires an editable page resource dictionary.",
        status="enhancement_required",
        details={"capability": "pdf.watermark-resource-rewrite"},
    )
