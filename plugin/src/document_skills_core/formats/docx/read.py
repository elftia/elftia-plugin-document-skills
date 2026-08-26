"""Structured DOCX read operation."""

from pathlib import Path
from typing import Any

from document_skills_core.core.io.core_properties import project_core_properties
from document_skills_core.core.io.paths import file_record

from .content_control_editing import project_content_controls
from .document_manifest import project_document_manifest
from .equations import project_equations
from .mapping import document_stories
from .package import OpcPackage
from .field_editing import project_fields
from .formatting_inspection import project_formatting
from .note_editing import project_notes
from .projection import (
    project_images,
    project_sections,
    project_story,
    project_tables,
)
from .references import project_references


def read_docx(path: Path, arguments: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    max_fields = arguments.get("max_fields", 1_000)
    max_notes = arguments.get("max_notes", 2_000)
    max_content_controls = arguments.get("max_content_controls", 1_000)
    package = OpcPackage.open(path)
    stories = document_stories(
        package,
        include_headers_footers=arguments["include_headers_footers"],
    )
    story_results = []
    truncations = []
    paragraph_remaining = arguments["max_paragraphs"]
    text_remaining = arguments["max_text_chars"]
    table_remaining = arguments["max_tables"]
    table_row_remaining = arguments["max_table_rows"]
    table_text_remaining = arguments["max_text_chars"]
    all_images = []
    fields, fields_truncated = project_fields(stories, max_fields)
    notes, notes_truncated = project_notes(package, max_notes)
    content_controls, controls_truncated = project_content_controls(
        stories,
        max_content_controls,
    )
    manifest = project_document_manifest(package) or {}
    for story in stories:
        paragraphs, truncated = project_story(
            package,
            story,
            paragraph_limit=max(paragraph_remaining, 1),
            text_limit=max(text_remaining, 1),
        )
        paragraph_remaining -= len(paragraphs)
        text_remaining -= sum(len(item["text"]) for item in paragraphs)
        tables, table_truncated = project_tables(
            story.root,
            table_limit=max(table_remaining, 0),
            row_limit=max(table_row_remaining, 0),
            text_limit=max(table_text_remaining, 0),
        )
        table_remaining -= len(tables)
        table_row_remaining -= sum(len(table["rows"]) for table in tables)
        table_text_remaining -= sum(
            len(paragraph["text"])
            for table in tables
            for row in table["rows"]
            for cell in row["cells"]
            for paragraph in cell["paragraphs"]
        )
        images = project_images(package, story)
        all_images.extend(images)
        story_results.append(
            {
                "kind": story.kind,
                "part": story.part,
                "paragraphs": paragraphs,
                "tables": tables,
            }
        )
        if truncated["paragraphs"] or truncated["text"] or table_truncated:
            truncations.append(
                {
                    "part": story.part,
                    "paragraphs": truncated["paragraphs"],
                    "text": truncated["text"],
                    "tables": table_truncated,
                }
            )
        if paragraph_remaining <= 0 or text_remaining <= 0:
            break
    result = {
        "metadata": project_core_properties(package.parts),
        "document": {
            "document_spec_version": manifest.get("document_spec_version"),
            "style_profile": manifest.get("style_profile"),
            "domain_profile": manifest.get("domain_profile"),
            "equations": project_equations(stories[0]),
            "stories": story_results,
            "sections": project_sections(package),
            "images": all_images,
            "fields": fields,
            "notes": notes,
            "content_controls": content_controls,
            "formatting": project_formatting(package, stories),
            "references": project_references(stories[0]),
        },
        "limits": {
            "max_paragraphs": arguments["max_paragraphs"],
            "max_fields": max_fields,
            "max_notes": max_notes,
            "max_content_controls": max_content_controls,
            "max_tables": arguments["max_tables"],
            "max_table_rows": arguments["max_table_rows"],
            "max_text_chars": arguments["max_text_chars"],
        },
        "truncated": (
            bool(truncations)
            or fields_truncated
            or notes_truncated
            or controls_truncated
        ),
        "truncations": truncations,
    }
    warnings = (
        [
            {
                "code": "DS_READ_TRUNCATED",
                "message": "Structured DOCX output reached a caller-selected bound.",
                "details": {"truncations": truncations},
            }
        ]
        if truncations or fields_truncated or notes_truncated or controls_truncated
        else []
    )
    return result, warnings


def input_artifact(path: Path) -> dict[str, Any]:
    return file_record(path, "input").as_dict()
