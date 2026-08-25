"""Safe Catalog copy-through for page-tree reconstruction."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .actions import classify_actions, has_dangerous_actions, has_executable_embedded_files
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .object_serialization import serialize_pdf_value
from .page_tree import walk_pages


_REBUILT_KEYS = frozenset({
    "/Type",
    "/Pages",
    "/PageLabels",
    "/Outlines",
    "/AcroForm",
})
_UNSUPPORTED_KEYS = frozenset({
    "/AA",
    "/AF",
    "/Collection",
    "/Dests",
    "/Names",
    "/OpenAction",
    "/Perms",
    "/Requirements",
    "/StructTreeRoot",
    "/Threads",
})


@dataclass(frozen=True)
class CatalogPreservation:
    """Selected direct entries plus their validated indirect object closure."""

    entries: tuple[tuple[str, Any], ...]
    required_objects: frozenset[int]

    def serialize(self, mapping: dict[int, int]) -> bytes:
        """Serialize selected entries in the output object-number space."""
        return b"".join(
            b" "
            + key.encode("latin-1", errors="strict")
            + b" "
            + serialize_pdf_value(_remap_value(value, mapping))
            for key, value in self.entries
        )


def select_catalog_preservation(
    model: PdfObjectModel,
    transitive_closure: Callable[[PdfObjectModel, list[int]], set[int]],
) -> CatalogPreservation:
    """Select safe, non-page-tree Catalog entries and close their references."""
    catalog = _validated_catalog(model)
    validate_catalog_safety(model, catalog=catalog)
    entries = tuple(
        (key, value)
        for key, value in catalog.entries.items()
        if key not in _REBUILT_KEYS and key not in _UNSUPPORTED_KEYS
    )
    roots = sorted({
        reference.obj_num
        for _key, value in entries
        for reference in _references(value)
    })
    dangling = [number for number in roots if number not in model.objects]
    if dangling:
        _unsafe(
            "A preserved PDF Catalog entry contains a dangling reference.",
            objects=dangling,
        )
    required = transitive_closure(model, roots)
    protected = {
        model.catalog_ref.obj_num,
        *(page.obj_num for page in walk_pages(model)),
    }
    pages = catalog.get("/Pages")
    if isinstance(pages, IndirectReference):
        protected.add(pages.obj_num)
    overlap = sorted(required & protected)
    if overlap:
        _unsafe(
            "A preserved PDF Catalog entry reaches the page tree being rebuilt.",
            objects=overlap,
        )
    return CatalogPreservation(entries, frozenset(required))


def validate_catalog_safety(
    model: PdfObjectModel,
    *,
    catalog: PdfDict | None = None,
) -> None:
    """Reject active or ambiguous Catalog graphs before reconstruction."""
    root = catalog or _validated_catalog(model)
    if has_dangerous_actions(classify_actions(model)) or has_executable_embedded_files(model):
        _unsafe("PDF page-tree reconstruction rejects active or executable content.")
    unsupported_keys = sorted(set(root.entries) & _UNSUPPORTED_KEYS)
    if unsupported_keys:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "PDF page-tree reconstruction cannot safely reconcile these Catalog graphs.",
            status="enhancement_required",
            details={
                "capability": "pdf.page-tree-catalog-reconciliation",
                "catalog_entries": unsupported_keys,
            },
        )


def _validated_catalog(model: PdfObjectModel) -> PdfDict:
    catalog = model.get_object(model.catalog_ref).value
    if not isinstance(catalog, PdfDict):
        _unsafe("PDF Catalog is not a dictionary.")
    return catalog


def _references(value: Any) -> list[IndirectReference]:
    if isinstance(value, IndirectReference):
        return [value]
    if isinstance(value, PdfDict):
        return [
            reference
            for item in value.entries.values()
            for reference in _references(item)
        ]
    if isinstance(value, (list, tuple)):
        return [reference for item in value for reference in _references(item)]
    return []


def _remap_value(value: Any, mapping: dict[int, int]) -> Any:
    if isinstance(value, IndirectReference):
        new_number = mapping.get(value.obj_num)
        if new_number is None:
            _unsafe(
                "A preserved PDF Catalog entry references an object outside its output graph.",
                objects=[value.obj_num],
            )
        return IndirectReference(new_number, 0)
    if isinstance(value, PdfDict):
        return PdfDict({key: _remap_value(item, mapping) for key, item in value.entries.items()})
    if isinstance(value, list):
        return [_remap_value(item, mapping) for item in value]
    if isinstance(value, tuple):
        return tuple(_remap_value(item, mapping) for item in value)
    return value


def _unsafe(message: str, *, objects: list[int] | None = None) -> None:
    details = {"objects": objects} if objects else None
    raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, message, details=details)
