"""Mutation and reopened-candidate gates for exact PDF text rewrites."""

import re
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .mutation_writer import write_pdf_mutation
from .object_model import PdfDict, PdfObject, PdfObjectModel
from .page_tree import PageInfo, walk_pages
from .rewrite_font_encoding import decode_text_for_font, encode_text_for_font
from .rewrite_layout import bbox_within, page_bounds, text_bbox_for_font
from .rewrite_operator_walker import OperatorLocator, page_operator_records
from .rewrite_ownership import require_page_exclusive_content


def replacement_fits_layout(
    model: PdfObjectModel,
    page: PageInfo,
    locator: OperatorLocator,
    text: str,
) -> bool:
    """Return whether an in-place replacement remains in requested bounds."""
    encoded = encode_text_for_font(model, page, locator.font_name, text)
    if encoded is None:
        return False
    bbox = text_bbox_for_font(
        model,
        page,
        locator.font_name,
        encoded,
        locator.font_size,
        locator.text_matrix,
    )
    return (
        bbox is not None
        and bbox_within(bbox, locator.selector_bbox)
        and bbox_within(bbox, page_bounds(page))
    )


def apply_targeted_rewrites(
    model: PdfObjectModel,
    locators: list[OperatorLocator],
    rewrite_map: dict[int, str],
) -> tuple[bytes, set[int]]:
    """Replace only operands named by resolved locators."""
    by_index = {locator.block_index: locator for locator in locators}
    try:
        targets = [(by_index[index], text) for index, text in rewrite_map.items()]
    except KeyError as error:
        _validation(
            "Rewrite block index has no resolved selector.",
            block_index=error.args[0],
        )
    identities = {
        (item.content_object, item.content_operator_index) for item, _text in targets
    }
    if len(identities) != len(targets):
        _validation("Multiple rewrite blocks resolve to the same text operator.")
    require_page_exclusive_content(
        model,
        (locator for locator, _text in targets),
    )
    pages = walk_pages(model)
    grouped: dict[int, list[tuple[OperatorLocator, bytes]]] = {}
    for locator, text in targets:
        if locator.operator not in {"Tj", "TJ"}:
            _enhancement(
                "Core rewrite supports exact Tj and TJ operand replacement only.",
                operator=locator.operator,
                block_index=locator.block_index,
            )
        encoded = encode_text_for_font(
            model,
            pages[locator.page_number - 1],
            locator.font_name,
            text,
        )
        if encoded is None:
            _enhancement(
                "The target font mapping cannot safely encode the replacement.",
                block_index=locator.block_index,
                font=locator.font_name,
            )
        if not replacement_fits_layout(
            model,
            pages[locator.page_number - 1],
            locator,
            text,
        ):
            _enhancement(
                "The replacement text does not fit the selected block and page bounds.",
                block_index=locator.block_index,
                bbox=list(locator.selector_bbox),
            )
        grouped.setdefault(locator.content_object, []).append((locator, encoded))
    mutations = {
        object_number: _targeted_object_payload(
            model,
            object_number,
            replacements,
        )
        for object_number, replacements in grouped.items()
    }
    return write_pdf_mutation(model, mutations, {}, set()), set(mutations)


