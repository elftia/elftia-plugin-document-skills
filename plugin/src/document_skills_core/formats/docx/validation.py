"""DOCX reopen, semantic, and preservation validation gates."""

from collections import Counter
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.core.validation import validate_artifact

from .constants import MIN_HEADING_STYLES, qn
from .mapping import (
    TextGroup,
    TextRef,
    document_stories,
    iter_paragraphs,
    map_paragraph,
    paragraph_style,
    semantic_tree_digest,
)
from .package import OpcPackage, PreservationManifest
from .projection import project_images, project_sections, project_tables
from .template import (
    TOKEN_PATTERN,
    TemplateExpectation,
    TemplatePlan,
    formatting_signature,
)


def validate_created(
    path: Path,
    report: dict[str, Any],
    images: list[dict[str, Any]],
) -> dict[str, Any]:
    """Validate a staged creation against the report and the creation snapshot.

    ``images`` is the ordered image oracle `create_docx` captured while it read
    the sources. The gate must not re-read those paths: a source replaced
    between creation and validation would fail a correctly built package.
    """
    assertions = [
        ("create-semantics", lambda candidate: _assert_created(candidate, report, images))
    ]
    return _required_report(path, assertions=assertions)


def validate_mutation(
    path: Path,
    *,
    source: Path,
    source_sha256: str,
    manifest: PreservationManifest,
    assertion: Callable[[Path], dict[str, Any]] | None = None,
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


def assert_template_semantics(
    path: Path,
    plan: TemplatePlan,
) -> dict[str, Any]:
    """Verify the backend changed only the Python-planned story semantics."""
    package = OpcPackage.open(path)
    stories = {story.part: story for story in document_stories(package)}
    paragraphs = {
        part: list(iter_paragraphs(story.root))
        for part, story in stories.items()
    }
    expected_counts = Counter(
        item.variable
        for expectation in plan.expectations
        for item in expectation.occurrences
    )
    verified: Counter[str] = Counter()
    anchors = 0
    failures: list[dict[str, Any]] = []
    mutable_nodes: dict[str, set[int]] = {}

    for expectation in plan.expectations:
        part_paragraphs = paragraphs.get(expectation.part)
        if (
            part_paragraphs is None
            or expectation.paragraph_index >= len(part_paragraphs)
        ):
            failures.append(_template_failure(expectation, "missing-paragraph"))
            continue
        groups = map_paragraph(
            part_paragraphs[expectation.paragraph_index]
        ).groups
        if expectation.group_index >= len(groups):
            failures.append(_template_failure(expectation, "missing-text-group"))
            continue
        group = groups[expectation.group_index]
        mutable_nodes.setdefault(expectation.part, set()).update(
            id(reference.node) for reference in group.refs
        )
        if group.text != expectation.expected_text:
            failures.append(_template_failure(expectation, "rendered-text"))
            continue
        actual_node_texts = tuple(reference.node.text or "" for reference in group.refs)
        if actual_node_texts != expectation.expected_node_texts:
            failures.append(_template_failure(expectation, "text-node-plan"))
            continue
        for occurrence in expectation.occurrences:
            if (
                group.text[occurrence.output_start : occurrence.output_end]
                != occurrence.value
            ):
                failures.append(
                    _template_failure(
                        expectation,
                        "rendered-value",
                        variable=occurrence.variable,
                    )
                )
                continue
            anchor = _output_anchor(
                group,
                occurrence.output_start,
                occurrence.output_end,
            )
            if (
                anchor is None
                or formatting_signature(anchor.run)
                != occurrence.formatting_anchor
            ):
                failures.append(
                    _template_failure(
                        expectation,
                        "formatting-anchor",
                        variable=occurrence.variable,
                    )
                )
                continue
            verified[occurrence.variable] += 1
            anchors += 1

    expected_oracles = {oracle.part: oracle for oracle in plan.story_oracles}
    for part, oracle in expected_oracles.items():
        story = stories.get(part)
        actual_digest = (
            semantic_tree_digest(
                story.root,
                ignore_text_space_for=mutable_nodes.get(part, set()),
            )
            if story is not None
            else None
        )
        if actual_digest != oracle.semantic_sha256:
            failures.append(
                {
                    "reason": "story-semantic-oracle",
                    "part": part,
                    "expected_sha256": oracle.semantic_sha256,
                    "actual_sha256": actual_digest,
                }
            )

    expected_literals = Counter(
        match.group(1)
        for expectation in plan.expectations
        for match in TOKEN_PATTERN.finditer(expectation.expected_text)
        if match.group(1) in plan.used
    )
    actual_literals = Counter(
        match.group(1)
        for story in stories.values()
        for paragraph in iter_paragraphs(story.root)
        for group in map_paragraph(paragraph).groups
        for match in TOKEN_PATTERN.finditer(group.text)
        if match.group(1) in plan.used
    )
    if actual_literals != expected_literals:
        failures.append(
            {
                "reason": "unresolved-approved-tokens",
                "variables": sorted((actual_literals - expected_literals).keys()),
            }
        )
    if verified != expected_counts:
        failures.append(
            {
                "reason": "occurrence-counts",
                "expected": dict(sorted(expected_counts.items())),
                "actual": dict(sorted(verified.items())),
            }
        )
    if set(verified) != set(plan.used):
        failures.append(
            {
                "reason": "used-variables",
                "expected": list(plan.used),
                "actual": sorted(verified),
            }
        )
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Template output does not satisfy the immutable semantic plan.",
            details={"mismatches": failures[:32]},
        )
    return {
        "verified_occurrences": sum(verified.values()),
        "counts_by_variable": dict(sorted(verified.items())),
        "used_variables": list(plan.used),
        "unused_variables": list(plan.unused),
        "unresolved_approved_tokens": 0,
        "formatting_anchors": anchors,
        "verified_story_parts": len(expected_oracles),
    }


