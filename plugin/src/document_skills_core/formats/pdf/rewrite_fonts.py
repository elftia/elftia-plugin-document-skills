"""Unicode rewrite overlays with new shaped Type0 font resources."""

from dataclasses import dataclass, field
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .font_assets import load_font_assets
from .font_embedding import EmbeddedFontSet
from .font_shaping import TextShaper
from .mutation_writer import write_pdf_mutation
from .object_model import IndirectReference, PdfDict, PdfObjectModel
from .object_serialization import serialize_pdf_value
from .page_tree import PageInfo, walk_pages
from .rewrite_layout import bbox_within, page_bounds
from .rewrite_operator_targeting import candidate_actual_text_runs, OperatorLocator
from .rewrite_overlay_layout import (
    bbox_intersects as _bbox_intersects,
    emit_rewrite_lines as _emit_rewrite_lines,
)
from .rewrite_ownership import require_page_exclusive_content


@dataclass
class MutationFontWriter:
    """Adapt deferred embedded-font construction to mutation additions."""

    next_object: int
    additions: dict[int, bytes] = field(default_factory=dict)

    def reserve_object(self) -> int:
        obj_num = self.next_object
        self.next_object += 1
        self.additions[obj_num] = b""
        return obj_num

    def replace_object(self, obj_num: int, content: bytes) -> None:
        if self.additions.get(obj_num) != b"":
            raise ValueError(f"PDF object {obj_num} is not an empty reservation")
        self.additions[obj_num] = _raw_object(obj_num, content)

    def add_object(self, content: bytes) -> int:
        obj_num = self.next_object
        self.next_object += 1
        self.additions[obj_num] = _raw_object(obj_num, content)
        return obj_num

    def add_stream_object(self, dictionary: bytes, stream_data: bytes) -> int:
        return self.add_object(
            dictionary + b"\nstream\n" + stream_data + b"\nendstream"
        )


def apply_unicode_rewrites(
    model: PdfObjectModel,
    pages: list[PageInfo],
    blocks: list[dict[str, Any]],
    rewrites: list[dict[str, Any]],
    locators: list[OperatorLocator],
    font_specs: list[dict[str, str]],
) -> tuple[bytes, set[int], set[int], list[dict[str, Any]]]:
    """Blank exact selected operands and append shaped replacement overlays."""
    writer = MutationFontWriter(max(model.objects) + 1)
    assets = load_font_assets(font_specs, [rewrite["text"] for rewrite in rewrites])
    fonts = EmbeddedFontSet(
        writer,
        assets,
        resource_prefix="DSUR",
        resource_start=1,
    )
    shaper = TextShaper(assets)
    mutations: dict[int, bytes] = {}
    targeted_pages: set[int] = set()
    evidence: list[dict[str, Any]] = []
    locator_by_block = {locator.block_index: locator for locator in locators}
    targets = [locator_by_block[rewrite["block_index"]] for rewrite in rewrites]
    require_page_exclusive_content(model, targets)
    stream_rewrites: dict[int, list[tuple[OperatorLocator, bytes]]] = {}

    for rewrite in rewrites:
        block_index = rewrite["block_index"]
        block = blocks[block_index]
        style = rewrite.get("style")
        if style is None:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Unicode rewrite requires an explicit embedded-font style.",
                status="enhancement_required",
                details={"field": f"rewrites.{block_index}.style"},
            )
        page = pages[block["page"] - 1]
        lines = shaper.wrap_and_shape(
            rewrite["text"],
            style,
            float(block["bbox"][2]) - float(block["bbox"][0]),
        )
        operators, resources, line_boxes = _emit_rewrite_lines(
            lines,
            block["bbox"],
            style,
            fonts,
        )
        if any(
            not bbox_within(tuple(line_box), page_bounds(page))
            for line_box in line_boxes
        ):
            raise DocumentSkillsError(
                ErrorCode.REQUEST_INVALID,
                "Rewritten text exceeds the target page bounds.",
                status="invalid_request",
                details={"block_index": block_index, "page": page.page_number},
            )
        addition = ("\nq\n" + "\n".join(operators) + "\nQ\n").encode(
            "latin-1",
            errors="strict",
        )
        locator = locator_by_block[block_index]
        if locator.page_number != page.page_number:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Unicode rewrite locator does not belong to the selected page.",
                details={"block_index": block_index},
            )
        stream_rewrites.setdefault(locator.content_object, []).append(
            (locator, addition)
        )
        targeted_pages.add(page.page_number)
        evidence.append({
            "page": page.page_number,
            "block_index": block_index,
            "original_text": block["text"],
            "rewritten_text": rewrite["text"],
            "font": f"/{resources[0]}" if resources else None,
            "size": style["font_size"],
            "bbox": block["bbox"],
            "direction": lines[0].direction,
            "line_count": len(lines),
            "line_bboxes": line_boxes,
            "content_object": locator.content_object,
            "content_operator_index": locator.content_operator_index,
            "operator": locator.operator,
            "glyph_degradation_count": 0,
        })

    for object_number, replacements in stream_rewrites.items():
        mutations[object_number] = _rewrite_located_stream(
            model,
            object_number,
            replacements,
        )

    fonts.finalize(writer)
    resource_entries = {
        f"/{font.resource_name}": IndirectReference(font.root_object, 0)
        for font in fonts.fonts
    }
    for page_number in sorted(targeted_pages):
        page = pages[page_number - 1]
        resource_object = _clone_page_resources(
            model,
            page,
            writer,
            resource_entries,
        )
        page_object = model.objects[page.obj_num]
        assert isinstance(page_object.value, PdfDict)
        page_value = PdfDict(dict(page_object.value.entries))
        page_value.entries["/Resources"] = IndirectReference(resource_object, 0)
        mutations[page.obj_num] = _raw_object(
            page.obj_num,
            serialize_pdf_value(page_value),
            generation=page_object.gen_num,
        )

    if any(not payload for payload in writer.additions.values()):
        raise RuntimeError("embedded font object reservation was not finalized")
    output = write_pdf_mutation(model, mutations, writer.additions, set())
    return output, set(mutations), set(writer.additions), evidence


