"""PDF reopen hooks, operation assertions, preservation, and rewrite gates.

Module provenance: original Elftia-authored clean-room implementation.
"""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.contracts.models import gate_record
from document_skills_core.core.validation import validate_artifact

from .actions import (
    classify_actions,
    has_dangerous_actions,
    has_executable_embedded_files,
)
from .byte_preflight import preflight_pdf
from .create_validation import assert_created as assert_created_candidate
from .metadata_xmp import load_linked_xmp, read_xmp_metadata
from .object_model import parse_pdf
from .page_tree import walk_pages
from .projection import project_info_dictionary


def validate_created(
    path: Path,
    document: dict[str, Any],
    creation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validation gates for pdf.create — asserts requested structures."""
    assertions = [(
        "create-semantics",
        lambda candidate: _assert_created(candidate, document, creation),
    )]
    return _required_report(path, assertions=assertions)


def validate_mutation(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: dict[str, Any],
    assertion: Callable[[Path], dict[str, Any]] | None = None,
    visual_check: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validation gates for pdf.edit — asserts preservation + semantics."""
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("object-preservation", lambda candidate: _assert_preservation(manifest, candidate))
    ]
    if assertion is not None:
        assertions.append(("mutation-semantics", assertion))
    metadata_expectation = manifest.get("metadata_expectation")
    if isinstance(metadata_expectation, dict):
        assertions.append((
            "metadata.info-xmp-sync",
            lambda candidate: _assert_metadata_sync(candidate, metadata_expectation),
        ))
    return _required_report(
        path,
        source=source,
        source_sha256=source_sha256,
        assertions=assertions,
        visual_check=visual_check,
    )


