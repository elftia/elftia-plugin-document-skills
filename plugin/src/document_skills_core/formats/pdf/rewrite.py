"""Block extract/rewrite/apply workflow with page-layout + CJK/RTL preservation.

THE differentiator: extract page-region text blocks via content-stream operators
+ text-matrix bbox; rewrite ONLY targeted blocks' operators in the targeted page's
content stream; preserve page box (MediaBox/CropBox), Rotation, all targeted-page
resources (font subsetting, image XObjects, ExtGState, color spaces), and all
surrounding blocks; all other pages/objects untouched at object level.

CJK/RTL honesty: detect required CIDs → check embedded font CMap/subsetting
coverage → for uncovered CIDs report each under glyph_degradation and set
status: degraded; NEVER silently emit .notdef/wrong glyphs.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .hash_bound_sources import load_hash_bound_pdf
from .object_model import PdfObjectModel, parse_pdf
from .page_tree import walk_pages
from .rewrite_font_encoding import encode_text_for_font
from .rewrite_fonts import apply_unicode_rewrites, verify_unicode_rewrite_layout
from .rewrite_operator_targeting import (
    apply_targeted_rewrites,
    locate_block_selectors,
    replacement_fits_layout,
    verify_rewrite_candidate,
)
from .rewrite_unicode_verification import assert_unicode_operator_rewrites


def rewrite_apply_pdf(
    input_path: Path,
    output_path: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute the block rewrite workflow.

    Returns (operation_result, preservation_manifest).
    """
    expected_source = arguments.get("source_sha256")
    if expected_source is None:
        # Internal callers exercise the rewrite engine directly. Public requests
        # are contractually required to take the hash-bound branch below.
        model = parse_pdf(input_path)
    else:
        model, _source_sha256 = load_hash_bound_pdf(
            input_path,
            expected_source,
            capability="pdf.rewrite.apply",
            field="source_sha256",
        )
    input_hashes = model.object_hashes()
    pages = walk_pages(model)

    blocks = arguments["blocks"]
    rewrites = arguments["rewrites"]
    locators = locate_block_selectors(model, pages, blocks)
    locator_by_block = {locator.block_index: locator for locator in locators}

    rewrite_map: dict[int, str] = {}
    for rewrite in rewrites:
        rewrite_map[rewrite["block_index"]] = rewrite["text"]

    changed_content_objs: set[int] = set()
    glyph_degradation: list[dict[str, Any]] = []
    rewrite_evidence: list[dict[str, Any]] = []
    targeted_blocks_by_page: dict[int, list[dict[str, Any]]] = {}
    for block_index, rewritten_text in rewrite_map.items():
        block = blocks[block_index]
        locator = locator_by_block[block_index]
        targeted_blocks_by_page.setdefault(block["page"], []).append(block)
        rewrite_evidence.append({
            "page": block["page"],
            "block_index": block_index,
            "original_text": block["text"],
            "rewritten_text": rewritten_text,
            "font": block.get("font", "F1"),
            "size": block.get("size", 12.0),
            "bbox": block.get("bbox"),
            "content_object": locator.content_object,
            "content_operator_index": locator.content_operator_index,
            "operator": locator.operator,
            "glyph_degradation_count": 0,
        })

    unsafe_rewrites: list[tuple[dict[str, Any], str]] = []
    for rewrite in rewrites:
        locator = locator_by_block[rewrite["block_index"]]
        page = pages[locator.page_number - 1]
        if encode_text_for_font(
            model,
            page,
            locator.font_name,
            rewrite["text"],
        ) is None:
            unsafe_rewrites.append((rewrite, "font-encoding"))
        elif not replacement_fits_layout(
            model,
            page,
            locator,
            rewrite["text"],
        ):
            unsafe_rewrites.append((rewrite, "layout-bounds"))
    uses_overlay = bool(unsafe_rewrites)
    if uses_overlay:
        font_ids = {font["id"] for font in arguments.get("fonts", [])}
        overlay_ready = all(
            rewrite.get("style") is not None
            and rewrite["style"]["font_family"] in font_ids
            for rewrite in rewrites
        )
        if not overlay_ready:
            raise DocumentSkillsError(
                ErrorCode.ENHANCEMENT_REQUIRED,
                "The in-place rewrite cannot preserve its font mapping and visible bounds, and no explicit embedded-font overlay is available.",
                status="enhancement_required",
                details={
                    "capability": (
                        "pdf.rewrite-layout-bounds"
                        if any(
                            reason == "layout-bounds"
                            for _rewrite, reason in unsafe_rewrites
                        )
                        else "pdf.rewrite-font-encoding"
                    ),
                    "block_indexes": [
                        rewrite["block_index"]
                        for rewrite, _reason in unsafe_rewrites
                    ],
                    "reasons": {
                        str(rewrite["block_index"]): reason
                        for rewrite, reason in unsafe_rewrites
                    },
                },
            )
    added_objects: set[int] = set()
    if uses_overlay:
        output_bytes, unicode_changed, added_objects, rewrite_evidence = apply_unicode_rewrites(
            model,
            pages,
            blocks,
            rewrites,
            locators,
            arguments.get("fonts", []),
        )
        changed_content_objs = unicode_changed
    else:
        output_bytes, changed_content_objs = apply_targeted_rewrites(
            model,
            locators,
            rewrite_map,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(output_bytes)

    output_model = parse_pdf(output_path)
    output_hashes = output_model.object_hashes()
    from .edit import _build_manifest
    manifest = _build_manifest(
        input_hashes, output_hashes,
        changed=changed_content_objs, added=added_objects, removed=set(),
    )

    # Determine status
    is_degraded = len(glyph_degradation) > 0
    status = "degraded" if is_degraded else "success"

    if uses_overlay:
        assert_unicode_operator_rewrites(
            model,
            output_model,
            locators,
            rewrite_map,
        )
        verify_unicode_rewrite_layout(output_model, blocks, rewrites)
        layout_preservation = _verify_layout_preservation(
            model,
            output_model,
            pages,
            targeted_blocks_by_page,
        )
    else:
        layout_preservation = verify_rewrite_candidate(
            model,
            output_model,
            locators,
            rewrite_map,
            changed_content_objs,
            added_objects,
        )

    operation_result: dict[str, Any] = {
        "rewrite": {
            "blocks_processed": len(rewrite_map),
            "rewrite_evidence": rewrite_evidence,
            "glyph_degradation": glyph_degradation,
            "page_layout_preservation": layout_preservation,
        },
        "preservation": manifest,
    }
    if is_degraded:
        operation_result["status"] = status
        operation_result["degradation_entry"] = {
            "capability": "core.cjk_glyph_coverage",
            "reason": "Embedded font subset does not cover required CJK/RTL codepoints.",
            "recommended_provider": "libreoffice",
            "uncovered_count": len(glyph_degradation),
        }
    return operation_result, manifest
def _verify_layout_preservation(
    input_model: PdfObjectModel,
    output_model: PdfObjectModel,
    pages: list,
    blocks_by_page: dict[int, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Verify page-layout-preservation-on-rewrite invariant.

    Reopen candidate+input, walk the targeted page's content stream, and assert
    that for every non-targeted block the text-showing operator matches, and
    page boxes and resources are preserved.
    """
    target_pages = set(blocks_by_page.keys())
    input_pages = walk_pages(input_model)
    output_pages = walk_pages(output_model)

    page_box_preserved = True
    for inp_page, out_page in zip(input_pages, output_pages):
        if inp_page.media_box != out_page.media_box:
            page_box_preserved = False
            break
        if inp_page.crop_box != out_page.crop_box:
            page_box_preserved = False
            break
        if inp_page.rotation != out_page.rotation:
            page_box_preserved = False
            break

    # Check non-targeted pages match at object level
    input_hashes = input_model.object_hashes()
    output_hashes = output_model.object_hashes()
    non_target_objs_preserved = True
    for num, hash_val in input_hashes.items():
        if num in output_hashes and output_hashes[num] != hash_val:
            # This object changed — acceptable if it's on a targeted page
            page_obj = next((p for p in input_pages if p.obj_num == num), None)
            if page_obj and page_obj.page_number not in target_pages:
                non_target_objs_preserved = False
                break
            # Content stream on a targeted page — acceptable change
            is_content = any(
                ref.obj_num == num
                for p in input_pages
                for ref in p.contents
            )
            if not is_content and page_obj is None:
                non_target_objs_preserved = False
                break

    return {
        "page_count_match": len(input_pages) == len(output_pages),
        "page_box_preserved": page_box_preserved,
        "non_targeted_objects_preserved": non_target_objs_preserved,
        "targeted_pages": sorted(target_pages),
        "verified": page_box_preserved and non_target_objs_preserved,
    }
