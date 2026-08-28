"""Deterministic tagged-PDF structure for created images with alternative text."""

from collections import defaultdict
from typing import Any, Protocol

from .create_text_utils import pdf_text_string
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .page_tree import PageInfo


class StructureObjectWriter(Protocol):
    def add_object(self, content: bytes) -> int: ...

    def reserve_object(self) -> int: ...

    def replace_object(self, obj_num: int, content: bytes) -> None: ...


def page_struct_parent(page: dict[str, Any], page_index: int) -> int | None:
    """Return the stable ParentTree key only when a page has a tagged image."""
    if any(
        block.get("type") == "image"
        and isinstance(block.get("image"), dict)
        and bool(block["image"].get("alt"))
        for block in page.get("blocks", [])
    ):
        return page_index
    return None


def finalize_image_structure(
    writer: StructureObjectWriter,
    images: list[dict[str, Any]],
    page_objects: list[int],
) -> int | None:
    """Emit the StructTreeRoot, Figure elements, and ParentTree."""
    tagged = [record for record in images if record.get("alt")]
    if not tagged:
        return None

    structure_root = writer.reserve_object()
    children: list[int] = []
    by_parent: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for record in tagged:
        page_number = _positive_int(record.get("page"), "page")
        mcid = _non_negative_int(record.get("mcid"), "mcid")
        parent = _non_negative_int(record.get("struct_parent"), "struct_parent")
        if page_number > len(page_objects):
            raise ValueError("Tagged image page is outside the emitted page list")
        alt = record.get("alt")
        if not isinstance(alt, str) or not alt:
            raise ValueError("Tagged image alternative text must be non-empty")
        element = writer.add_object(
            (
                f"<< /Type /StructElem /S /Figure /P {structure_root} 0 R "
                f"/Pg {page_objects[page_number - 1]} 0 R /K {mcid} "
                f"/Alt {pdf_text_string(alt)} >>"
            ).encode("ascii")
        )
        record["structure_object"] = element
        children.append(element)
        by_parent[parent].append((mcid, element))

    number_entries: list[str] = []
    for parent in sorted(by_parent):
        ordered = sorted(by_parent[parent])
        if [mcid for mcid, _element in ordered] != list(range(len(ordered))):
            raise ValueError("Tagged image MCIDs must be contiguous on each page")
        references = " ".join(f"{element} 0 R" for _mcid, element in ordered)
        number_entries.append(f"{parent} [{references}]")
    parent_tree = writer.add_object(
        f"<< /Nums [{' '.join(number_entries)}] >>".encode("ascii")
    )
    child_references = " ".join(f"{child} 0 R" for child in children)
    next_key = max(by_parent) + 1
    writer.replace_object(
        structure_root,
        (
            f"<< /Type /StructTreeRoot /K [{child_references}] "
            f"/ParentTree {parent_tree} 0 R /ParentTreeNextKey {next_key} >>"
        ).encode("ascii"),
    )
    return structure_root


