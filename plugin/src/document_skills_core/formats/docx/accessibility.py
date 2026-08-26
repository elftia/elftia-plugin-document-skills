"""Bounded inert accessibility inspection for Word documents."""

from pathlib import Path
from typing import Any

from document_skills_core.core.io.paths import (
    assert_source_preserved,
    file_record,
)

from .constants import qn
from .contracts import ParsedDocxRequest
from .mapping import document_stories, paragraph_style
from .package import OpcPackage
from .projection import project_images
from .results import read_validation, success_result


def inspect_accessibility_operation(
    request: ParsedDocxRequest,
) -> dict[str, Any]:
    assert request.input_path is not None
    source = file_record(request.input_path, "input")
    operation_result, warnings = inspect_accessibility(
        request.input_path,
        request.arguments,
    )
    assert_source_preserved(source.path, source.sha256)
    return success_result(
        request,
        artifacts=[source.as_dict()],
        operation_result=operation_result,
        warnings=warnings,
        validation=read_validation(
            "operation.accessibility-inspection",
            operation_result,
        ),
    )


def inspect_accessibility(
    path: Path,
    arguments: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    package = OpcPackage.open(path)
    stories = document_stories(package, include_headers_footers=True)
    issues: list[dict[str, Any]] = []
    checks = []

    language_issues = 0 if _has_document_language(package) else 1
    if language_issues:
        issues.append(
            _issue(
                "DOCUMENT_LANGUAGE_MISSING",
                "Document language metadata is missing from core properties and Word styles.",
                {"part": "docProps/core.xml"},
            )
        )
    checks.append(_check("document_language", 1, language_issues))

    heading_count, heading_issues = _inspect_headings(stories[0].root, issues)
    checks.append(_check("heading_hierarchy", heading_count, heading_issues))

    image_count = 0
    image_issues = 0
    for story in stories:
        for image in project_images(package, story):
            image_count += 1
            alt_text = image.get("alt_text")
            if type(alt_text) is str and alt_text.strip():
                continue
            image_issues += 1
            issues.append(
                _issue(
                    "IMAGE_ALT_TEXT_MISSING",
                    "Embedded image is missing non-empty alternative text.",
                    {
                        "part": story.part,
                        "relationship_id": image.get("relationship_id"),
                    },
                )
            )
    checks.append(_check("image_alt_text", image_count, image_issues))

    table_count = 0
    table_issues = 0
    for story in stories:
        for table_index, table in enumerate(story.root.iter(qn("w", "tbl"))):
            table_count += 1
            first_row = table.find(f"./{qn('w', 'tr')}")
            header = (
                first_row.find(f"./{qn('w', 'trPr')}/{qn('w', 'tblHeader')}")
                if first_row is not None
                else None
            )
            if _on_off_property_enabled(header):
                continue
            table_issues += 1
            issues.append(
                _issue(
                    "TABLE_HEADER_MISSING",
                    "Table first row is not marked as a repeating header row.",
                    {"part": story.part, "table_index": table_index},
                )
            )
    checks.append(_check("table_headers", table_count, table_issues))

    issues.sort(key=_issue_sort_key)
    maximum = arguments["max_issues"]
    returned = issues[:maximum]
    truncated = len(returned) < len(issues)
    result = {
        "accessibility": {
            "status": "pass" if not issues else "review_required",
            "issue_count": len(issues),
            "returned_issues": len(returned),
            "truncated": truncated,
            "checks": checks,
            "issues": returned,
        }
    }
    warnings = (
        [
            {
                "code": "DS_ACCESSIBILITY_TRUNCATED",
                "message": "Accessibility findings reached the caller-selected bound.",
                "details": {"issue_count": len(issues), "returned_issues": len(returned)},
            }
        ]
        if truncated
        else []
    )
    return result, warnings


def _has_document_language(package: OpcPackage) -> bool:
    core = package.parts.get("docProps/core.xml")
    if core is not None:
        root = package.xml("docProps/core.xml")
        language = root.find(qn("dc", "language"))
        if language is not None and (language.text or "").strip():
            return True
    if "word/styles.xml" not in package.parts:
        return False
    styles = package.xml("word/styles.xml")
    default_language = styles.find(
        f"./{qn('w', 'docDefaults')}/{qn('w', 'rPrDefault')}/"
        f"{qn('w', 'rPr')}/{qn('w', 'lang')}"
    )
    return default_language is not None and bool(
        (default_language.attrib.get(qn("w", "val")) or "").strip()
    )


def _inspect_headings(root: Any, issues: list[dict[str, Any]]) -> tuple[int, int]:
    body = root.find(qn("w", "body"))
    paragraphs = [] if body is None else body.findall(qn("w", "p"))
    previous_level: int | None = None
    heading_count = 0
    issue_count = 0
    for paragraph_index, paragraph in enumerate(paragraphs):
        level = _heading_level(paragraph_style(paragraph))
        if level is None:
            continue
        heading_count += 1
        if (previous_level is None and level > 1) or (
            previous_level is not None and level > previous_level + 1
        ):
            issue_count += 1
            issues.append(
                _issue(
                    "HEADING_LEVEL_SKIPPED",
                    "Heading hierarchy skips an intermediate level.",
                    {
                        "part": "word/document.xml",
                        "paragraph_index": paragraph_index,
                        "heading_level": level,
                        "previous_heading_level": previous_level,
                    },
                )
            )
        previous_level = level
    return heading_count, issue_count


def _heading_level(style: str | None) -> int | None:
    if not style:
        return None
    folded = style.casefold().replace(" ", "")
    if folded.startswith("heading") and folded[7:].isdigit():
        return int(folded[7:])
    return None


def _on_off_property_enabled(element: Any | None) -> bool:
    if element is None:
        return False
    value = element.attrib.get(qn("w", "val"))
    if value is None:
        return True
    return value.strip().casefold() in {"1", "on", "true", "yes"}


def _issue(code: str, message: str, location: dict[str, Any]) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "warning",
        "message": message,
        "location": location,
    }


def _check(identifier: str, items_checked: int, issues: int) -> dict[str, Any]:
    return {"id": identifier, "items_checked": items_checked, "issues": issues}


def _issue_sort_key(issue: dict[str, Any]) -> tuple[str, str, str]:
    location = issue["location"]
    return (
        issue["code"],
        str(location.get("part", "")),
        str(location.get("paragraph_index", location.get("table_index", ""))),
    )
