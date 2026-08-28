"""PDF PageLabels read projection and flat number-tree mutation.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mutation_writer import write_pdf_mutation
from .object_model import IndirectReference, PdfDict, PdfObjectModel, parse_pdf
from .object_serialization import serialize_pdf_value
from .page_tree import walk_pages

_STYLE_TO_PDF = {
    "decimal": "/D",
    "roman-upper": "/R",
    "roman-lower": "/r",
    "letters-upper": "/A",
    "letters-lower": "/a",
    "none": None,
}


def project_page_labels(model: PdfObjectModel, page_count: int) -> list[str]:
    """Expand a flat PageLabels number tree to one visible label per page."""
    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        return []
    root = catalog.get("/PageLabels")
    if isinstance(root, IndirectReference):
        try:
            root = model.get_object(root).value
        except DocumentSkillsError:
            return []
    if not isinstance(root, PdfDict):
        return []
    nums = root.get("/Nums")
    if not isinstance(nums, list) or len(nums) % 2 != 0:
        return []
    ranges: list[tuple[int, PdfDict]] = []
    for position in range(0, len(nums), 2):
        start_page = nums[position]
        spec = nums[position + 1]
        if isinstance(start_page, int) and isinstance(spec, PdfDict):
            ranges.append((start_page, spec))
    if not ranges:
        return []
    ranges.sort(key=lambda item: item[0])
    labels: list[str] = []
    current_range = 0
    for page_index in range(page_count):
        while current_range + 1 < len(ranges) and ranges[current_range + 1][0] <= page_index:
            current_range += 1
        range_start, spec = ranges[current_range]
        prefix = spec.get("/P", "")
        prefix = prefix if isinstance(prefix, str) else ""
        start = spec.get("/St", 1)
        start = start if isinstance(start, int) and start > 0 else 1
        labels.append(prefix + _format_label(spec.get("/S"), start + page_index - range_start))
    return labels


def selected_page_labels(
    model: PdfObjectModel,
    page_count: int,
    selected_pages: list[int],
) -> list[str] | None:
    """Return visible labels for a page selection, rejecting non-flat trees."""
    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PDF Catalog is not a dictionary.")
    if catalog.get("/PageLabels") is None:
        return None
    _existing_labels(model, catalog)
    labels = project_page_labels(model, page_count)
    if len(labels) != page_count:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "PageLabels does not define a valid label for every page.",
        )
    return [labels[page - 1] for page in selected_pages]


def page_labels_catalog_entry(labels: list[str] | None) -> bytes:
    """Serialize exact visible labels as a direct flat PageLabels number tree."""
    if labels is None:
        return b""
    nums: list[Any] = []
    for page_index, label in enumerate(labels):
        nums.extend([page_index, PdfDict({"/P": label})])
    value = serialize_pdf_value(PdfDict({"/Nums": nums}))
    return b" /PageLabels " + value


def edit_page_labels(
    model: PdfObjectModel,
    primitive: dict[str, Any],
    output: Path,
    input_hashes: dict[int, str],
    *,
    build_manifest: Callable[..., dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Set or clear a flat PageLabels number tree."""
    pages = walk_pages(model)
    outside = [item["page"] for item in primitive["ranges"] if item["page"] > len(pages)]
    if outside:
        raise DocumentSkillsError(
            ErrorCode.REQUEST_INVALID,
            "Page-label range starts outside the document.",
            status="invalid_request",
            details={"pages": outside, "page_count": len(pages)},
        )
    catalog = model.get_object(model.catalog_ref)
    if not isinstance(catalog.value, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PDF Catalog is not a dictionary.")
    existing_ref, existing_value = _existing_labels(model, catalog.value)
    mutations: dict[int, bytes] = {}
    additions: dict[int, bytes] = {}
    removed: set[int] = set()
    catalog_value = PdfDict(dict(catalog.value.entries))
    if primitive["action"] == "set":
        labels_value = _labels_dictionary(primitive["ranges"])
        if existing_ref is not None:
            mutations[existing_ref.obj_num] = _object_payload(
                existing_ref.obj_num,
                existing_ref.gen_num,
                labels_value,
            )
        elif existing_value is not None:
            catalog_value.entries["/PageLabels"] = labels_value
            mutations[catalog.obj_num] = _object_payload(
                catalog.obj_num, catalog.gen_num, catalog_value
            )
        else:
            labels_object = max(model.objects) + 1
            labels_ref = IndirectReference(labels_object, 0)
            additions[labels_object] = _object_payload(labels_object, 0, labels_value)
            catalog_value.entries["/PageLabels"] = labels_ref
            mutations[catalog.obj_num] = _object_payload(
                catalog.obj_num, catalog.gen_num, catalog_value
            )
    elif existing_ref is not None or existing_value is not None:
        catalog_value.entries.pop("/PageLabels", None)
        mutations[catalog.obj_num] = _object_payload(
            catalog.obj_num, catalog.gen_num, catalog_value
        )
        if existing_ref is not None:
            removed.add(existing_ref.obj_num)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(write_pdf_mutation(model, mutations, additions, removed))
    output_model = parse_pdf(output)
    manifest = build_manifest(
        input_hashes,
        output_model.object_hashes(),
        changed=set(mutations),
        added=set(additions),
        removed=removed,
    )
    return {
        "primitive": "page_labels",
        "action": primitive["action"],
        "ranges": primitive["ranges"],
        "labels": project_page_labels(output_model, len(pages)),
        "preservation": manifest,
    }, manifest


def _existing_labels(
    model: PdfObjectModel,
    catalog: PdfDict,
) -> tuple[IndirectReference | None, PdfDict | None]:
    value = catalog.get("/PageLabels")
    reference = value if isinstance(value, IndirectReference) else None
    if reference is not None:
        value = model.get_object(reference).value
    if value is None:
        return None, None
    if not isinstance(value, PdfDict) or value.get("/Kids") is not None:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Core page-label editing supports flat /Nums number trees only.",
            status="enhancement_required",
            details={"capability": "pdf.page-label-nested-number-tree"},
        )
    nums = value.get("/Nums")
    if nums is not None and not isinstance(nums, list):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PageLabels /Nums is malformed.")
    return reference, value


def _labels_dictionary(ranges: list[dict[str, Any]]) -> PdfDict:
    nums: list[Any] = []
    for item in ranges:
        spec_entries: dict[str, Any] = {}
        style = _STYLE_TO_PDF[item["style"]]
        if style is not None:
            spec_entries["/S"] = style
        if item["prefix"]:
            spec_entries["/P"] = item["prefix"]
        if item["start"] != 1:
            spec_entries["/St"] = item["start"]
        nums.extend([item["page"] - 1, PdfDict(spec_entries)])
    return PdfDict({"/Nums": nums})


def _format_label(style: Any, number: int) -> str:
    if style == "/D":
        return str(number)
    if style == "/R":
        return _roman(number)
    if style == "/r":
        return _roman(number).lower()
    if style == "/A":
        return _letters(number)
    if style == "/a":
        return _letters(number).lower()
    return ""


def _roman(number: int) -> str:
    values = (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
        (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
        (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    )
    result = ""
    for value, symbol in values:
        while number >= value:
            result += symbol
            number -= value
    return result


def _letters(number: int) -> str:
    result = ""
    while number > 0:
        number -= 1
        result = chr(ord("A") + number % 26) + result
        number //= 26
    return result


def _object_payload(obj_num: int, gen_num: int, value: PdfDict) -> bytes:
    return (
        f"{obj_num} {gen_num} obj\n".encode("ascii")
        + serialize_pdf_value(value)
        + b"\nendobj"
    )
