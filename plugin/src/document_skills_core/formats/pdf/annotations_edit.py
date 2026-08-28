"""Safe add, update, and delete support for PDF text annotations.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mutation_writer import write_pdf_mutation
from .object_model import IndirectReference, PdfDict, PdfObject, PdfObjectModel, parse_pdf
from .object_serialization import serialize_pdf_value
from .page_tree import PageInfo, walk_pages


def edit_annotation(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
    *,
    build_manifest: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Apply one annotation mutation without authorizing annotation actions."""
    page, page_object, annotations = _page_annotations(model, primitive["page"])
    mutations: dict[int, bytes] = {}
    additions: dict[int, bytes] = {}
    removed: set[int] = set()
    action = primitive["action"]
    if action == "add":
        result = _add_annotation(
            model, page, page_object, annotations, primitive, mutations, additions
        )
    elif action == "update":
        result = _update_annotation(
            model, annotations, primitive, mutations
        )
    else:
        result = _delete_annotation(
            model, page_object, annotations, primitive, mutations, removed
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(write_pdf_mutation(model, mutations, additions, removed))
    output_hashes = parse_pdf(output).object_hashes()
    manifest = build_manifest(
        input_hashes,
        output_hashes,
        changed=set(mutations),
        added=set(additions),
        removed=removed,
    )
    result["primitive"] = "annotation"
    result["preservation"] = manifest
    return result, manifest


def _page_annotations(
    model: PdfObjectModel,
    page_number: int,
) -> tuple[PageInfo, PdfObject, list[Any]]:
    pages = walk_pages(model)
    if page_number > len(pages):
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Annotation page is outside the document.",
            status="invalid_request",
            details={"page": page_number, "page_count": len(pages)},
        )
    page = pages[page_number - 1]
    page_object = model.objects[page.obj_num]
    if not isinstance(page_object.value, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PDF page is not a dictionary.")
    annotations = page_object.value.get("/Annots", [])
    if not isinstance(annotations, list):
        raise _unsupported_annotation()
    return page, page_object, list(annotations)


def _add_annotation(
    model: PdfObjectModel,
    page: PageInfo,
    page_object: PdfObject,
    annotations: list[Any],
    primitive: dict[str, Any],
    mutations: dict[int, bytes],
    additions: dict[int, bytes],
) -> dict[str, Any]:
    annotation_object = max(model.objects) + 1
    annotation_ref = IndirectReference(annotation_object, 0)
    page_ref = IndirectReference(page.obj_num, page_object.gen_num)
    value = PdfDict({
        "/Type": "/Annot",
        "/Subtype": "/Text",
        "/Rect": primitive["rectangle"],
        "/Contents": primitive["contents"],
        "/C": primitive["color"],
        "/F": 4,
        "/P": page_ref,
        "/Name": "/Comment",
    })
    if primitive.get("title") is not None:
        value.entries["/T"] = primitive["title"]
    additions[annotation_object] = _object_payload(annotation_object, 0, value)
    page_value = _copy_dict(page_object.value)
    page_value.entries["/Annots"] = annotations + [annotation_ref]
    mutations[page_object.obj_num] = _object_payload(
        page_object.obj_num, page_object.gen_num, page_value
    )
    return {
        "action": "add",
        "page": page.page_number,
        "index": len(annotations) + 1,
        "annotation_object": annotation_object,
    }


def _update_annotation(
    model: PdfObjectModel,
    annotations: list[Any],
    primitive: dict[str, Any],
    mutations: dict[int, bytes],
) -> dict[str, Any]:
    annotation = _target_annotation(model, annotations, primitive)
    assert isinstance(annotation.value, PdfDict)
    value = _copy_dict(annotation.value)
    for request_key, pdf_key in (
        ("rectangle", "/Rect"),
        ("contents", "/Contents"),
        ("title", "/T"),
        ("color", "/C"),
    ):
        if primitive.get(request_key) is not None:
            value.entries[pdf_key] = primitive[request_key]
    mutations[annotation.obj_num] = _object_payload(
        annotation.obj_num, annotation.gen_num, value
    )
    return {
        "action": "update",
        "page": primitive["page"],
        "index": primitive["index"],
        "annotation_object": annotation.obj_num,
    }


def _delete_annotation(
    model: PdfObjectModel,
    page_object: PdfObject,
    annotations: list[Any],
    primitive: dict[str, Any],
    mutations: dict[int, bytes],
    removed: set[int],
) -> dict[str, Any]:
    annotation = _target_annotation(model, annotations, primitive)
    index = primitive["index"] - 1
    _assert_exclusive_delete_reference(model, page_object, annotation, index)
    remaining = annotations[:index] + annotations[index + 1:]
    assert isinstance(page_object.value, PdfDict)
    page_value = _copy_dict(page_object.value)
    if remaining:
        page_value.entries["/Annots"] = remaining
    else:
        page_value.entries.pop("/Annots", None)
    mutations[page_object.obj_num] = _object_payload(
        page_object.obj_num, page_object.gen_num, page_value
    )
    removed.add(annotation.obj_num)
    return {
        "action": "delete",
        "page": primitive["page"],
        "index": primitive["index"],
        "annotation_object": annotation.obj_num,
    }


def _target_annotation(
    model: PdfObjectModel,
    annotations: list[Any],
    primitive: dict[str, Any],
) -> PdfObject:
    index = primitive["index"]
    if index > len(annotations):
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Annotation index is outside the page annotation list.",
            status="invalid_request",
            details={"index": index, "annotation_count": len(annotations)},
        )
    reference = annotations[index - 1]
    if not isinstance(reference, IndirectReference):
        raise _unsupported_annotation()
    annotation = model.get_object(reference)
    value = annotation.value
    if (
        not isinstance(value, PdfDict)
        or value.get("/Subtype") != "/Text"
        or value.get("/A") is not None
        or value.get("/AA") is not None
    ):
        raise _unsupported_annotation()
    expected = primitive.get("expected_contents")
    actual = value.get("/Contents", "")
    if expected is not None and actual != expected:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Annotation contents precondition did not match.",
            status="invalid_request",
            details={"expected_contents": expected, "actual_contents": actual},
        )
    return annotation


