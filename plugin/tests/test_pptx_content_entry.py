"""Planning-only outline and bounded Markdown reconstruction tests."""

from hashlib import sha256
import json
from pathlib import Path

import pytest

from document_skills_core.formats.pptx.package import OpcPackage
from document_skills_core.formats.pptx.read import read_pptx
from document_skills_core.formats.pptx.service import PptxService
from tests.fixtures.recipes.docx_fixture_support import PNG_1X1


def _markdown_request(source: Path, output: Path, **arguments: object) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pptx.create.from-markdown",
        "input": str(source),
        "output": str(output),
        "arguments": arguments,
    }


def test_outline_is_versioned_planning_json_not_a_fake_deck(
    project_root: Path,
    tmp_path: Path,
) -> None:
    output = tmp_path / "plan.json"
    result = PptxService(project_root).execute("pptx.outline.create", {
        "schema_version": "1.0",
        "operation": "pptx.outline.create",
        "output": str(output),
        "arguments": {
            "title": "Quarterly review",
            "audience": "Leadership",
            "objective": "Choose the next investment",
            "slides": [
                {
                    "title": "Decision",
                    "purpose": "Frame the choice",
                    "bullets": ["Option A", "Option B"],
                    "notes": "Ask for a decision.",
                    "metadata": {"recipe": "comparison", "tags": ["decision"]},
                }
            ],
        },
    })

    assert result["status"] == "success", result
    plan = json.loads(output.read_text(encoding="utf-8"))
    assert plan["kind"] == "pptx-outline"
    assert plan["artifact_type"] == "planning-json"
    assert plan["presentation_generated"] is False
    assert plan["slides"][0]["number"] == 1
    assert not output.read_bytes().startswith(b"PK")
    outcomes = {gate["id"]: gate["outcome"] for gate in result["validation"]["gates"]}
    assert outcomes["operation.pptx-outline-planning"] == "pass"
    assert outcomes["visual.render"] == "not_applicable"


def test_markdown_reconstructs_native_objects_notes_metadata_and_source_evidence(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(PNG_1X1)
    source = tmp_path / "deck.md"
    source.write_text(
        "# Launch plan\n\n"
        "A concise opening paragraph.\n\n"
        "<!-- pptx: {\"recipe\":\"cover\",\"notes\":\"Opening note\",\"tags\":[\"launch\"]} -->\n\n"
        "## Evidence\n\n"
        "- Native list item\n"
        "1. Ordered item\n\n"
        "| Region | Value |\n"
        "| --- | ---: |\n"
        "| North | 7 |\n\n"
        "![Evidence image](pixel.png)\n\n"
        "```python\nprint('native code text')\n```\n\n"
        ":::notes\nExplain the evidence.\n:::\n\n"
        "### Close\n\n"
        "Summary text.\n",
        encoding="utf-8",
        newline="\n",
    )
    before = sha256(source.read_bytes()).hexdigest()
    output = tmp_path / "deck.pptx"

    result = PptxService(project_root).execute(
        "pptx.create.from-markdown",
        _markdown_request(source, output),
    )

    assert result["status"] == "success", result
    assert sha256(source.read_bytes()).hexdigest() == before
    package = OpcPackage.open(output)
    assert len(package.slide_parts()) == 3
    assert len(package.media_parts()) == 1
    assert len(package.notes_slide_parts()) == 2
    projected, _warnings = read_pptx(output, {})
    assert projected["slide_count"] == 3
    reconstruction = result["diagnostics"]["operation_result"]["reconstruction"]
    assert reconstruction["source_sha256"] == before
    assert reconstruction["semantic_reconstruction"] is True
    assert reconstruction["visual_preservation_claimed"] is False
    assert reconstruction["slides"][0]["tags"] == ["launch"]
    assert reconstruction["slides"][1]["native_objects"] == {
        "image": True,
        "table": True,
        "text_blocks": 3,
    }
    creation = result["diagnostics"]["operation_result"]["creation"]
    assert creation["has_image"] is True
    assert creation["has_table"] is True
    assert creation["has_notes"] is True
    assert creation["images"][0]["fallback"] == "native"


@pytest.mark.parametrize(
    "body",
    [
        "# One\n\n![remote](https://example.invalid/image.png)\n",
        "# One\n\n![escape](../escape.png)\n",
        "# One\n\n![first](a.png)\n![second](b.png)\n",
        (
            "# One\n\n| A |\n| --- |\n| 1 |\n\n"
            "| B |\n| --- |\n| 2 |\n"
        ),
        "# One\n\n<!-- pptx: {\"unknown\":true} -->\n",
        "# One\n\n:::notes\nnot closed\n",
    ],
)
def test_markdown_fails_closed_for_unsafe_or_ambiguous_content(
    project_root: Path,
    tmp_path: Path,
    body: str,
) -> None:
    for name in ("a.png", "b.png"):
        (tmp_path / name).write_bytes(PNG_1X1)
    source = tmp_path / "unsafe.md"
    source.write_text(body, encoding="utf-8", newline="\n")
    output = tmp_path / "must-not-exist.pptx"

    result = PptxService(project_root).execute(
        "pptx.create.from-markdown",
        _markdown_request(source, output),
    )

    assert result["status"] == "invalid_request", result
    assert not output.exists()
