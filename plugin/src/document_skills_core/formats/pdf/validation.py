"""PDF reopen hooks, operation assertions, preservation, and rewrite gates.

Module provenance: original Elftia-authored clean-room implementation.
"""

from collections import Counter
from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.validation import validate_artifact

from .byte_preflight import PdfByteLimits, preflight_pdf
from .content_streams import extract_content_stream
from .mapping import map_text_blocks
from .object_model import parse_pdf
from .page_tree import walk_pages
from .resources import inventory_images


def validate_created(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Validation gates for pdf.create — asserts requested structures."""
    assertions = [("create-semantics", lambda candidate: _assert_created(candidate, document))]
    return _required_report(path, assertions=assertions)


def validate_mutation(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: dict[str, Any],
    assertion: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validation gates for pdf.edit — asserts preservation + semantics."""
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("object-preservation", lambda _candidate: _assert_preservation(manifest))
    ]
    if assertion is not None:
        assertions.append(("mutation-semantics", assertion))
    return _required_report(
        path,
        source=source,
        source_sha256=source_sha256,
        assertions=assertions,
    )


def validate_rewrite(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: dict[str, Any],
    layout_evidence: dict[str, Any],
) -> dict[str, Any]:
    """Validation gates for pdf.rewrite.apply — asserts preservation + layout."""
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("object-preservation", lambda _candidate: _assert_preservation(manifest)),
        ("operation.rewrite-fidelity", lambda _candidate: _assert_rewrite_fidelity(layout_evidence)),
    ]
    return _required_report(
        path,
        source=source,
        source_sha256=source_sha256,
        assertions=assertions,
    )


def _assert_created(path: Path, document: dict[str, Any]) -> dict[str, Any]:
    """Assert the created PDF satisfies the document contract."""
    model = parse_pdf(path)
    pages = walk_pages(model)
    failures: list[str] = []

    expected_count = len(document.get("pages", []))
    if len(pages) != expected_count:
        failures.append("page-count")

    expected_text = _requested_text_counts(document)
    mapped_text = map_text_blocks(model, pages)
    missing_text = _missing_requested_text(document, mapped_text)
    if missing_text:
        failures.append("requested-text")

    expected_structures = _requested_structure_counts(document)
    content = b"\n".join(
        extract_content_stream(model, page.contents, page.page_number)
        for page in pages
    )
    actual_structures = Counter({
        block_type: content.count(f"%DS-BLOCK:{block_type}".encode("ascii"))
        for block_type in expected_structures
    })
    actual_structures["image"] = sum(
        len(inventory_images(model, page.resources))
        for page in pages
    )
    missing_structures = sorted(
        block_type
        for block_type, count in expected_structures.items()
        if actual_structures[block_type] < count
    )
    if missing_structures:
        failures.append("requested-structure")

    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Created PDF does not satisfy the document contract.",
            details={
                "missing_or_mismatched": failures,
                "missing_text": missing_text,
                "missing_structures": missing_structures,
            },
        )
    return {
        "pages": len(pages),
        "requested_structure": True,
        "requested_text_blocks": sum(expected_text.values()),
        "requested_structure_counts": dict(expected_structures),
    }


def _requested_text_counts(document: dict[str, Any]) -> Counter[str]:
    requested: Counter[str] = Counter()
    for page in document.get("pages", []):
        for block in page.get("blocks", []):
            block_type = block.get("type")
            text = block.get("text")
            if block_type in {"heading", "paragraph"} and text:
                requested[text] += 1
            if block_type != "table":
                continue
            table = block.get("table") or {}
            for row in table.get("rows", []):
                for cell in row.get("cells", []):
                    if cell:
                        requested[str(cell)] += 1
    return requested