def _output_anchor(group: TextGroup, start: int, end: int) -> TextRef | None:
    if end > start:
        for reference in group.refs:
            if reference.start <= start < reference.end:
                return reference
    return next(
        (
            reference
            for reference in group.refs
            if reference.start == start
            or reference.start <= start <= reference.end
        ),
        None,
    )


def _template_failure(
    expectation: TemplateExpectation,
    reason: str,
    **details: Any,
) -> dict[str, Any]:
    return {
        "reason": reason,
        "part": expectation.part,
        "paragraph_index": expectation.paragraph_index,
        "group_index": expectation.group_index,
        **details,
    }


def _required_report(
    path: Path,
    *,
    source: Path | None = None,
    source_sha256: str | None = None,
    assertions: list[tuple[str, Callable[[Path], dict[str, Any]]]] | None = None,
) -> dict[str, Any]:
    report = validate_artifact(
        path,
        expected_format="docx",
        source_path=source,
        source_sha256=source_sha256,
        reopen=reopen_docx,
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
            "Staged DOCX failed required validation gates.",
            details={"failed_gates": failed},
        )
    return report


def reopen_docx(path: Path) -> dict[str, Any]:
    package = OpcPackage.open(path)
    return {
        "parts": len(package.parts),
        "relationships": len(package.relationships),
        "sections": len(project_sections(package)),
    }