def verify_unicode_rewrite_layout(
    model: PdfObjectModel,
    blocks: list[dict[str, Any]],
    rewrites: list[dict[str, Any]],
) -> None:
    """Reopen overlay operators and prove visible text remains in requested bounds."""
    pages = walk_pages(model)
    page_runs = {
        page.page_number: candidate_actual_text_runs(model, page)
        for page in pages
    }
    failures: list[int] = []
    for rewrite in rewrites:
        block_index = rewrite["block_index"]
        selector = blocks[block_index]
        page = pages[selector["page"] - 1]
        selected_bbox = tuple(float(value) for value in selector["bbox"])
        runs = page_runs[page.page_number]
        candidates = [] if runs is None else [
            item
            for item in runs
            if _bbox_intersects(item.bbox, selected_bbox)
        ]
        candidate_text = "".join(item.text for item in candidates)
        if (
            not candidates
            or "".join(candidate_text.split())
            != "".join(rewrite["text"].split())
            or any(
                not bbox_within(item.bbox, selected_bbox)
                or not bbox_within(item.bbox, page_bounds(page))
                for item in candidates
            )
        ):
            failures.append(block_index)
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Unicode rewrite candidate exceeds its requested visible bounds.",
            details={"block_indexes": sorted(set(failures))},
        )


def _rewrite_located_stream(
    model: PdfObjectModel,
    object_number: int,
    replacements: list[tuple[OperatorLocator, bytes]],
) -> bytes:
    obj = model.objects[object_number]
    if not obj.is_stream or not isinstance(obj.value, tuple):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "Rewrite target is not a stream.")
    dictionary, decoded = obj.value
    if not isinstance(dictionary, PdfDict):
        raise DocumentSkillsError(ErrorCode.ARCHIVE_UNSAFE, "Rewrite stream dictionary is invalid.")
    filters = dictionary.get("/Filter")
    supported = (
        filters is None
        or filters == "/FlateDecode"
        or filters == ["/FlateDecode"]
    )
    if not supported or dictionary.get("/DecodeParms") is not None:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Unicode rewrite supports only plain or single FlateDecode content streams.",
            status="enhancement_required",
            details={"content_object": object_number},
        )
    rewritten = decoded
    additions: list[bytes] = []
    for locator, addition in sorted(
        replacements,
        key=lambda item: item[0].operand_start,
        reverse=True,
    ):
        if locator.operator not in {"Tj", "TJ"}:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "Unicode rewrite supports exact Tj and TJ operands only.",
                status="enhancement_required",
                details={"operator": locator.operator},
            )
        if rewritten[locator.operand_start:locator.operand_end] != locator.original_operand:
            raise DocumentSkillsError(
                ErrorCode.VALIDATION_FAILED,
                "Unicode rewrite locator no longer matches the source operand.",
                details={"block_index": locator.block_index},
            )
        empty = b"[]" if locator.operator == "TJ" else (
            b"<>" if locator.operand_kind == "hex" else b"()"
        )
        rewritten = (
            rewritten[:locator.operand_start]
            + empty
            + rewritten[locator.operand_end:]
        )
        additions.append(addition)
    rewritten += b"".join(reversed(additions))
    updated = PdfDict(dict(dictionary.entries))
    updated.entries.pop("/Filter", None)
    updated.entries.pop("/DecodeParms", None)
    updated.entries["/Length"] = len(rewritten)
    return _raw_object(
        object_number,
        serialize_pdf_value(updated)
        + b"\nstream\n"
        + rewritten
        + b"\nendstream",
        generation=obj.gen_num,
    )


def _clone_page_resources(
    model: PdfObjectModel,
    page: PageInfo,
    writer: MutationFontWriter,
    font_entries: dict[str, IndirectReference],
) -> int:
    resources = PdfDict(dict(page.resources.entries)) if page.resources else PdfDict({})
    font_dictionary = resources.get("/Font")
    if isinstance(font_dictionary, IndirectReference):
        font_dictionary = model.get_object(font_dictionary).value
    if font_dictionary is None:
        font_dictionary = PdfDict({})
    if not isinstance(font_dictionary, PdfDict):
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Rewrite requires an editable page font resource dictionary.",
            status="enhancement_required",
        )
    updated_fonts = PdfDict(dict(font_dictionary.entries))
    collisions = sorted(set(updated_fonts.entries).intersection(font_entries))
    if collisions:
        raise DocumentSkillsError(
            ErrorCode.ENHANCEMENT_REQUIRED,
            "Rewrite embedded-font resource names collide with the source page.",
            status="enhancement_required",
            details={"resources": collisions},
        )
    updated_fonts.entries.update(font_entries)
    resources.entries["/Font"] = updated_fonts
    return writer.add_object(serialize_pdf_value(resources))


def _raw_object(obj_num: int, content: bytes, *, generation: int = 0) -> bytes:
    return (
        f"{obj_num} {generation} obj\n".encode("ascii")
        + content
        + b"\nendobj"
    )
