"""Catalog → Pages → Page leaf walk with page-box inheritance.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import (
    ART_BOX,
    BLEED_BOX,
    CROP_BOX,
    MEDIA_BOX,
    TRIM_BOX,
)
from .object_model import (
    IndirectReference,
    PdfDict,
    PdfObject,
    PdfObjectModel,
)


@dataclass(frozen=True)
class PageInfo:
    """Resolved page information after inheritance walk."""
    page_number: int
    obj_num: int
    media_box: tuple[float, float, float, float]
    crop_box: tuple[float, float, float, float] | None
    bleed_box: tuple[float, float, float, float] | None
    trim_box: tuple[float, float, float, float] | None
    art_box: tuple[float, float, float, float] | None
    rotation: int
    resources: PdfDict | None
    contents: list[IndirectReference]


def walk_pages(model: PdfObjectModel) -> list[PageInfo]:
    """Walk Catalog → /Pages → /Kids recursively to collect Page leaves in order."""
    catalog_obj = model.get_object(model.catalog_ref)
    catalog = _shallow_resolve(model, catalog_obj.value)
    if not isinstance(catalog, PdfDict):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF Catalog is not a dictionary.",
        )
    pages_ref = catalog.get("/Pages")
    if not isinstance(pages_ref, IndirectReference):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF Catalog does not contain a /Pages reference.",
        )
    pages: list[PageInfo] = []
    _walk_kids(model, pages_ref, pages, inherited={}, page_count=[0], visited=set())
    if not pages:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF page tree has no page leaves.",
        )
    return pages


def _shallow_resolve(model: PdfObjectModel, value: Any) -> Any:
    """Resolve one level of indirect reference without deep recursion."""
    if isinstance(value, IndirectReference):
        obj = model.get_object(value)
        return obj.value
    return value


def _walk_kids(
    model: PdfObjectModel,
    node_ref: IndirectReference,
    pages: list[PageInfo],
    inherited: dict[str, Any],
    page_count: list[int],
    visited: set[int],
) -> None:
    """Recursively walk /Kids, collecting Page leaves with inherited values."""
    if node_ref.obj_num in visited:
        return
    visited.add(node_ref.obj_num)
    node_obj = model.get_object(node_ref)
    node = _shallow_resolve(model, node_obj.value)
    if not isinstance(node, PdfDict):
        return
    node_type = node.get("/Type")
    if node_type == "/Page":
        page_count[0] += 1
        info = _build_page_info(model, node_obj, node, inherited, page_count[0])
        pages.append(info)
        return
    # Intermediate /Pages node — collect inherited values
    new_inherited = dict(inherited)
    for key in (MEDIA_BOX, CROP_BOX, BLEED_BOX, TRIM_BOX, ART_BOX, "/Resources", "/Rotate"):
        val = node.get(key)
        if val is not None:
            new_inherited[key] = val
    kids = node.get("/Kids")
    if not isinstance(kids, list):
        return
    for kid in kids:
        if isinstance(kid, IndirectReference):
            _walk_kids(model, kid, pages, new_inherited, page_count, visited)


def _build_page_info(
    model: PdfObjectModel,
    obj: PdfObject,
    page: PdfDict,
    inherited: dict[str, Any],
    page_number: int,
) -> PageInfo:
    """Build a PageInfo from a /Page dictionary with inheritance resolved."""
    media_box = _resolve_box(page, inherited, MEDIA_BOX)
    if media_box is None:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            f"PDF page {page_number} has no MediaBox.",
        )
    crop_box = _resolve_box(page, inherited, CROP_BOX)
    bleed_box = _resolve_box(page, inherited, BLEED_BOX)
    trim_box = _resolve_box(page, inherited, TRIM_BOX)
    art_box = _resolve_box(page, inherited, ART_BOX)
    rotation = page.get("/Rotate", inherited.get("/Rotate", 0))
    if not isinstance(rotation, int):
        rotation = 0
    resources = page.get("/Resources", inherited.get("/Resources"))
    if isinstance(resources, IndirectReference):
        res_obj = model.get_object(resources)
        resources = res_obj.value
    if not isinstance(resources, PdfDict):
        resources = None
    contents = page.get("/Contents")
    content_refs: list[IndirectReference] = []
    if isinstance(contents, IndirectReference):
        content_refs = [contents]
    elif isinstance(contents, list):
        for c in contents:
            if isinstance(c, IndirectReference):
                content_refs.append(c)
    return PageInfo(
        page_number=page_number,
        obj_num=obj.obj_num,
        media_box=media_box,
        crop_box=crop_box,
        bleed_box=bleed_box,
        trim_box=trim_box,
        art_box=art_box,
        rotation=rotation,
        resources=resources,
        contents=content_refs,
    )


def _resolve_box(
    page: PdfDict, inherited: dict[str, Any], key: str
) -> tuple[float, float, float, float] | None:
    """Resolve a page box from the page dict or inherited values."""
    val = page.get(key, inherited.get(key))
    if val is None:
        return None
    if isinstance(val, list) and len(val) >= 4:
        try:
            return (float(val[0]), float(val[1]), float(val[2]), float(val[3]))
        except (TypeError, ValueError):
            return None
    return None