def _assert_exclusive_delete_reference(
    model: PdfObjectModel,
    page_object: PdfObject,
    annotation: PdfObject,
    index: int,
) -> None:
    allowed_path = ("/Annots", index)
    allowed_count = 0
    unexpected_count = 0
    unexpected: list[dict[str, Any]] = []
    for owner_number in sorted(model.objects):
        owner = model.objects[owner_number]
        for path, reference in _iter_references(owner.value):
            if reference.obj_num != annotation.obj_num:
                continue
            if (
                owner_number == page_object.obj_num
                and path == allowed_path
                and reference.gen_num == annotation.gen_num
            ):
                allowed_count += 1
                continue
            unexpected_count += 1
            if len(unexpected) < 16:
                unexpected.append(
                    {
                        "owner_object": owner_number,
                        "path": list(path),
                        "generation": reference.gen_num,
                    }
                )
    if allowed_count == 1 and unexpected_count == 0:
        return
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Text annotation deletion requires one exclusive page /Annots reference.",
        status="enhancement_required",
        details={
            "capability": "pdf.annotation-delete-exclusive-reference",
            "annotation_object": annotation.obj_num,
            "allowed_reference_count": allowed_count,
            "unexpected_reference_count": unexpected_count,
            "unexpected_references": unexpected,
        },
    )


def _iter_references(
    value: Any,
    path: tuple[str | int, ...] = (),
    depth: int = 0,
):
    if depth > 64:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PDF object graph exceeds the annotation reference scan depth.",
        )
    if isinstance(value, IndirectReference):
        yield path, value
    elif isinstance(value, PdfDict):
        for key in sorted(value.entries):
            yield from _iter_references(
                value.entries[key],
                path + (key,),
                depth + 1,
            )
    elif isinstance(value, (list, tuple)):
        for item_index, item in enumerate(value):
            yield from _iter_references(
                item,
                path + (item_index,),
                depth + 1,
            )


def _copy_dict(value: PdfDict) -> PdfDict:
    return PdfDict(dict(value.entries))


def _object_payload(obj_num: int, gen_num: int, value: PdfDict) -> bytes:
    return (
        f"{obj_num} {gen_num} obj\n".encode("ascii")
        + serialize_pdf_value(value)
        + b"\nendobj"
    )


def _unsupported_annotation() -> DocumentSkillsError:
    return DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        "Core annotation editing supports indirect, action-free Text annotations only.",
        status="enhancement_required",
        details={"capability": "pdf.annotation-safe-subset"},
    )