def validate_rewrite(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: dict[str, Any],
    layout_evidence: dict[str, Any],
    visual_check: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validation gates for pdf.rewrite.apply — asserts preservation + layout."""
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("object-preservation", lambda candidate: _assert_preservation(manifest, candidate)),
        ("operation.rewrite-fidelity", lambda _candidate: _assert_rewrite_fidelity(layout_evidence)),
    ]
    return _required_report(
        path,
        source=source,
        source_sha256=source_sha256,
        assertions=assertions,
        visual_check=visual_check,
    )


def _assert_created(
    path: Path,
    document: dict[str, Any],
    creation: dict[str, Any] | None,
) -> dict[str, Any]:
    evidence = assert_created_candidate(path, document, creation)
    evidence["metadata"] = _assert_metadata_sync(path, document["metadata"])
    return evidence


def _assert_preservation(
    manifest: dict[str, Any],
    candidate: Path | None = None,
) -> dict[str, Any]:
    """Assert the preservation manifest is intact for untargeted objects."""
    removed = manifest.get("removed_objects", [])
    added = manifest.get("added_objects", [])
    input_hashes = manifest.get("input_hashes", {})
    output_hashes = (
        parse_pdf(candidate).object_hashes()
        if candidate is not None
        else manifest.get("output_hashes", {})
    )
    changed = set(manifest.get("changed_objects", []))

    # A normalized manifest knows the exact final payload for every mapped
    # object, including explicitly reconciled fields. Never let changed_objects
    # authorize a deviation from that final expectation.
    mismatched: set[int] = set()
    expected_output_hashes = manifest.get("expected_output_hashes", {})
    if isinstance(expected_output_hashes, dict):
        expected_numbers = {int(number) for number in expected_output_hashes}
        actual_numbers = {int(number) for number in output_hashes}
        if (
            manifest.get("identity_space") != "renumbered"
            and expected_numbers != actual_numbers
        ):
            mismatched.update(expected_numbers ^ actual_numbers)
        for num_str, expected_hash in expected_output_hashes.items():
            num = int(num_str) if isinstance(num_str, str) else num_str
            actual_hash = output_hashes.get(num_str) or output_hashes.get(num)
            if actual_hash != expected_hash:
                mismatched.add(num)

    input_numbers = {int(number) for number in input_hashes}
    output_numbers = {int(number) for number in output_hashes}
    if manifest.get("identity_space") != "renumbered":
        if input_numbers - output_numbers != set(removed):
            mismatched.update((input_numbers - output_numbers) ^ set(removed))
        if output_numbers - input_numbers != set(added):
            mismatched.update((output_numbers - input_numbers) ^ set(added))

    # Check that all objects outside the predeclared changed set retain their
    # source-normalized hash.
    for num_str, in_hash in input_hashes.items():
        num = int(num_str) if isinstance(num_str, str) else num_str
        out_hash = output_hashes.get(num_str) or output_hashes.get(num)
        if out_hash is not None and num not in changed and in_hash != out_hash:
            # Check it's not in the removed set
            if num not in removed:
                mismatched.add(num)

    if mismatched:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A PDF mutation changed an untargeted object.",
            details={"mismatched_objects": sorted(mismatched)},
        )
    return {
        "changed_objects": manifest.get("changed_objects", []),
        "added_objects": added,
        "removed_objects": removed,
        "preserved_objects": manifest.get("preserved_objects", []),
    }


def _assert_metadata_sync(
    path: Path,
    expected: dict[str, str],
) -> dict[str, Any]:
    """Require supported Info and Catalog-linked XMP values to agree."""
    model = parse_pdf(path)
    info = project_info_dictionary(model)
    linked_xmp = load_linked_xmp(model)
    xmp = read_xmp_metadata(linked_xmp.xml) if linked_xmp is not None else {}
    mismatches = {
        field: {
            "expected": value,
            "info": info.get(field),
            "xmp": xmp.get(field),
        }
        for field, value in expected.items()
        if info.get(field) != value or xmp.get(field) != value
    }
    if linked_xmp is None or mismatches:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "PDF Info and Catalog-linked XMP metadata are not synchronized.",
            details={
                "xmp_linked": linked_xmp is not None,
                "mismatches": mismatches,
            },
        )
    return {
        "xmp_linked": True,
        "fields": sorted(expected),
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
    if preflight.encrypted:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "A staged PDF must not remain encrypted after a normal operation.",
        )
    model = parse_pdf(path)
    if model.trailer.encrypt is not None:
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "A staged PDF must not remain encrypted after a normal operation.",
        )
    actions = classify_actions(model)
    if has_dangerous_actions(actions) or has_executable_embedded_files(model):
        raise DocumentSkillsError(
            ErrorCode.ARCHIVE_UNSAFE,
            "A staged PDF contains active, external, or executable content.",
        )
    pages = walk_pages(model)
    return {
        "version": f"PDF-{model.version_major}.{model.version_minor}",
        "object_count": len(model.objects),
        "pages": len(pages),
        "encrypted": False,
        "has_eof": preflight.has_eof,
    }


def _required_report(
    path: Path,
    *,
    source: Path | None = None,
    source_sha256: str | None = None,
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] | None = None,
    visual_check: Callable[[], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run the standard required validation report for a staged PDF."""
    report = validate_artifact(
        path,
        expected_format="pdf",
        source_path=source,
        source_sha256=source_sha256,
        reopen=reopen_pdf,
        assertions=assertions,
        visual_available=visual_check is not None,
        schema_available=False,
    )
    if visual_check is not None:
        report["gates"] = [
            gate for gate in report["gates"] if gate["id"] != "visual.render"
        ]
        if report["status"] == "pass":
            report["gates"].append(_run_visual_check(visual_check))
        else:
            report["gates"].append(gate_record(
                "visual.mutation-render-diff",
                "not_run",
                required=False,
                evidence={"reason": "A prior required candidate gate failed."},
            ))
        report["status"] = "fail" if any(
            gate["required"] and gate["outcome"] != "pass"
            for gate in report["gates"]
        ) else "pass"
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


def _run_visual_check(
    visual_check: Callable[[], dict[str, Any]],
) -> dict[str, Any]:
    try:
        gate = visual_check()
    except DocumentSkillsError as error:
        return gate_record(
            "visual.mutation-render-diff",
            "fail",
            required=True,
            validator="poppler",
            evidence={
                "reason": error.code.value,
                "message": str(error)[:512],
            },
        )
    except Exception as error:
        return gate_record(
            "visual.mutation-render-diff",
            "fail",
            required=True,
            validator="poppler",
            evidence={
                "reason": type(error).__name__,
                "message": str(error)[:512],
            },
        )
    if gate.get("id") != "visual.mutation-render-diff":
        return gate_record(
            "visual.mutation-render-diff",
            "fail",
            required=True,
            validator="poppler",
            evidence={"reason": "malformed_visual_gate"},
        )
    return gate
