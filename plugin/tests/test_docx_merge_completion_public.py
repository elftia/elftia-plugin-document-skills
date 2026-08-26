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

def test_public_merge_copies_body_tables_images_sections_and_story_graph(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_image = tmp_path / "merge-source.png"
    source_image.write_bytes(_PNG_16)
    source = tmp_path / "merge-source.docx"
    source_report = _report(str(source_image))
    source_report["metadata"] = {"title": "Merged source"}
    source_report["blocks"] = [
        {"type": "heading", "text": "Merged source", "level": 1},
        {"type": "paragraph", "text": "Merged source body"},
        {"type": "table", "rows": [["Source", "Value"], ["B", "2"]]},
    ]
    source_report["header"] = "Merged source header"
    source_report["footer"] = "Merged source footer"
    create_request = _request(
        tmp_path,
        "merge-source-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(source),
            "arguments": {"report": source_report},
        },
    )
    created = _public(project_root, "run", "--request", str(create_request))
    assert created["status"] == "success", created
    base_sha256 = sha256_file(public_created)
    source_sha256 = sha256_file(source)
    output = tmp_path / "merged.docx"
    request = _request(
        tmp_path,
        "merge.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "sources": [
                    {
                        "path": str(source),
                        "expected_sha256": source_sha256,
                    }
                ],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    assert result["provider_chain"] == ["core-python"]
    merged = result["diagnostics"]["operation_result"]["merge"]
    assert merged["source_count"] == 1
    assert merged["styles"] == "identical"
    assert merged["numbering"] == "identical"
    assert merged["copied_body_blocks"] >= 3
    document = _read_document(project_root, tmp_path, output, "read-merged.json")
    body = next(story for story in document["stories"] if story["kind"] == "body")
    assert any(item["text"] == "Merged source body" for item in body["paragraphs"])
    assert len(body["tables"]) == 2
    assert len(document["images"]) == 2
    assert len(document["sections"]) == 4
    assert any(
        story["kind"] == "header" and story["paragraphs"][0]["text"] == "Merged source header"
        for story in document["stories"]
    )
    structural = result["diagnostics"]["operation_result"]["structure_diff"]
    assert structural["counts"]["tables"]["delta"] == 1
    assert structural["counts"]["images"]["delta"] == 1
    assert structural["counts"]["sections"]["delta"] == 2
    repeated_output = tmp_path / "merged-repeated.docx"
    repeated_payload = json.loads(request.read_text(encoding="utf-8"))
    repeated_payload["output"] = str(repeated_output)
    repeated_request = _request(tmp_path, "merge-repeated.json", repeated_payload)
    repeated = _public(project_root, "run", "--request", str(repeated_request))
    assert repeated["status"] == "success", repeated
    assert repeated_output.read_bytes() == output.read_bytes()
    assert sha256_file(public_created) == base_sha256
    assert sha256_file(source) == source_sha256


def test_public_merge_stale_source_hash_preserves_destination(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source = tmp_path / "stale-merge-source.docx"
    source.write_bytes(public_created.read_bytes())
    base_sha256 = sha256_file(public_created)
    source_sha256 = sha256_file(source)
    output = tmp_path / "existing-stale-merge.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "merge-stale.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "sources": [{"path": str(source), "expected_sha256": "0" * 64}],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "failed"
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    assert result["errors"][0]["details"]["reason"] == "expected-source-sha256"
    assert output.read_bytes() == original_destination
    assert sha256_file(public_created) == base_sha256
    assert sha256_file(source) == source_sha256


def test_public_merge_refuses_nonidentical_styles_without_clobbering(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "merge-style-source.png"
    image.write_bytes(_PNG)
    source = tmp_path / "merge-style-source.docx"
    report = _report(str(image))
    report["blocks"] = [
        {"type": "heading", "text": "Level three", "level": 3},
        {"type": "paragraph", "text": "Style conflict source"},
    ]
    create_request = _request(
        tmp_path,
        "merge-style-create.json",
        {
            "schema_version": "1.0",
            "operation": "docx.create",
            "output": str(source),
            "arguments": {"report": report},
        },
    )
    created = _public(project_root, "run", "--request", str(create_request))
    assert created["status"] == "success", created
    source_sha256 = sha256_file(source)
    output = tmp_path / "existing-style-conflict.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "merge-style-conflict.json",
        {
            "schema_version": "1.0",
            "operation": "docx.merge",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "sources": [{"path": str(source), "expected_sha256": source_sha256}],
                "style_conflict_policy": "require-identical",
                "numbering_conflict_policy": "require-identical",
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request), check=False)

    assert result["status"] == "enhancement_required"
    assert result["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert "word/styles.xml" in result["errors"][0]["details"]["mismatched_parts"]
    assert output.read_bytes() == original_destination


def test_public_unknown_format_operation_never_reaches_docx_provider(
    project_root: Path,
    tmp_path: Path,
) -> None:
    request = _request(
        tmp_path,
        "unknown.json",
        {
            "schema_version": "1.0",
            "operation": "pdfx.read",
            "input": str(tmp_path / "input.pdfx"),
            "arguments": {},
        },
    )
    result = _public(project_root, "run", "--request", str(request), check=False)
    assert result["status"] == "invalid_request"
    assert result["provider_chain"] == []
    assert result["errors"][0]["code"] == "DS_OPERATION_UNKNOWN"


def test_public_expected_docx_errors_keep_specific_codes(
    project_root: Path,
    tmp_path: Path,
) -> None:
    invalid_request = _request(
        tmp_path,
        "invalid-docx.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(tmp_path / "input.docx"),
            "arguments": {"unknown": True},
        },
    )
    invalid = _public(
        project_root,
        "run",
        "--request",
        str(invalid_request),
        check=False,
    )
    assert invalid["status"] == "invalid_request"
    assert invalid["provider_chain"] == []
    assert invalid["errors"][0]["code"] == "DS_REQUEST_INVALID"

    fixture_root = project_root / "tests" / "fixtures"
    unsafe_request = _request(
        tmp_path,
        "unsafe-docx.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(fixture_root / "docx-malicious-active.docx"),
            "arguments": {},
        },
    )
    unsafe = _public(
        project_root,
        "run",
        "--request",
        str(unsafe_request),
        check=False,
    )
    assert unsafe["status"] == "failed"
    assert unsafe["provider_chain"] == ["core-python"]
    assert unsafe["errors"][0]["code"] == "DS_ARCHIVE_UNSAFE"

    protected_output = tmp_path / "protected-output.docx"
    protected_request = _request(
        tmp_path,
        "protected-docx.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit.replace-text",
            "input": str(fixture_root / "docx-revision-comments.docx"),
            "output": str(protected_output),
            "arguments": {
                "replacements": [
                    {"search": "revision-only", "replace": "changed"}
                ]
            },
        },
    )
    protected = _public(
        project_root,
        "run",
        "--request",
        str(protected_request),
        check=False,
    )
    assert protected["status"] == "enhancement_required"
    assert protected["provider_chain"] == ["core-python"]
    assert protected["errors"][0]["code"] == "DS_ENHANCEMENT_REQUIRED"
    assert not protected_output.exists()
