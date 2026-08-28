"""Safe flat outline/bookmark add, update, and delete operations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mutation_writer import write_pdf_mutation
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel, parse_pdf
from .object_serialization import serialize_pdf_value
from .page_tree import walk_pages


@dataclass(frozen=True)
class _OutlineGraph:
    catalog: PdfObject
    root: PdfObject | None
    items: list[PdfObject]


def edit_outline(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
    *,
    build_manifest: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one flat outline mutation and preserve every unrelated object."""
    graph = _load_flat_graph(model)
    pages = walk_pages(model)
    mutations: dict[int, bytes] = {}
    additions: dict[int, bytes] = {}
    removed: set[int] = set()
    action = primitive["action"]
    if action == "add":
        result = _add_outline(model, graph, pages, primitive, mutations, additions)
    elif action == "update":
        result = _update_outline(graph, pages, primitive, mutations)
    else:
        result = _delete_outline(graph, primitive, mutations, removed)

    output_bytes = write_pdf_mutation(model, mutations, additions, removed)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(output_bytes)
    output_hashes = parse_pdf(output).object_hashes()
    manifest = build_manifest(
        input_hashes,
        output_hashes,
        changed=set(mutations),
        added=set(additions),
        removed=removed,
    )
    result["primitive"] = "outline"
    result["preservation"] = manifest
    return result, manifest


def _load_flat_graph(model: PdfObjectModel) -> _OutlineGraph:
    catalog = model.get_object(model.catalog_ref)
    if not isinstance(catalog.value, PdfDict):
        raise _unsafe("PDF Catalog is not a dictionary.")
    root_ref = catalog.value.get("/Outlines")
    if root_ref is None:
        return _OutlineGraph(catalog, None, [])
    if not isinstance(root_ref, IndirectReference):
        raise _unsupported_graph()
    root = model.get_object(root_ref)
    if not isinstance(root.value, PdfDict):
        raise _unsafe("PDF outline root is not a dictionary.")
    items: list[PdfObject] = []
    current = root.value.get("/First")
    visited: set[int] = set()
    while isinstance(current, IndirectReference):
        if current.obj_num in visited:
            raise _unsafe("PDF outline chain contains a cycle.")
        visited.add(current.obj_num)
        item = model.get_object(current)
        if not isinstance(item.value, PdfDict):
            raise _unsafe("PDF outline item is not a dictionary.")
        if item.value.get("/First") is not None or item.value.get("/A") is not None:
            raise _unsupported_graph()
        items.append(item)
        current = item.value.get("/Next")
    if current is not None:
        raise _unsupported_graph()
    return _OutlineGraph(catalog, root, items)


def _add_outline(
    model: PdfObjectModel,
    graph: _OutlineGraph,
    pages: list[Any],
    primitive: dict[str, Any],
    mutations: dict[int, bytes],
    additions: dict[int, bytes],
) -> dict[str, Any]:
    page_ref = _page_reference(pages, primitive["page"])
    next_object = max(model.objects) + 1
    if graph.root is None:
        root_ref = IndirectReference(next_object, 0)
        item_ref = IndirectReference(next_object + 1, 0)
        root_value = PdfDict({
            "/Type": "/Outlines",
            "/First": item_ref,
            "/Last": item_ref,
            "/Count": 1,
        })
        item_value = _new_item(primitive["title"], root_ref, page_ref)
        additions[root_ref.obj_num] = _object_payload(root_ref.obj_num, 0, root_value)
        additions[item_ref.obj_num] = _object_payload(item_ref.obj_num, 0, item_value)
        catalog_value = _copy_dict(graph.catalog.value)
        catalog_value.entries["/Outlines"] = root_ref
        mutations[graph.catalog.obj_num] = _object_payload(
            graph.catalog.obj_num,
            graph.catalog.gen_num,
            catalog_value,
        )
        index = 1
        item_object = item_ref.obj_num
    else:
        assert isinstance(graph.root.value, PdfDict)
        root_ref = IndirectReference(graph.root.obj_num, graph.root.gen_num)
        item_ref = IndirectReference(next_object, 0)
        item_value = _new_item(primitive["title"], root_ref, page_ref)
        if graph.items:
            previous = graph.items[-1]
            item_value.entries["/Prev"] = IndirectReference(previous.obj_num, previous.gen_num)
            previous_value = _copy_dict(previous.value)
            previous_value.entries["/Next"] = item_ref
            mutations[previous.obj_num] = _object_payload(
                previous.obj_num, previous.gen_num, previous_value
            )
        additions[item_ref.obj_num] = _object_payload(item_ref.obj_num, 0, item_value)
        root_value = _copy_dict(graph.root.value)
        root_value.entries["/First"] = root_value.get("/First", item_ref)
        root_value.entries["/Last"] = item_ref
        root_value.entries["/Count"] = len(graph.items) + 1
        mutations[graph.root.obj_num] = _object_payload(
            graph.root.obj_num, graph.root.gen_num, root_value
        )
        index = len(graph.items) + 1
        item_object = item_ref.obj_num
    return {
        "action": "add",
        "index": index,
        "title": primitive["title"],
        "page": primitive["page"],
        "outline_object": item_object,
    }