def verify_rewrite_candidate(
    input_model: PdfObjectModel,
    output_model: PdfObjectModel,
    locators: list[OperatorLocator],
    rewrite_map: dict[int, str],
    changed_objects: set[int],
    added_objects: set[int],
) -> dict[str, Any]:
    """Prove target semantics and preservation from reopened candidate bytes."""
    input_pages = walk_pages(input_model)
    output_pages = walk_pages(output_model)
    page_count_match = len(input_pages) == len(output_pages)
    pairs = tuple(zip(input_pages, output_pages))
    page_box_preserved = page_count_match and all(
        _page_geometry(source) == _page_geometry(candidate)
        for source, candidate in pairs
    )
    resources_preserved = page_count_match and all(
        source.resources == candidate.resources for source, candidate in pairs
    )
    by_index = {locator.block_index: locator for locator in locators}
    targets = [(by_index[index], text) for index, text in rewrite_map.items()]
    targeted_verified = page_count_match
    target_layout_verified = page_count_match
    target_pages = {locator.page_number for locator, _text in targets}
    for page_number in target_pages if page_count_match else set():
        records, _blocks = page_operator_records(
            output_model,
            output_pages[page_number - 1],
        )
        candidate_by_identity = {
            (item.content_object, item.content_operator_index): item for item in records
        }
        for locator, expected in targets:
            if locator.page_number != page_number:
                continue
            candidate = candidate_by_identity.get(
                (locator.content_object, locator.content_operator_index)
            )
            decoded = (
                None
                if candidate is None
                else decode_text_for_font(
                    output_model,
                    output_pages[page_number - 1],
                    candidate.font_name,
                    candidate.source_bytes,
                )
            )
            if (
                candidate is None
                or candidate.operator != locator.operator
                or candidate.unsupported_text_state
                or decoded != expected
            ):
                targeted_verified = False
                target_layout_verified = False
                continue
            candidate_bbox = text_bbox_for_font(
                output_model,
                output_pages[page_number - 1],
                candidate.font_name,
                candidate.source_bytes,
                candidate.font_size,
                candidate.text_matrix,
            )
            if (
                candidate_bbox is None
                or not bbox_within(candidate_bbox, locator.selector_bbox)
                or not bbox_within(
                    candidate_bbox,
                    page_bounds(output_pages[page_number - 1]),
                )
            ):
                target_layout_verified = False
    grouped = _encoded_targets(input_model, input_pages, targets)
    if sum(len(items) for items in grouped.values()) != len(targets):
        targeted_verified = False
    operators_preserved = changed_objects == set(grouped) and all(
        number in output_model.objects
        and output_model.objects[number].payload_bytes
        == _targeted_object_payload(input_model, number, replacements)
        for number, replacements in grouped.items()
    )
    input_hashes = input_model.object_hashes()
    output_hashes = output_model.object_hashes()
    removed = set(input_hashes) - set(output_hashes)
    unexpected_added = set(output_hashes) - set(input_hashes) - added_objects
    unexpected_changed = {
        number
        for number in set(input_hashes) & set(output_hashes)
        if input_hashes[number] != output_hashes[number]
        and number not in changed_objects
    }
    objects_preserved = not removed and not unexpected_added and not unexpected_changed
    verified = all(
        (
            page_count_match,
            page_box_preserved,
            resources_preserved,
            targeted_verified,
            target_layout_verified,
            operators_preserved,
            objects_preserved,
        )
    )
    if not verified:
        _validation(
            "Rewritten PDF failed candidate-derived semantic or preservation checks.",
            page_count_match=page_count_match,
            page_box_preserved=page_box_preserved,
            resources_preserved=resources_preserved,
            targeted_blocks_verified=targeted_verified,
            targeted_layout_verified=target_layout_verified,
            non_targeted_operators_preserved=operators_preserved,
            unexpected_changed_objects=sorted(unexpected_changed),
            unexpected_added_objects=sorted(unexpected_added),
            removed_objects=sorted(removed),
        )
    return {
        "page_count_match": page_count_match,
        "page_box_preserved": page_box_preserved,
        "non_targeted_objects_preserved": objects_preserved,
        "targeted_pages": sorted(target_pages),
        "verified": True,
    }


def _encoded_targets(
    model: PdfObjectModel,
    pages: list[PageInfo],
    targets: list[tuple[OperatorLocator, str]],
) -> dict[int, list[tuple[OperatorLocator, bytes]]]:
    grouped: dict[int, list[tuple[OperatorLocator, bytes]]] = {}
    for locator, text in targets:
        encoded = encode_text_for_font(
            model,
            pages[locator.page_number - 1],
            locator.font_name,
            text,
        )
        if encoded is not None:
            grouped.setdefault(locator.content_object, []).append((locator, encoded))
    return grouped


