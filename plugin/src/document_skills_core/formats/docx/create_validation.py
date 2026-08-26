"""Created-document semantic and layout validation."""

from hashlib import sha256
from pathlib import Path
from typing import Any
from xml.etree.ElementTree import Element

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode

from .constants import qn
from .equations import project_equations
from .mapping import document_stories, iter_paragraphs, map_paragraph, paragraph_style
from .package import OpcPackage
from .projection import project_images, project_sections, project_tables
from .references import expected_reference_projection, project_references
from .semantic_nodes import ALL_NODE_TYPES, semantic_node_for

def _assert_created(
    path: Path,
    report: dict[str, Any],
    expected_images: list[dict[str, Any]],
    expected_styles: dict[str, Any],
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
            block.get("style", f"Heading{block['level']}")
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
    expected_semantic_nodes = [
        (block["node_id"], block["node_type"])
        for block in report["blocks"]
        if block.get("node_id") is not None
    ]
    if _semantic_node_layout(body.root) != expected_semantic_nodes:
        failures.append("semantic-node-identities")
    references = project_references(body)
    if references != expected_reference_projection(report["blocks"]):
        failures.append("references")
    expected_equations = [
        {
            "node_id": block["node_id"],
            "node_type": "equation",
            "linear": block["linear"],
            "editable_omml": True,
        }
        for block in report["blocks"]
        if block["type"] == "equation"
    ]
    equations = project_equations(body)
    if equations != expected_equations:
        failures.append("equations")
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
        *(
            ["docProps/custom.xml", "word/settings.xml"]
            if report.get("document_spec_version") is not None
            else []
        ),
        *(f"word/{kind}1.xml" for kind in expected_references),
        *(
            f"word/media/image{position}.{image['extension']}"
            for position, image in enumerate(expected_images, start=1)
        ),
    }
    if set(package.parts) != expected_parts:
        failures.append("package-parts")
    if report.get("document_spec_version") is not None:
        settings = package.xml("word/settings.xml")
        compatibility = settings.find(
            f"./{qn('w', 'compat')}/{qn('w', 'compatSetting')}"
        )
        if compatibility is None or compatibility.attrib != {
            qn("w", "name"): "compatibilityMode",
            qn("w", "uri"): "http://schemas.microsoft.com/office/word",
            qn("w", "val"): "15",
        }:
            failures.append("word-compatibility-mode")
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
    if (
        style_ids != set(expected_styles["style_ids"])
        or _part_digest(package, "word/styles.xml") != expected_styles["sha256"]
    ):
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
        "semantic_nodes": len(expected_semantic_nodes),
        "references": len(references["bindings"]),
        "equations": len(equations),
    }


def _part_digest(package: OpcPackage, name: str | None) -> str | None:
    payload = package.parts.get(name or "")
    return sha256(payload).hexdigest() if payload is not None else None


_BLOCK_LAYOUT = {
    "heading": "text",
    "paragraph": "text",
    "reference": "text",
    "equation": "text",
    "table": "table",
    "image": "image",
}


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


def _semantic_node_layout(root: Element) -> list[tuple[str, str]]:
    body = root.find(qn("w", "body"))
    layout = []
    for child in body if body is not None else []:
        semantic_node = semantic_node_for(child, allowed_types=ALL_NODE_TYPES)
        if semantic_node is not None:
            layout.append((semantic_node.node_id, semantic_node.node_type))
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