def split_image_evidence(
    images: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep the established image record stable and publish associations separately."""
    structure_fields = {"alt", "mcid", "struct_parent", "structure_object"}
    public_images = [
        {key: value for key, value in record.items() if key not in structure_fields}
        for record in images
    ]
    associations = [
        {
            "page": record["page"],
            "block_index": record["block_index"],
            "image_object": record["image_object"],
            "bbox": record["bbox"],
            "alt": record.get("alt"),
            "mcid": record.get("mcid"),
            "struct_parent": record.get("struct_parent"),
            "structure_object": record.get("structure_object"),
        }
        for record in images
    ]
    return public_images, associations


def image_structure_mismatches(
    model: PdfObjectModel,
    pages: list[PageInfo],
    expected: list[dict[str, Any]],
    actual: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[tuple[int, int], dict[str, Any]]]:
    """Validate exact Figure/MCID/Page/ParentTree associations after reopen."""
    failures: list[dict[str, Any]] = []
    evidence: dict[tuple[int, int], dict[str, Any]] = {}
    tagged = [record for record in expected if record.get("alt")]
    expected_draw_keys = {
        (record.get("page"), record.get("image_object")): record.get("mcid")
        for record in expected
    }
    actual_draw_keys = defaultdict(list)
    for record in actual:
        actual_draw_keys[(record.get("page"), record.get("object"))].append(
            record.get("mcid")
        )
    for key, mcid in expected_draw_keys.items():
        if actual_draw_keys.get(key) != [mcid]:
            failures.append({
                "reason": "image-marked-content-association",
                "page": key[0],
                "object": key[1],
            })
    if set(actual_draw_keys) != set(expected_draw_keys):
        failures.append({"reason": "unexpected-image-marked-content-draw"})
    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        return [{"reason": "image-structure-catalog"}], evidence
    if not tagged:
        if catalog.get("/StructTreeRoot") is not None or catalog.get("/MarkInfo") is not None:
            failures.append({"reason": "unexpected-image-structure-tree"})
        if any(record.get("mcid") is not None for record in actual):
            failures.append({"reason": "unexpected-image-marked-content"})
        if any(_page_dictionary(model, page).get("/StructParents") is not None for page in pages):
            failures.append({"reason": "unexpected-image-struct-parents"})
        return failures, evidence

    root_ref = catalog.get("/StructTreeRoot")
    mark_info = catalog.get("/MarkInfo")
    if not isinstance(mark_info, PdfDict) or mark_info.get("/Marked") is not True:
        failures.append({"reason": "missing-image-mark-info"})
    if not isinstance(root_ref, IndirectReference):
        return failures + [{"reason": "missing-image-structure-root"}], evidence
    root = model.get_object(root_ref).value
    if not isinstance(root, PdfDict) or root.get("/Type") != "/StructTreeRoot":
        return failures + [{"reason": "invalid-image-structure-root"}], evidence

    expected_objects = [record.get("structure_object") for record in tagged]
    root_children = _reference_numbers(root.get("/K"))
    if root_children != expected_objects:
        failures.append({"reason": "image-structure-kids"})

    parent_ref = root.get("/ParentTree")
    parent_tree = (
        model.get_object(parent_ref).value
        if isinstance(parent_ref, IndirectReference)
        else None
    )
    parent_map = _parent_number_tree(parent_tree)
    expected_parent_map: dict[int, list[int]] = defaultdict(list)
    page_by_number = {page.page_number: page for page in pages}
    for record in tagged:
        page = page_by_number.get(record.get("page"))
        element_number = record.get("structure_object")
        mcid = record.get("mcid")
        parent = record.get("struct_parent")
        if (
            page is None
            or type(element_number) is not int
            or type(mcid) is not int
            or type(parent) is not int
        ):
            failures.append({"reason": "invalid-image-structure-evidence"})
            continue
        expected_parent_map[parent].append(element_number)
        page_value = _page_dictionary(model, page)
        if page_value.get("/StructParents") != parent:
            failures.append({"reason": "image-struct-parents", "page": page.page_number})
        element = model.objects.get(element_number)
        value = element.value if element is not None else None
        if not _element_matches(value, root_ref, page.obj_num, mcid, record.get("alt")):
            failures.append({"reason": "image-structure-element", "object": element_number})
            continue
        key = (page.page_number, mcid)
        if key in evidence:
            failures.append({"reason": "duplicate-image-mcid", "page": key[0], "mcid": key[1]})
            continue
        evidence[key] = {
            "alt": record["alt"],
            "mcid": mcid,
            "struct_parent": parent,
            "structure_object": element_number,
            "page_object": page.obj_num,
        }

    normalized_parent_map = dict(sorted(expected_parent_map.items()))
    if parent_map != normalized_parent_map:
        failures.append({"reason": "image-parent-tree"})
    next_key = max(normalized_parent_map) + 1
    if root.get("/ParentTreeNextKey") != next_key:
        failures.append({"reason": "image-parent-tree-next-key"})
    tagged_pages = set(normalized_parent_map)
    for index, page in enumerate(pages):
        if index not in tagged_pages and _page_dictionary(model, page).get("/StructParents") is not None:
            failures.append({"reason": "unexpected-image-struct-parents", "page": page.page_number})
    return failures, evidence


def _element_matches(
    value: Any,
    root: IndirectReference,
    page_object: int,
    mcid: int,
    alt: Any,
) -> bool:
    parent = value.get("/P") if isinstance(value, PdfDict) else None
    page = value.get("/Pg") if isinstance(value, PdfDict) else None
    return (
        isinstance(value, PdfDict)
        and value.get("/Type") == "/StructElem"
        and value.get("/S") == "/Figure"
        and isinstance(parent, IndirectReference)
        and parent == root
        and isinstance(page, IndirectReference)
        and page.obj_num == page_object
        and page.gen_num == 0
        and value.get("/K") == mcid
        and value.get("/Alt") == alt
    )


def _parent_number_tree(value: Any) -> dict[int, list[int]] | None:
    if not isinstance(value, PdfDict):
        return None
    numbers = value.get("/Nums")
    if not isinstance(numbers, list) or len(numbers) % 2:
        return None
    result: dict[int, list[int]] = {}
    for index in range(0, len(numbers), 2):
        key = numbers[index]
        references = _reference_numbers(numbers[index + 1])
        if type(key) is not int or key < 0 or references is None or key in result:
            return None
        result[key] = references
    return dict(sorted(result.items()))


def _reference_numbers(value: Any) -> list[int] | None:
    if not isinstance(value, list) or not all(
        isinstance(item, IndirectReference) and item.gen_num == 0 for item in value
    ):
        return None
    return [item.obj_num for item in value]


def _page_dictionary(model: PdfObjectModel, page: PageInfo) -> PdfDict:
    value = model.objects[page.obj_num].value
    return value if isinstance(value, PdfDict) else PdfDict()


def _positive_int(value: Any, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"Tagged image {field} must be a positive integer")
    return value


def _non_negative_int(value: Any, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Tagged image {field} must be a non-negative integer")
    return value
