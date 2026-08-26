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

def test_public_typed_edit_mutates_tables_with_immutable_hash_selectors(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    document = _read_document(
        project_root,
        tmp_path,
        public_created,
        "read-table-source.json",
    )
    body = next(story for story in document["stories"] if story["kind"] == "body")
    source_table = body["tables"][0]
    assert len(source_table["selector_sha256"]) == 64
    table_target = {
        "story": "body",
        "table_index": 0,
        "expected_table_sha256": source_table["selector_sha256"],
    }
    output = tmp_path / "table-edited.docx"
    request = _request(
        tmp_path,
        "typed-table-edit.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "table_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}",
                        },
                        "position": "after",
                        "table": {
                            "style": "TableGrid",
                            "rows": [["A", "B"], ["C", "D"]],
                        },
                    },
                    {
                        "type": "table_cell_update",
                        "target": table_target,
                        "cell": {
                            "row_index": 1,
                            "cell_index": 1,
                            "expected_text": "PUBLIC",
                        },
                        "text": "APPROVED",
                    },
                    {
                        "type": "table_row_insert",
                        "target": table_target,
                        "anchor": {
                            "row_index": 1,
                            "expected_cells": ["Target", "PUBLIC"],
                        },
                        "position": "after",
                        "cells": ["Owner", "Alice"],
                    },
                    {
                        "type": "table_row_delete",
                        "target": table_target,
                        "row": {
                            "row_index": 0,
                            "expected_cells": ["Key", "Value"],
                        },
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
            "table_cell_update": 1,
            "table_insert": 1,
            "table_row_delete": 1,
            "table_row_insert": 1,
        },
        "selector_policy": "immutable-input-body-paragraph-and-table-sha256",
    }
    assert result["diagnostics"]["operation_result"]["preservation"][
        "changed_parts"
    ] == ["word/document.xml"]
    repeated_output = tmp_path / "table-edited-repeat.docx"
    repeated_payload = json.loads(request.read_text(encoding="utf-8"))
    repeated_payload["output"] = str(repeated_output)
    repeated_request = _request(
        tmp_path,
        "typed-table-edit-repeat.json",
        repeated_payload,
    )
    repeated = _public(project_root, "run", "--request", str(repeated_request))
    assert repeated["status"] == "success"
    assert repeated_output.read_bytes() == output.read_bytes()
    edited_document = _read_document(
        project_root,
        tmp_path,
        output,
        "read-table-edited.json",
    )
    edited_body = next(
        story for story in edited_document["stories"] if story["kind"] == "body"
    )
    assert [_table_values(table) for table in edited_body["tables"]] == [
        [["A", "B"], ["C", "D"]],
        [["Target", "APPROVED"], ["Owner", "Alice"]],
    ]

    inserted_table = edited_body["tables"][0]
    edited_sha256 = sha256_file(output)
    merged_output = tmp_path / "table-merged.docx"
    merge_request = _request(
        tmp_path,
        "typed-table-merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(output),
            "output": str(merged_output),
            "arguments": {
                "edits": [
                    {
                        "type": "table_cells_merge",
                        "target": {
                            "story": "body",
                            "table_index": 0,
                            "expected_table_sha256": inserted_table[
                                "selector_sha256"
                            ],
                        },
                        "range": {
                            "start_row": 0,
                            "start_column": 0,
                            "end_row": 0,
                            "end_column": 1,
                            "expected_texts": [["A", "B"]],
                        },
                        "text": "A + B",
                    }
                ]
            },
        },
    )
    merged = _public(project_root, "run", "--request", str(merge_request))
    assert merged["status"] == "success", merged
    assert merged["diagnostics"]["operation_result"]["edit"][
        "primitive_counts"
    ] == {"table_cells_merge": 1}
    assert sha256_file(output) == edited_sha256
    merged_document = _read_document(
        project_root,
        tmp_path,
        merged_output,
        "read-table-merged.json",
    )
    merged_body = next(
        story for story in merged_document["stories"] if story["kind"] == "body"
    )
    merged_table = merged_body["tables"][0]
    assert _table_values(merged_table)[0] == ["A + B"]
    assert merged_table["rows"][0]["cells"][0]["grid_span"] == "2"

    merged_sha256 = sha256_file(merged_output)
    split_output = tmp_path / "table-split.docx"
    split_request = _request(
        tmp_path,
        "typed-table-split.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(merged_output),
            "output": str(split_output),
            "arguments": {
                "edits": [
                    {
                        "type": "table_cell_split",
                        "target": {
                            "story": "body",
                            "table_index": 0,
                            "expected_table_sha256": merged_table[
                                "selector_sha256"
                            ],
                        },
                        "cell": {
                            "row_index": 0,
                            "cell_index": 0,
                            "expected_text": "A + B",
                        },
                        "texts": ["A", "B"],
                    }
                ]
            },
        },
    )
    split = _public(project_root, "run", "--request", str(split_request))
    assert split["status"] == "success", split
    assert split["diagnostics"]["operation_result"]["edit"][
        "primitive_counts"
    ] == {"table_cell_split": 1}
    assert sha256_file(merged_output) == merged_sha256
    split_document = _read_document(
        project_root,
        tmp_path,
        split_output,
        "read-table-split.json",
    )
    split_body = next(
        story for story in split_document["stories"] if story["kind"] == "body"
    )
    assert _table_values(split_body["tables"][0])[0] == ["A", "B"]
    assert sha256_file(public_created) == source_sha256
    assert sha256_file(output) != sha256_file(merged_output)
    assert sha256_file(merged_output) != sha256_file(split_output)


def test_public_typed_table_edit_preserves_destination_on_stale_table_hash(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    output = tmp_path / "existing-table-edit.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "typed-table-edit-mismatch.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "table_cell_update",
                        "target": {
                            "story": "body",
                            "table_index": 0,
                            "expected_table_sha256": "0" * 64,
                        },
                        "cell": {
                            "row_index": 1,
                            "cell_index": 1,
                            "expected_text": "PUBLIC",
                        },
                        "text": "APPROVED",
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
    assert result["errors"][0]["details"]["reason"] == "expected-table-sha256"
    assert output.read_bytes() == original_destination
    assert sha256_file(public_created) == source_sha256
