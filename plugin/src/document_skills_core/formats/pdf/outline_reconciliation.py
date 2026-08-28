"""Flat destination-outline projection for page sequence mutations."""

from typing import Any

from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .outlines_edit import (
    _load_flat_graph,
    _new_item,
    _object_payload,
    _unsafe,
    _unsupported_graph,
)
from .page_tree import walk_pages


def selected_flat_outlines(
    model: PdfObjectModel,
    selected_pages: list[int],
) -> list[dict[str, Any]] | None:
    """Project retained flat `/Fit` outlines onto a new page order."""
    graph = _load_flat_graph(model)
    if graph.root is None:
        return None
    pages = walk_pages(model)
    source_page_by_object = {
        page.obj_num: page.page_number
        for page in pages
    }
    output_page_by_source = {
        source_page: output_page
        for output_page, source_page in enumerate(selected_pages, start=1)
    }
    retained: list[dict[str, Any]] = []
    for item in graph.items:
        assert isinstance(item.value, PdfDict)
        title = item.value.get("/Title")
        destination = item.value.get("/Dest")
        if (
            not isinstance(title, str)
            or not isinstance(destination, list)
            or len(destination) != 2
            or not isinstance(destination[0], IndirectReference)
            or destination[1] != "/Fit"
        ):
            raise _unsupported_graph()
        source_page = source_page_by_object.get(destination[0].obj_num)
        if source_page is None:
            raise _unsafe("PDF outline destination does not reference a page leaf.")
        output_page = output_page_by_source.get(source_page)
        if output_page is not None:
            retained.append({"title": title, "page": output_page})
    return retained


def build_flat_outline_objects(
    outlines: list[dict[str, Any]] | None,
    page_refs: list[int],
    start_object: int,
) -> tuple[int | None, dict[int, bytes]]:
    """Build a fresh flat outline graph targeting output page references."""
    if not outlines:
        return None, {}
    root_ref = IndirectReference(start_object, 0)
    item_refs = [
        IndirectReference(start_object + index, 0)
        for index in range(1, len(outlines) + 1)
    ]
    root = PdfDict({
        "/Type": "/Outlines",
        "/First": item_refs[0],
        "/Last": item_refs[-1],
        "/Count": len(item_refs),
    })
    objects = {root_ref.obj_num: _object_payload(root_ref.obj_num, 0, root)}
    for index, (outline, item_ref) in enumerate(zip(outlines, item_refs)):
        page = outline["page"]
        if not 1 <= page <= len(page_refs):
            raise _unsafe("Reconciled outline destination is outside the output pages.")
        value = _new_item(
            outline["title"],
            root_ref,
            IndirectReference(page_refs[page - 1], 0),
        )
        if index > 0:
            value.entries["/Prev"] = item_refs[index - 1]
        if index + 1 < len(item_refs):
            value.entries["/Next"] = item_refs[index + 1]
        objects[item_ref.obj_num] = _object_payload(item_ref.obj_num, 0, value)
    return root_ref.obj_num, objects


def outline_catalog_entry(root_object: int | None) -> bytes:
    if root_object is None:
        return b""
    return f" /Outlines {root_object} 0 R".encode("ascii")