def _targeted_object_payload(
    model: PdfObjectModel,
    object_number: int,
    replacements: list[tuple[OperatorLocator, bytes]],
) -> bytes:
    obj, dictionary, stream = _editable_stream(model, object_number)
    if dictionary.get("/Filter") is not None:
        _enhancement(
            "Exact rewrite of a filtered content stream is not supported.",
            content_object=object_number,
        )
    rewritten = stream
    replacements.sort(key=lambda item: item[0].operand_start, reverse=True)
    for locator, encoded in replacements:
        if rewritten[locator.operand_start : locator.operand_end] != (
            locator.original_operand
        ):
            _validation(
                "Rewrite operator locator no longer matches the source operand.",
                block_index=locator.block_index,
                content_object=object_number,
            )
        replacement = _encoded_operand(locator, encoded)
        rewritten = (
            rewritten[: locator.operand_start]
            + replacement
            + rewritten[locator.operand_end :]
        )
    return _replace_stream_payload(obj, dictionary, stream, rewritten)


def _editable_stream(
    model: PdfObjectModel,
    object_number: int,
) -> tuple[PdfObject, PdfDict, bytes]:
    obj = model.objects[object_number]
    if not obj.is_stream or not isinstance(obj.value, tuple):
        _validation(
            "Rewrite target is not a content stream.",
            content_object=object_number,
        )
    dictionary, stream = obj.value
    if not isinstance(dictionary, PdfDict):
        _validation(
            "Rewrite stream dictionary is malformed.",
            content_object=object_number,
        )
    return obj, dictionary, stream


def _replace_stream_payload(
    obj: PdfObject,
    dictionary: PdfDict,
    original: bytes,
    rewritten: bytes,
) -> bytes:
    length = dictionary.get("/Length")
    marker = re.search(rb"stream\r?\n", obj.payload_bytes)
    if marker is None or not isinstance(length, int) or length != len(original):
        _enhancement("Rewrite stream requires a direct, exact /Length entry.")
    start = marker.end()
    end = start + length
    if obj.payload_bytes[start:end] != original:
        _validation("Decoded rewrite stream does not match its source payload.")
    new_length = f"/Length {len(rewritten)}".encode("ascii")
    prefix, count = re.subn(
        rb"/Length\s+\d+",
        new_length,
        obj.payload_bytes[:start],
        count=1,
    )
    if count != 1:
        _enhancement("Rewrite stream /Length entry cannot be updated safely.")
    return prefix + rewritten + obj.payload_bytes[end:]


def _encoded_operand(locator: OperatorLocator, raw: bytes) -> bytes:
    if locator.operator == "TJ":
        return b"[<" + raw.hex().upper().encode("ascii") + b">]"
    if locator.operand_kind == "hex":
        return b"<" + raw.hex().upper().encode("ascii") + b">"
    escapes = {
        0x08: b"\\b",
        0x09: b"\\t",
        0x0A: b"\\n",
        0x0C: b"\\f",
        0x0D: b"\\r",
        0x28: b"\\(",
        0x29: b"\\)",
        0x5C: b"\\\\",
    }
    encoded = bytearray(b"(")
    for value in raw:
        if value in escapes:
            encoded.extend(escapes[value])
        elif 0x20 <= value <= 0x7E:
            encoded.append(value)
        else:
            encoded.extend(f"\\{value:03o}".encode("ascii"))
    return bytes(encoded + b")")


def _page_geometry(page: PageInfo) -> tuple[Any, ...]:
    return page.media_box, page.crop_box, page.rotation


def _validation(message: str, **details: Any) -> None:
    raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, message, details=details)


def _enhancement(message: str, **details: Any) -> None:
    raise DocumentSkillsError(
        ErrorCode.ENHANCEMENT_REQUIRED,
        message,
        status="enhancement_required",
        details={"capability": "pdf.rewrite-exact-operator", **details},
    )