def _update_outline(
    graph: _OutlineGraph,
    pages: list[Any],
    primitive: dict[str, Any],
    mutations: dict[int, bytes],
) -> dict[str, Any]:
    item = _target_item(graph, primitive)
    assert isinstance(item.value, PdfDict)
    item_value = _copy_dict(item.value)
    if primitive.get("title") is not None:
        item_value.entries["/Title"] = primitive["title"]
    if primitive.get("page") is not None:
        item_value.entries["/Dest"] = [
            _page_reference(pages, primitive["page"]),
            "/Fit",
        ]
    mutations[item.obj_num] = _object_payload(item.obj_num, item.gen_num, item_value)
    return {
        "action": "update",
        "index": primitive["index"],
        "title": item_value.get("/Title", ""),
        "page": primitive.get("page"),
        "outline_object": item.obj_num,
    }


def _delete_outline(
    graph: _OutlineGraph,
    primitive: dict[str, Any],
    mutations: dict[int, bytes],
    removed: set[int],
) -> dict[str, Any]:
    item = _target_item(graph, primitive)
    assert graph.root is not None and isinstance(graph.root.value, PdfDict)
    index = primitive["index"] - 1
    previous = graph.items[index - 1] if index > 0 else None
    following = graph.items[index + 1] if index + 1 < len(graph.items) else None
    if previous is not None:
        assert isinstance(previous.value, PdfDict)
        value = _copy_dict(previous.value)
        if following is None:
            value.entries.pop("/Next", None)
        else:
            value.entries["/Next"] = IndirectReference(following.obj_num, following.gen_num)
        mutations[previous.obj_num] = _object_payload(previous.obj_num, previous.gen_num, value)
    if following is not None:
        assert isinstance(following.value, PdfDict)
        value = _copy_dict(following.value)
        if previous is None:
            value.entries.pop("/Prev", None)
        else:
            value.entries["/Prev"] = IndirectReference(previous.obj_num, previous.gen_num)
        mutations[following.obj_num] = _object_payload(following.obj_num, following.gen_num, value)
    root_value = _copy_dict(graph.root.value)
    if previous is None:
        if following is None:
            root_value.entries.pop("/First", None)
        else:
            root_value.entries["/First"] = IndirectReference(following.obj_num, following.gen_num)
    if following is None:
        if previous is None:
            root_value.entries.pop("/Last", None)
        else:
            root_value.entries["/Last"] = IndirectReference(previous.obj_num, previous.gen_num)
    root_value.entries["/Count"] = len(graph.items) - 1
    mutations[graph.root.obj_num] = _object_payload(
        graph.root.obj_num, graph.root.gen_num, root_value
    )
    removed.add(item.obj_num)
    assert isinstance(item.value, PdfDict)
    return {
        "action": "delete",
        "index": primitive["index"],
        "title": item.value.get("/Title", ""),
        "page": None,
        "outline_object": item.obj_num,
    }


def _target_item(graph: _OutlineGraph, primitive: dict[str, Any]) -> PdfObject:
    index = primitive["index"]
    if index > len(graph.items):
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Outline index is outside the current flat outline list.",
            status="invalid_request",
            details={"index": index, "outline_count": len(graph.items)},
        )
    item = graph.items[index - 1]
    assert isinstance(item.value, PdfDict)
    expected = primitive.get("expected_title")
    actual = item.value.get("/Title", "")
    if expected is not None and actual != expected:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Outline title precondition did not match.",
            status="invalid_request",
            details={"index": index, "expected_title": expected, "actual_title": actual},
        )
    return item


def _new_item(title: str, root: IndirectReference, page: IndirectReference) -> PdfDict:
    return PdfDict({
        "/Title": title,
        "/Parent": root,
        "/Dest": [page, "/Fit"],
    })


def _page_reference(pages: list[Any], page_number: int) -> IndirectReference:
    if page_number > len(pages):
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Outline destination page is outside the document.",
            status="invalid_request",
            details={"page": page_number, "page_count": len(pages)},
        )
    page = pages[page_number - 1]
    return IndirectReference(page.obj_num, 0)


def _copy_dict(value: PdfDict) -> PdfDict:
    return PdfDict(dict(value.entries))


def _object_payload(obj_num: int, gen_num: int, value: PdfDict) -> bytes:
    return (
        f"{obj_num} {gen_num} obj\n".encode("ascii")
        + serialize_pdf_value(value)
        + b"\nendobj"
    )


def _unsupported_graph() -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Core outline editing supports only flat destination-based outline chains.",
        status="enhancement_required",
        details={"capability": "pdf.outline-nested-or-action"},
    )


def _unsafe(message: str) -> DocumentSkillsError:
    return DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message)
