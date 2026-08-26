"""Request builders for the result-bound optional DOCX CI profile."""

from pathlib import Path
from typing import Any

from document_skills_core.core.io.paths import sha256_file

OPERATION_PROVIDERS = {
    "docx.comments.add": "dotnet-openxml",
    "docx.comments.read": "dotnet-openxml",
    "docx.comments.resolve": "dotnet-openxml",
    "docx.compare.visual": "libreoffice",
    "docx.convert.legacy": "libreoffice",
    "docx.convert.pdf": "libreoffice",
    "docx.layout.repair": "libreoffice",
    "docx.render": "libreoffice",
    "docx.revisions.apply": "dotnet-openxml",
    "docx.revisions.read": "dotnet-openxml",
    "docx.validate.schema": "dotnet-openxml",
}
OPTIONAL_PROVIDERS = frozenset({"dotnet-openxml", "libreoffice"})


def source_create_request(output: Path) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "docx.create",
        "output": str(output),
        "arguments": {
            "report": {
                "metadata": {"title": "DOCX Optional Provider CI"},
                "blocks": [
                    {
                        "type": "heading",
                        "text": "Optional Provider CI",
                        "level": 1,
                    },
                    {
                        "type": "paragraph",
                        "text": "One page of deterministic provider evidence.",
                    },
                ],
            }
        },
    }


def repair_create_request(output: Path, image: Path) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "docx.create",
        "output": str(output),
        "arguments": {
            "document_spec": {
                "version": "1.0",
                "style_profile": {
                    "id": "professional-generic",
                    "version": "1.0",
                },
                "resources": {"wide": {"type": "image", "path": str(image)}},
                "nodes": [
                    {"id": "document_title", "type": "title", "text": "Repair"},
                    {
                        "id": "figure_wide",
                        "type": "figure",
                        "resource": "wide",
                        "alt_text": "Oversized figure",
                        "width_inches": 10,
                    },
                ],
            }
        },
    }


def libreoffice_requests(
    source: Path,
    repair_source: Path,
    legacy_source: Path,
    evidence_root: Path,
) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": "1.0",
            "operation": "docx.convert.pdf",
            "input": str(source),
            "output": str(evidence_root / "converted.pdf"),
            "options": {"fidelity": "enhanced"},
            "arguments": {"max_output_bytes": 8 * 1024 * 1024},
        },
        {
            "schema_version": "1.0",
            "operation": "docx.render",
            "input": str(source),
            "output": str(evidence_root / "rendered.pdf"),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "format": "pdf",
                "page_range": {"start": 1, "end": 1},
                "include_page_pngs": True,
                "dpi": 96,
                "layout_profile": "professional-v1",
                "max_pages": 1,
                "max_page_bytes": 2 * 1024 * 1024,
                "max_png_total_bytes": 1_000_000,
                "max_total_bytes": 8 * 1024 * 1024,
            },
        },
        {
            "schema_version": "1.0",
            "operation": "docx.compare.visual",
            "input": str(source),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "reference": str(source),
                "expected_reference_sha256": sha256_file(source),
                "render_profile": "libreoffice-96dpi-v1",
                "page_pairs": [{"actual": 1, "reference": 1}],
                "max_pages": 1,
                "max_total_bytes": 8 * 1024 * 1024,
                "max_png_total_bytes": 8 * 1024 * 1024,
            },
        },
        {
            "schema_version": "1.0",
            "operation": "docx.layout.repair",
            "input": str(repair_source),
            "output": str(evidence_root / "repaired.docx"),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "max_rounds": 2,
                "finding_codes": ["DOCX_LAYOUT_OBJECT_EXCEEDS_TEXT_WIDTH"],
                "max_pages": 5,
                "max_total_bytes": 8 * 1024 * 1024,
                "max_png_total_bytes": 8 * 1024 * 1024,
            },
        },
        {
            "schema_version": "1.0",
            "operation": "docx.convert.legacy",
            "input": str(legacy_source),
            "output": str(evidence_root / "legacy-converted.docx"),
            "options": {"fidelity": "enhanced"},
            "arguments": {
                "format": "docx",
                "max_output_bytes": 8 * 1024 * 1024,
            },
        },
    ]


def revision_read_request(project_root: Path) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "docx.revisions.read",
        "input": str(project_root / "tests/fixtures/docx-revisions-nested.docx"),
        "options": {"fidelity": "enhanced"},
        "arguments": {
            "max_revisions": 100,
            "filters": _revision_filters(),
            "scope": _revision_scope(),
        },
    }


def revision_apply_request(
    project_root: Path,
    evidence_root: Path,
    revision_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "docx.revisions.apply",
        "input": str(project_root / "tests/fixtures/docx-revisions-nested.docx"),
        "output": str(evidence_root / "revision-accepted.docx"),
        "options": {"fidelity": "enhanced"},
        "arguments": {
            "action": "accept",
            "revision_ids": [revision_id],
            "filters": _revision_filters(),
            "scope": _revision_scope(),
        },
    }


def comments_read_request(project_root: Path) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "docx.comments.read",
        "input": str(project_root / "tests/fixtures/docx-revision-comments.docx"),
        "options": {"fidelity": "enhanced"},
        "arguments": {"max_comments": 100},
    }


def comments_add_request(
    project_root: Path,
    output: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "docx.comments.add",
        "input": str(project_root / "tests/fixtures/docx-revision-comments.docx"),
        "output": str(output),
        "options": {"fidelity": "enhanced"},
        "arguments": {
            "author": "Optional Provider CI",
            "text": "Result-bound execution evidence",
            "anchor": {
                "story": "body",
                "paragraph_index": 0,
                "expected_text": "Core DOCX",
                "range": "paragraph",
            },
        },
    }


def comments_resolve_request(
    source: Path,
    output: Path,
    comment_id: str,
) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "docx.comments.resolve",
        "input": str(source),
        "output": str(output),
        "options": {"fidelity": "enhanced"},
        "arguments": {"comment_id": comment_id, "resolved": True},
    }


def schema_request(source: Path) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "operation": "docx.validate.schema",
        "input": str(source),
        "options": {"fidelity": "enhanced"},
        "arguments": {"max_errors": 100},
    }


def _revision_filters() -> dict[str, list[str]]:
    return {"authors": ["Carol"], "types": ["insertion"]}


def _revision_scope() -> dict[str, Any]:
    return {
        "story": "body",
        "range": "table",
        "table_index": 1,
        "expected_table_sha256": (
            "05863db08075a5cbbc625625b0e0f5540"
            "b027e3c6ce23067b7cd6586c0518ae4"
        ),
    }