def _assert_created(
    path: Path,
    report: dict[str, Any],
    expected_images: list[dict[str, Any]],
) -> dict[str, Any]:
    package = OpcPackage.open(path)
    body = document_stories(package, include_headers_footers=False)[0]
    tables, _ = project_tables(body.root, table_limit=1_000, row_limit=10_000)
    images = project_images(package, body)
    sections = project_sections(package)
    stories = document_stories(package)
    story_map = {story.kind: story for story in stories}
    kinds = set(story_map)
    failures = []
    expected_text = [
        (
            block["text"],
            f"Heading{block['level']}"
            if block["type"] == "heading"
            else block["style"],
        )
        for block in report["blocks"]
        if block["type"] in {"heading", "paragraph"}
    ]
    actual_text = [
        (
            "".join(group.text for group in map_paragraph(paragraph).groups),
            paragraph_style(paragraph),
        )
        for paragraph in iter_paragraphs(body.root)
    ]
    if not _ordered_subset(expected_text, actual_text):
        failures.append("block-text-style")
    expected_tables = [
        block for block in report["blocks"] if block["type"] == "table"
    ]
    if len(tables) != len(expected_tables):
        failures.append("table-count")
    elif any(
        actual["style"] != expected["style"]
        or _table_values(actual) != expected["rows"]
        for actual, expected in zip(tables, expected_tables, strict=True)
    ):
        failures.append("table-structure-style")
    requested_images = [
        *(block for block in report["blocks"] if block["type"] == "image"),
        *([report["image"]] if report["image"] is not None else []),
    ]
    if len(expected_images) != len(requested_images):
        failures.append("image-oracle")
    elif len(images) != len(expected_images) or any(
        actual["alt_text"] != expected["alt_text"]
        or actual["content_type"] != expected["content_type"]
        or not actual["target_part"]
        # Payload identity, not just type: two same-format images whose
        # relationship targets were swapped would otherwise pass while the
        # document displays them in the wrong order. Compared against the
        # creation snapshot, never against a re-read of the source path.
        or _part_digest(package, actual["target_part"]) != expected["sha256"]
        for actual, expected in zip(images, expected_images, strict=True)
    ):
        failures.append("image-relationship-type")
    elif len({item["target_part"] for item in images}) != len(images):
        # Distinct media parts: two drawings sharing one part would make the
        # per-image records the caller gets back a lie.
        failures.append("image-target-uniqueness")
    if _body_layout(body.root) != _expected_layout(report):
        # Image blocks render where the caller put them, so the gate has to
        # police placement, not just the image sequence.
        failures.append("block-layout")
    expected_references = {
        kind
        for kind, requested in (
            ("header", report["header"]),
            ("footer", report["footer"]),
        )
        if requested is not None
    }
    if (
        len(sections) != len(report["sections"])
        or [item["orientation"] for item in sections]
        != [item["orientation"] for item in report["sections"]]
        or any(
            {reference["kind"] for reference in item["references"]}
            != expected_references
            for item in sections
        )
    ):
        failures.append("sections")
    # Story kinds come from the document's relationships, so an unreferenced
    # header part is invisible there — and a part name carries no guarantee, so
    # a name-based sweep is evadable too. Creation authors every byte of the
    # package, so assert the exact part set instead: anything the report did not
    # ask for, under any name and any declared type, fails the gate.
    expected_parts = {
        "[Content_Types].xml",
        "_rels/.rels",
        "docProps/app.xml",
        "docProps/core.xml",
        "word/_rels/document.xml.rels",
        "word/document.xml",
        "word/numbering.xml",
        "word/styles.xml",
        *(f"word/{kind}1.xml" for kind in expected_references),
        *(
            f"word/media/image{position}.{image['extension']}"
            for position, image in enumerate(expected_images, start=1)
        ),
    }
    if set(package.parts) != expected_parts:
        failures.append("package-parts")
    if kinds != {"body", *expected_references}:
        failures.append("header-footer")
    elif any(
        _story_text(story_map[kind]) != requested
        for kind, requested in (
            ("header", report["header"]),
            ("footer", report["footer"]),
        )
        if requested is not None
    ):
        failures.append("header-footer-text")
    styles = package.xml("word/styles.xml")
    style_ids = {
        item.attrib.get(qn("w", "styleId"))
        for item in styles.findall(qn("w", "style"))
    }
    # The heading style set is derived from the report now, so assert it
    # exactly rather than as a subset: a package carrying styles the document
    # never asked for is as wrong as one missing the styles it uses.
    levels = [
        block["level"] for block in report["blocks"] if block["type"] == "heading"
    ]
    depth = max(MIN_HEADING_STYLES, *levels) if levels else MIN_HEADING_STYLES
    expected_styles = {
        "Normal",
        "TableGrid",
        *(f"Heading{level}" for level in range(1, depth + 1)),
    }
    if style_ids != expected_styles:
        failures.append("styles")
    if not _metadata_matches(package, report["metadata"]):
        failures.append("metadata")
    if failures:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "Created DOCX does not satisfy the report semantics.",
            details={"missing_or_mismatched": failures},
        )
    return {
        "tables": len(tables),
        "images": len(images),
        "sections": len(sections),
        "stories": sorted(kinds),
        "metadata": True,
        "requested_structure": True,
    }