def _missing_requested_text(
    document: dict[str, Any],
    mapped_text: list[Any],
) -> list[str]:
    """Accept exact text blocks or request text reconstructed after wrapping."""
    page_text: dict[int, str] = {}
    for page_number in range(1, len(document.get("pages", [])) + 1):
        page_text[page_number] = _normalized_text(
            " ".join(block.text for block in mapped_text if block.page == page_number)
        )
    missing: list[str] = []
    for page_number, page in enumerate(document.get("pages", []), start=1):
        requested_items: list[str] = []
        for block in page.get("blocks", []):
            if block.get("type") in {"heading", "paragraph"} and block.get("text"):
                requested_items.append(str(block["text"]))
            if block.get("type") == "table":
                for row in (block.get("table") or {}).get("rows", []):
                    requested_items.extend(str(cell) for cell in row.get("cells", []) if cell)
        for text in requested_items:
            normalized = _normalized_text(text)
            if normalized and normalized in page_text[page_number]:
                page_text[page_number] = page_text[page_number].replace(normalized, "", 1)
                continue
            missing.append(text)
    return sorted(missing)


def _normalized_text(value: str) -> str:
    return " ".join(value.split())


def _requested_structure_counts(document: dict[str, Any]) -> Counter[str]:
    requested: Counter[str] = Counter()
    for page in document.get("pages", []):
        for block in page.get("blocks", []):
            block_type = block.get("type")
            if block_type in {"table", "image", "vector_shape"}:
                requested[block_type] += 1
    return requested


def _assert_preservation(manifest: dict[str, Any]) -> dict[str, Any]:
    """Assert the preservation manifest is intact for untargeted objects."""
    removed = manifest.get("removed_objects", [])
    input_hashes = manifest.get("input_hashes", {})
    output_hashes = manifest.get("output_hashes", {})
    changed = set(manifest.get("changed_objects", []))

    # Check that all objects not in the changed set retain their hash
    mismatched = []
    for num_str, in_hash in input_hashes.items():
        num = int(num_str) if isinstance(num_str, str) else num_str
        out_hash = output_hashes.get(num_str) or output_hashes.get(num)
        if out_hash is not None and num not in changed and in_hash != out_hash:
            # Check it's not in the removed set
            if num not in removed:
                mismatched.append(num)

    if mismatched:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A PDF mutation changed an untargeted object.",
            details={"mismatched_objects": mismatched},
        )
    return {
        "changed_objects": manifest.get("changed_objects", []),
        "added_objects": manifest.get("added_objects", []),
        "removed_objects": removed,
        "preserved_objects": manifest.get("preserved_objects", []),
    }


def _assert_rewrite_fidelity(layout_evidence: dict[str, Any]) -> dict[str, Any]:
    """Assert the page-layout-preservation-on-rewrite invariant."""
    if not layout_evidence.get("verified", False):
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Page-layout-preservation-on-rewrite gate failed.",
            details={
                "page_box_preserved": layout_evidence.get("page_box_preserved"),
                "non_targeted_objects_preserved": layout_evidence.get("non_targeted_objects_preserved"),
            },
        )
    return layout_evidence


def reopen_pdf(path: Path) -> dict[str, Any]:
    """Reopen a PDF and verify its required structures."""
    preflight = preflight_pdf(path)
    model = parse_pdf(path)
    pages = walk_pages(model)
    return {
        "version": f"PDF-{model.version_major}.{model.version_minor}",
        "object_count": len(model.objects),
        "pages": len(pages),
        "encrypted": preflight.encrypted,
        "has_eof": preflight.has_eof,
    }


def _required_report(
    path: Path,
    *,
    source: Path | None = None,
    source_sha256: str | None = None,
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    """Run the standard required validation report for a staged PDF."""
    report = validate_artifact(
        path,
        expected_format="pdf",
        source_path=source,
        source_sha256=source_sha256,
        reopen=reopen_pdf,
        assertions=assertions,
        visual_available=False,
        schema_available=False,
    )
    if report["status"] != "pass":
        failed = [
            gate["id"]
            for gate in report["gates"]
            if gate["required"] and gate["outcome"] != "pass"
        ]
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Staged PDF failed required validation gates.",
            details={"failed_gates": failed},
            validation=report,
        )
    return report
