"""Visual page projection for DOCX rendering, not semantic PDF editing.

Subset render evidence omits accessibility tags and initial view navigation.
General PDF editing retains its catalog reconciliation rejection policy.
Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path

from ...core.contracts.errors import DocumentSkillsError, ErrorCode
from ..pdf.actions import classify_actions, has_dangerous_actions, has_executable_embedded_files
from ..pdf.edit import edit_pdf
from ..pdf.mutation_writer import write_pdf_mutation
from ..pdf.object_model import IndirectReference, PdfDict, parse_pdf
from ..pdf.object_serialization import serialize_pdf_value
from ..pdf.page_tree import walk_pages


def split_render_pages(source: Path, output: Path, start: int, end: int) -> None:
    """Create visual page evidence after screening the complete source graph."""
    model = parse_pdf(source)
    if has_dangerous_actions(classify_actions(model)) or has_executable_embedded_files(model):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE,
                                  "Visual page projection rejects active PDF content.")
    catalog_object = model.get_object(model.catalog_ref)
    catalog = catalog_object.value
    if not isinstance(catalog, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "PDF Catalog is not a dictionary.")
    pages = walk_pages(model)
    if not 1 <= start <= end <= len(pages):
        raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "Visual page range exceeds the source.")
    if "/OpenAction" in catalog.entries:
        _require_internal_destination(model, catalog.get("/OpenAction"), {p.obj_num for p in pages})
    removed = {"/OpenAction", "/StructTreeRoot", "/MarkInfo"}
    if "/StructTreeRoot" in catalog.entries:
        # XMP can assert PDF/UA conformance; an untagged projection must not
        # carry that claim. Document Info, language and color profiles remain.
        removed.add("/Metadata")
    mutations = {}
    for obj in (catalog_object, *(model.objects[page.obj_num] for page in pages)):
        omitted = removed if obj is catalog_object else {"/StructParents"}
        entries = {key: value for key, value in obj.value.entries.items() if key not in omitted}
        if entries != obj.value.entries:
            mutations[obj.obj_num] = (
                f"{obj.obj_num} {obj.gen_num} obj\n".encode("ascii")
                + serialize_pdf_value(PdfDict(entries)) + b"\nendobj"
            )
    projected = source
    if mutations:
        projected = output.with_name(f".{output.stem}.visual-source.pdf")
        projected.write_bytes(write_pdf_mutation(model, mutations, {}, set()))
    # Other unsupported Catalog graphs still fail in the existing splitter.
    edit_pdf(projected, output, {"primitives": [{"type": "split", "page_ranges": [[start,end]]}]})


def _require_internal_destination(model, value, page_objects):
    if isinstance(value, IndirectReference):
        value = model.get_object(value).value
    if isinstance(value, PdfDict) and value.get("/S") == "/GoTo":
        if set(value.entries) <= {"/Type", "/S", "/D"}:
            value = value.get("/D")
            if isinstance(value, IndirectReference):
                value = model.get_object(value).value
    if (isinstance(value, list) and len(value) >= 2
            and isinstance(value[0], IndirectReference) and value[0].obj_num in page_objects
            and isinstance(value[1], str)
            and len(value) == {"/XYZ":5, "/Fit":2, "/FitH":3, "/FitV":3,
                               "/FitR":6, "/FitB":2, "/FitBH":3, "/FitBV":3}.get(value[1])
            and all(item is None or type(item) in {int,float} for item in value[2:])):
        return
    raise DocumentSkillsError(ErrorCode.ENHANCEMENT_REQUIRED,
                              "Visual projection cannot reconcile this initial PDF action.",
                              status="enhancement_required")
