"""DOCX validation transaction facade and reopen gates."""

from pathlib import Path
from typing import Any, Callable

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.io.archive import DangerousContentPolicy
from document_skills_core.core.validation import validate_artifact

from .create_validation import _assert_created
from .mapping import document_stories, iter_paragraphs, map_paragraph
from .package import OpcPackage, PreservationManifest
from .preservation_validation import _assert_preservation
from .projection import project_sections
from .template import TemplatePlan
from .template_validation import assert_template_semantics

def validate_created(
    path: Path,
    report: dict[str, Any],
    images: list[dict[str, Any]],
    styles: dict[str, Any],
) -> dict[str, Any]:
    """Validate a staged creation against the report and the creation snapshot.

    ``images`` is the ordered image oracle `create_docx` captured while it read
    the sources. The gate must not re-read those paths: a source replaced
    between creation and validation would fail a correctly built package.
    """
    assertions = [
        (
            "create-semantics",
            lambda candidate: _assert_created(candidate, report, images, styles),
        )
    ]
    return _required_report(path, assertions=assertions)


def validate_mutation(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: PreservationManifest,
    assertion: Callable[[Path], dict[str, Any]] | None = None,
    allow_vba_preservation: bool = False,
) -> dict[str, Any]:
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] = [
        ("part-preservation", lambda _candidate: _assert_preservation(manifest))
    ]
    if assertion is not None:
        assertions.append(("mutation-semantics", assertion))
    return _required_report(
        path,
        source=source,
        source_sha256=source_sha256,
        assertions=assertions,
        allow_vba_preservation=allow_vba_preservation,
    )


def assert_replacement_text(
    path: Path,
    rules: list[dict[str, Any]],
    *,
    case_sensitive: bool,
) -> dict[str, Any]:
    package = OpcPackage.open(path)
    text = "\n".join(
        "".join(group.text for group in map_paragraph(paragraph).groups)
        for story in document_stories(package)
        for paragraph in iter_paragraphs(story.root)
    )
    remaining = []
    for index, rule in enumerate(rules):
        haystack = text if case_sensitive else text.casefold()
        needle = rule["search"] if case_sensitive else rule["search"].casefold()
        if needle in haystack and rule["search"] != rule["replace"]:
            remaining.append({"rule_index": index, "search": rule["search"]})
    if remaining:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Replacement semantic assertion found unresolved requested text.",
            details={"remaining": remaining},
        )
    return {"remaining_search_values": 0}


def _required_report(
    path: Path,
    *,
    source: Path | None = None,
    source_sha256: str | None = None,
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] | None = None,
    allow_vba_preservation: bool = False,
) -> dict[str, Any]:
    report = validate_artifact(
        path,
        expected_format="docx",
        source_path=source,
        source_sha256=source_sha256,
        reopen=lambda candidate: reopen_docx(
            candidate,
            allow_vba_preservation=allow_vba_preservation,
        ),
        assertions=assertions,
        visual_available=False,
        schema_available=False,
        dangerous_policy=(
            DangerousContentPolicy.PRESERVE_DISABLED
            if allow_vba_preservation
            else DangerousContentPolicy.REJECT
        ),
    )
    if report["status"] != "pass":
        failed = [
            gate["id"]
            for gate in report["gates"]
            if gate["required"] and gate["outcome"] != "pass"
        ]
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Staged DOCX failed required validation gates.",
            details={"failed_gates": failed},
            validation=report,
        )
    return report


def reopen_docx(
    path: Path,
    *,
    allow_vba_preservation: bool = False,
) -> dict[str, Any]:
    package = OpcPackage.open(
        path,
        allow_vba_preservation=allow_vba_preservation,
    )
    return {
        "parts": len(package.parts),
        "relationships": len(package.relationships),
        "sections": len(project_sections(package)),
    }
