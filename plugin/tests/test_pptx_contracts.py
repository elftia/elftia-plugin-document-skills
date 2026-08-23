"""PPTX operation argument contract tests."""

from pathlib import Path

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError
from document_skills_core.formats.pptx.contracts import (
    PPTX_OPERATIONS,
    parse_pptx_request,
)


def test_pptx_operations_preserve_existing_surface_and_add_validators():
    assert PPTX_OPERATIONS == frozenset(
        {
            "pptx.read",
            "pptx.inspect.structure",
            "pptx.validate.schema",
            "pptx.create",
            "pptx.edit",
            "pptx.create.from-html",
        }
    )


def test_parse_schema_validation_is_read_only_and_bounded(tmp_path: Path):
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.validate.schema",
        "input": str(tmp_path / "deck.pptx"),
        "arguments": {},
    })
    assert parsed.arguments == {}
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.validate.schema",
            "input": str(tmp_path / "deck.pptx"),
            "output": str(tmp_path / "report.pptx"),
            "arguments": {},
        })


def test_parse_from_html_minimal_request_defaults(tmp_path: Path):
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.create.from-html",
        "input": str(tmp_path / "deck.html"),
        "output": str(tmp_path / "deck.pptx"),
        "arguments": {},
    })
    assert parsed.arguments == {
        "metadata": {
            "title": "Elftia Presentation",
            "creator": "Elftia Document Skills",
            "subject": "",
        },
        "fallback_policy": "element-rasterize",
    }


def test_parse_from_html_accepts_bounded_metadata_and_fail_policy(tmp_path: Path):
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.create.from-html",
        "input": str(tmp_path / "deck.htm"),
        "output": str(tmp_path / "deck.pptx"),
        "arguments": {
            "metadata": {"title": "Deck", "creator": "Elftia", "subject": "Test"},
            "fallback_policy": "fail",
        },
    })
    assert parsed.arguments["fallback_policy"] == "fail"
    assert parsed.arguments["metadata"]["title"] == "Deck"


@pytest.mark.parametrize(
    ("arguments", "input_name", "output_name"),
    [
        ({"unknown": True}, "deck.html", "deck.pptx"),
        ({"fallback_policy": "slide-rasterize"}, "deck.html", "deck.pptx"),
        ({"metadata": {"unknown": "x"}}, "deck.html", "deck.pptx"),
        ({}, "deck.txt", "deck.pptx"),
        ({}, "deck.html", "deck.docx"),
    ],
)
def test_parse_from_html_rejects_unknown_policy_and_extensions(
    tmp_path: Path,
    arguments: dict[str, object],
    input_name: str,
    output_name: str,
):
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.create.from-html",
            "input": str(tmp_path / input_name),
            "output": str(tmp_path / output_name),
            "arguments": arguments,
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_from_html_rejects_same_path_and_in_place(tmp_path: Path):
    request = {
        "schema_version": "1.0",
        "operation": "pptx.create.from-html",
        "input": str(tmp_path / "deck.html"),
        "output": str(tmp_path / "deck.pptx"),
        "arguments": {},
        "options": {"in_place": True},
    }
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request(request)


def test_parse_read_rejects_unknown_argument():
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.read",
            "input": "test.pptx",
            "arguments": {"unknown": True},
        })
    assert exc.value.code.value == "DS_REQUEST_INVALID"


def test_parse_read_requires_input():
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.read",
            "arguments": {},
        })


def test_parse_read_rejects_output():
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.read",
            "input": "test.pptx",
            "output": "out.pptx",
            "arguments": {},
        })


def test_parse_create_requires_output():
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.create",
            "arguments": {"deck": {"metadata": {}, "slides": []}},
        })


def test_parse_edit_requires_distinct_paths():
    same = str(Path("same.pptx").resolve())
    with pytest.raises(DocumentSkillsError) as exc:
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": same,
            "output": same,
            "arguments": {"edits": [{"slide": 1, "type": "slide_text", "ref": "", "value": "x"}]},
        })
    assert exc.value.code.value == "DS_OUTPUT_EQUALS_INPUT"


def test_parse_edit_requires_edits():
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": "in.pptx",
            "output": "out.pptx",
            "arguments": {"edits": []},
        })


def test_parse_edit_rejects_unknown_edit_type():
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.edit",
            "input": "in.pptx",
            "output": "out.pptx",
            "arguments": {"edits": [{"slide": 1, "type": "invalid_type", "ref": ""}]},
        })


def test_parse_input_must_have_pptx_extension():
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.read",
            "input": "test.docx",
            "arguments": {},
        })


def test_parse_create_rejects_input():
    with pytest.raises(DocumentSkillsError):
        parse_pptx_request({
            "schema_version": "1.0",
            "operation": "pptx.create",
            "input": "in.pptx",
            "output": "out.pptx",
            "arguments": {"deck": {"metadata": {}, "slides": []}},
        })


def test_parse_read_defaults():
    parsed = parse_pptx_request({
        "schema_version": "1.0",
        "operation": "pptx.read",
        "input": "test.pptx",
        "arguments": {},
    })
    assert parsed.arguments["include_notes"] is True
    assert parsed.arguments["include_connectors"] is True
    assert parsed.arguments["max_slides"] == 1_000
