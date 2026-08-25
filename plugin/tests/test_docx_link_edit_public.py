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

def test_public_typed_edit_inserts_bookmark_and_internal_hyperlink(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    paragraph_target = {
        "story": "body",
        "paragraph_index": 1,
        "expected_text": "Hello {name}",
    }
    output = tmp_path / "linked.docx"
    request = _request(
        tmp_path,
        "typed-link-edit.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "bookmark_insert",
                        "target": paragraph_target,
                        "name": "Greeting",
                        "range": "paragraph",
                    },
                    {
                        "type": "hyperlink_insert",
                        "target": paragraph_target,
                        "bookmark_name": "Greeting",
                        "placement": "append",
                        "text": "Jump to greeting",
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    assert result["diagnostics"]["operation_result"]["edit"] == {
        "applied": 2,
        "primitive_counts": {"bookmark_insert": 1, "hyperlink_insert": 1},
        "selector_policy": "immutable-input-body-paragraph-and-internal-link",
    }
    document = _read_document(
        project_root,
        tmp_path,
        output,
        "read-linked.json",
    )
    body = next(story for story in document["stories"] if story["kind"] == "body")
    paragraph = body["paragraphs"][1]
    assert paragraph["text"] == "Hello {name}Jump to greeting"
    assert paragraph["hyperlinks"] == [
        {
            "relationship_id": None,
            "target": None,
            "target_mode": "Internal",
            "resolved_target": None,
            "type": "internal-bookmark",
            "anchor": "Greeting",
            "text": "Jump to greeting",
        }
    ]
    with zipfile.ZipFile(output) as archive:
        root = fromstring(archive.read("word/document.xml"))
    starts = [
        node
        for node in root.iter(qn("w", "bookmarkStart"))
        if node.attrib.get(qn("w", "name")) == "Greeting"
    ]
    assert len(starts) == 1
    bookmark_id = starts[0].attrib[qn("w", "id")]
    assert any(
        node.attrib.get(qn("w", "id")) == bookmark_id
        for node in root.iter(qn("w", "bookmarkEnd"))
    )

    output_sha256 = sha256_file(output)
    updated_output = tmp_path / "linked-updated.docx"
    update_request = _request(
        tmp_path,
        "typed-link-update.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(output),
            "output": str(updated_output),
            "arguments": {
                "edits": [
                    {
                        "type": "hyperlink_update",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}Jump to greeting",
                        },
                        "match": {
                            "bookmark_name": "Greeting",
                            "text": "Jump to greeting",
                            "expected_matches": 1,
                        },
                        "bookmark_name": "Greeting",
                        "text": "Return to greeting",
                    }
                ]
            },
        },
    )
    updated = _public(project_root, "run", "--request", str(update_request))
    assert updated["status"] == "success", updated
    updated_document = _read_document(
        project_root,
        tmp_path,
        updated_output,
        "read-linked-updated.json",
    )
    updated_body = next(
        story for story in updated_document["stories"] if story["kind"] == "body"
    )
    assert updated_body["paragraphs"][1]["hyperlinks"][0]["text"] == (
        "Return to greeting"
    )
    assert sha256_file(output) == output_sha256
    assert sha256_file(public_created) == source_sha256


def test_public_typed_bookmark_edit_preserves_destination_on_stale_paragraph(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    output = tmp_path / "existing-stale-bookmark.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "typed-stale-bookmark.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "bookmark_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "stale paragraph text",
                        },
                        "name": "Greeting",
                        "range": "paragraph",
                    }
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["errors"][0]["details"]["reason"] == "expected-text"
    assert output.read_bytes() == original_destination
    assert sha256_file(public_created) == source_sha256


def test_public_typed_hyperlink_edit_preserves_destination_on_stale_match(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    linked = tmp_path / "linked-for-stale-match.docx"
    create_request = _request(
        tmp_path,
        "typed-link-stale-setup.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(linked),
            "arguments": {
                "edits": [
                    {
                        "type": "bookmark_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}",
                        },
                        "name": "Greeting",
                        "range": "paragraph",
                    },
                    {
                        "type": "hyperlink_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}",
                        },
                        "bookmark_name": "Greeting",
                        "placement": "append",
                        "text": "Jump to greeting",
                    },
                ]
            },
        },
    )
    created = _public(project_root, "run", "--request", str(create_request))
    assert created["status"] == "success", created
    linked_sha256 = sha256_file(linked)

    output = tmp_path / "existing-stale-hyperlink.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    stale_request = _request(
        tmp_path,
        "typed-stale-hyperlink.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(linked),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "hyperlink_update",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}Jump to greeting",
                        },
                        "match": {
                            "bookmark_name": "Greeting",
                            "text": "stale link text",
                            "expected_matches": 1,
                        },
                        "text": "Return to greeting",
                    }
                ]
            },
        },
    )

    result = _public(
        project_root,
        "run",
        "--request",
        str(stale_request),
        check=False,
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["errors"][0]["details"]["reason"] == "hyperlink-match-count"
    assert output.read_bytes() == original_destination
    assert sha256_file(linked) == linked_sha256


def test_public_typed_edit_preserves_destination_on_selector_mismatch(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    output = tmp_path / "existing-edited.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "typed-edit-mismatch.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "paragraph_style",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "stale caller text",
                        },
                        "style": "Heading2",
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
    assert output.read_bytes() == original_destination
    assert sha256_file(public_created) == source_sha256