def _part_digest(package: OpcPackage, name: str | None) -> str | None:
    payload = package.parts.get(name or "")
    return sha256(payload).hexdigest() if payload is not None else None


_BLOCK_LAYOUT = {"heading": "text", "paragraph": "text", "table": "table", "image": "image"}


def _expected_layout(report: dict[str, Any]) -> list[str]:
    """The body child sequence the report describes, up to the section tail."""
    layout = [_BLOCK_LAYOUT[block["type"]] for block in report["blocks"]]
    if report["image"] is not None:
        layout.append("image")
    return layout


def _body_layout(root: Element) -> list[str]:
    """Classify the body's direct children, stopping at the section tail.

    Section boundaries are bare `w:p` elements holding only `w:pPr`, and the
    final `w:sectPr` is a direct child too; both sit after the report content,
    so the walk stops at the first boundary paragraph.
    """
    body = root.find(qn("w", "body"))
    layout: list[str] = []
    for child in body if body is not None else []:
        if child.tag == qn("w", "tbl"):
            layout.append("table")
            continue
        if child.tag != qn("w", "p"):
            break
        if child.find(f"./{qn('w', 'pPr')}/{qn('w', 'sectPr')}") is not None:
            break
        layout.append(
            "image" if child.find(f".//{qn('w', 'drawing')}") is not None else "text"
        )
    return layout


def _ordered_subset(
    expected: list[tuple[str, str | None]],
    actual: list[tuple[str, str | None]],
) -> bool:
    cursor = iter(actual)
    return all(any(candidate == item for candidate in cursor) for item in expected)


def _table_values(table: dict[str, Any]) -> list[list[str]]:
    return [
        [
            "\n".join(paragraph["text"] for paragraph in cell["paragraphs"])
            for cell in row["cells"]
        ]
        for row in table["rows"]
    ]


def _story_text(story: Any) -> str:
    return "\n".join(
        "".join(group.text for group in map_paragraph(paragraph).groups)
        for paragraph in iter_paragraphs(story.root)
    )


def _metadata_matches(package: OpcPackage, expected: dict[str, str]) -> bool:
    root = package.xml("docProps/core.xml")
    actual = {
        "title": root.findtext(qn("dc", "title"), ""),
        "subject": root.findtext(qn("dc", "subject"), ""),
        "creator": root.findtext(qn("dc", "creator"), ""),
        "keywords": root.findtext(qn("cp", "keywords"), ""),
    }
    requested = {
        **expected,
        "creator": expected["creator"] or "Elftia Document Skills",
    }
    return actual == requested


def _assert_preservation(manifest: PreservationManifest) -> dict[str, Any]:
    if manifest.removed:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A DOCX mutation removed package parts.",
            details={"removed_parts": list(manifest.removed)},
        )
    mismatched = [
        name
        for name in manifest.preserved
        if manifest.input_hashes[name] != manifest.output_hashes[name]
    ]
    if mismatched:
        raise DocumentSkillsError(
            ErrorCode.VALIDATION_FAILED,
            "A preserved DOCX part changed.",
            details={"parts": mismatched},
        )
    return {
        "changed_parts": list(manifest.changed),
        "added_parts": list(manifest.added),
        "removed_parts": list(manifest.removed),
        "preserved_parts": len(manifest.preserved),
    }
