"""DOCX public-boundary tests split by operation family."""

from tests.support.docx_public import *  # noqa: F401,F403
from tests.support.docx_public import (
    _GIF,
    _PNG,
    _PNG_16,
    _public,
    _read_document,
    _report,
    _request,
    _table_values,
)

def test_public_typed_edit_updates_sections_and_isolates_header_footer_stories(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    document = _read_document(
        project_root,
        tmp_path,
        public_created,
        "read-section-source.json",
    )
    first, second = document["sections"]
    assert len(first["selector_sha256"]) == 64
    references = {
        (item["kind"], item["reference_type"]): item
        for item in second["references"]
    }
    original_header = references[("header", "default")]
    assert len(original_header["story_sha256"]) == 64
    output = tmp_path / "section-edited.docx"
    request = _request(
        tmp_path,
        "typed-section-edit.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "section_update",
                        "target": {
                            "story": "body",
                            "section_index": 0,
                            "expected_section_sha256": first["selector_sha256"],
                        },
                        "updates": {
                            "orientation": "landscape",
                            "page_size": {
                                "width_twips": 15840,
                                "height_twips": 12240,
                            },
                            "margins": {
                                "top_twips": 720,
                                "right_twips": 900,
                                "bottom_twips": 720,
                                "left_twips": 900,
                                "header_twips": 360,
                                "footer_twips": 360,
                                "gutter_twips": 0,
                            },
                            "break_type": "continuous",
                        },
                    },
                    {
                        "type": "header_footer_update",
                        "target": {
                            "story": "body",
                            "section_index": 1,
                            "expected_section_sha256": second["selector_sha256"],
                        },
                        "kind": "header",
                        "variant": "default",
                        "expected_story_sha256": original_header["story_sha256"],
                        "link_to_previous": False,
                        "text": "Section two header",
                    },
                    {
                        "type": "header_footer_update",
                        "target": {
                            "story": "body",
                            "section_index": 1,
                            "expected_section_sha256": second["selector_sha256"],
                        },
                        "kind": "header",
                        "variant": "first",
                        "expected_story_sha256": None,
                        "link_to_previous": False,
                        "text": "First page header",
                    },
                    {
                        "type": "header_footer_update",
                        "target": {
                            "story": "body",
                            "section_index": 1,
                            "expected_section_sha256": second["selector_sha256"],
                        },
                        "kind": "footer",
                        "variant": "even",
                        "expected_story_sha256": None,
                        "link_to_previous": False,
                        "text": "Even page footer",
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    assert result["diagnostics"]["operation_result"]["edit"] == {
        "applied": 4,
        "primitive_counts": {
            "header_footer_update": 3,
            "section_update": 1,
        },
        "selector_policy": "immutable-input-body-paragraph-and-section-sha256",
    }
    preservation = result["diagnostics"]["operation_result"]["preservation"]
    assert set(preservation["changed_parts"]) == {
        "[Content_Types].xml",
        "word/_rels/document.xml.rels",
        "word/document.xml",
    }
    assert "word/settings.xml" in preservation["added_parts"]
    assert len(
        [
            part
            for part in preservation["added_parts"]
            if part.startswith(("word/header-", "word/footer-"))
        ]
    ) == 3
    edited = _read_document(
        project_root,
        tmp_path,
        output,
        "read-section-edited.json",
    )
    assert edited["sections"][0]["orientation"] == "landscape"
    assert edited["sections"][0]["type"] == "continuous"
    assert edited["sections"][0]["page_size"] == {"h": "12240", "w": "15840"}
    assert edited["sections"][0]["margins"] == {
        "bottom": "720",
        "footer": "360",
        "gutter": "0",
        "header": "360",
        "left": "900",
        "right": "900",
        "top": "720",
    }
    second_references = {
        (item["kind"], item["reference_type"]): item
        for item in edited["sections"][1]["references"]
    }
    assert {
        ("header", "default"),
        ("header", "first"),
        ("footer", "default"),
        ("footer", "even"),
    }.issubset(second_references)
    story_text = {
        story["part"]: "\n".join(
            paragraph["text"] for paragraph in story["paragraphs"]
        )
        for story in edited["stories"]
    }
    assert story_text[second_references[("header", "default")]["target_part"]] == (
        "Section two header"
    )
    assert story_text[second_references[("header", "first")]["target_part"]] == (
        "First page header"
    )
    assert story_text[second_references[("footer", "even")]["target_part"]] == (
        "Even page footer"
    )

    output_sha256 = sha256_file(output)
    linked_output = tmp_path / "section-linked.docx"
    unlink_request = _request(
        tmp_path,
        "typed-header-link.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(output),
            "output": str(linked_output),
            "arguments": {
                "edits": [
                    {
                        "type": "header_footer_update",
                        "target": {
                            "story": "body",
                            "section_index": 1,
                            "expected_section_sha256": edited["sections"][1][
                                "selector_sha256"
                            ],
                        },
                        "kind": "header",
                        "variant": "default",
                        "expected_story_sha256": second_references[
                            ("header", "default")
                        ]["story_sha256"],
                        "link_to_previous": True,
                    }
                ]
            },
        },
    )
    linked = _public(project_root, "run", "--request", str(unlink_request))
    assert linked["status"] == "success", linked
    linked_document = _read_document(
        project_root,
        tmp_path,
        linked_output,
        "read-section-linked.json",
    )
    assert ("header", "default") not in {
        (item["kind"], item["reference_type"])
        for item in linked_document["sections"][1]["references"]
    }
    assert sha256_file(output) == output_sha256
    assert sha256_file(public_created) == source_sha256


def test_public_typed_section_edit_preserves_destination_on_stale_hash(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    output = tmp_path / "existing-section-edit.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "typed-section-edit-mismatch.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "section_update",
                        "target": {
                            "story": "body",
                            "section_index": 0,
                            "expected_section_sha256": "0" * 64,
                        },
                        "updates": {"orientation": "landscape"},
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(request),
        check=False,
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["errors"][0]["details"]["reason"] == "expected-section-sha256"
    assert output.read_bytes() == original_destination
    assert sha256_file(public_created) == source_sha256
