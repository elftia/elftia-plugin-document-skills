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

def test_public_typed_edit_inserts_and_replaces_images_transactionally(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    inserted_image = tmp_path / "inserted.gif"
    inserted_image.write_bytes(_GIF)
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(_PNG_16)
    output = tmp_path / "public-image-edited.docx"
    request = _request(
        tmp_path,
        "typed-image-edit.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "image_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}",
                        },
                        "position": "after",
                        "image": {
                            "path": str(inserted_image),
                            "alt_text": "Inserted chart",
                            "width_inches": 2,
                            "crop": {
                                "left": 5,
                                "top": 10,
                                "right": 15,
                                "bottom": 20,
                            },
                        },
                    },
                    {
                        "type": "image_replace",
                        "target": {
                            "story": "body",
                            "relationship_id": "rIdImage1",
                            "expected_alt_text": "pixel",
                            "expected_media_sha256": sha256(_PNG).hexdigest(),
                        },
                        "image": {
                            "path": str(replacement),
                            "alt_text": "Replacement pixel",
                            "width_inches": 1.5,
                        },
                    },
                ]
            },
        },
    )

    result = _public(project_root, "run", "--request", str(request))

    assert result["status"] == "success", result
    assert result["provider_chain"] == ["core-python"]
    assert result["diagnostics"]["operation_result"]["edit"] == {
        "applied": 2,
        "primitive_counts": {"image_insert": 1, "image_replace": 1},
        "selector_policy": "immutable-input-body-paragraph-and-image-relationship",
    }
    preservation = result["diagnostics"]["operation_result"]["preservation"]
    assert set(preservation["changed_parts"]) == {
        "[Content_Types].xml",
        "word/_rels/document.xml.rels",
        "word/document.xml",
    }
    assert len(preservation["added_parts"]) == 2
    assert "word/media/image1.png" in preservation["preserved_parts"]
    assert (
        preservation["input_hashes"]["word/media/image1.png"]
        == preservation["output_hashes"]["word/media/image1.png"]
    )

    read_request = _request(
        tmp_path,
        "read-image-edited.json",
        {
            "schema_version": "1.0",
            "operation": "docx.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read = _public(project_root, "run", "--request", str(read_request))
    assert [
        image["alt_text"]
        for image in read["diagnostics"]["operation_result"]["document"]["images"]
    ] == ["Inserted chart", "Replacement pixel"]
    assert [
        image["content_type"]
        for image in read["diagnostics"]["operation_result"]["document"]["images"]
    ] == ["image/gif", "image/png"]
    assert [
        image["dimensions_emu"]
        for image in read["diagnostics"]["operation_result"]["document"]["images"]
    ] == [
        {"cx": "1828800", "cy": "1828800"},
        {"cx": "1371600", "cy": "1371600"},
    ]

    with zipfile.ZipFile(output) as archive:
        document = fromstring(archive.read("word/document.xml"))
    inserted = next(
        drawing
        for drawing in document.iter(qn("w", "drawing"))
        if next(drawing.iter(qn("wp", "docPr"))).attrib.get("descr")
        == "Inserted chart"
    )
    crop = next(inserted.iter(qn("a", "srcRect")))
    assert crop.attrib == {"l": "5000", "t": "10000", "r": "15000", "b": "20000"}
    repeated_output = tmp_path / "public-image-edited-repeat.docx"
    repeated_payload = json.loads(request.read_text(encoding="utf-8"))
    repeated_payload["output"] = str(repeated_output)
    repeated_request = _request(
        tmp_path,
        "typed-image-edit-repeat.json",
        repeated_payload,
    )
    repeated = _public(project_root, "run", "--request", str(repeated_request))
    assert repeated["status"] == "success"
    assert repeated_output.read_bytes() == output.read_bytes()
    assert sha256_file(public_created) == source_sha256


def test_public_typed_image_edit_rebases_local_image_from_invocation_directory(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    invocation = tmp_path / "调用目录"
    assets = invocation / "assets"
    assets.mkdir(parents=True)
    (assets / "replacement.png").write_bytes(_PNG_16)
    request = _request(
        tmp_path,
        "typed-image-edit-relative.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": "../public-created.docx",
            "output": "result/edited.docx",
            "arguments": {
                "edits": [
                    {
                        "type": "image_replace",
                        "target": {
                            "story": "body",
                            "relationship_id": "rIdImage1",
                            "expected_alt_text": "pixel",
                            "expected_media_sha256": sha256(_PNG).hexdigest(),
                        },
                        "image": {
                            "path": "assets/replacement.png",
                            "alt_text": "Relative replacement",
                            "width_inches": 1,
                        },
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
        cwd=invocation,
    )

    assert result["status"] == "success", result
    assert (invocation / "result/edited.docx").is_file()
    assert sha256_file(public_created) == source_sha256


def test_public_typed_image_edit_preserves_destination_on_stale_media_selector(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    replacement = tmp_path / "replacement.png"
    replacement.write_bytes(_PNG_16)
    output = tmp_path / "existing-image-edit.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "typed-image-edit-mismatch.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "image_replace",
                        "target": {
                            "story": "body",
                            "relationship_id": "rIdImage1",
                            "expected_alt_text": "stale alt text",
                            "expected_media_sha256": sha256(_PNG).hexdigest(),
                        },
                        "image": {
                            "path": str(replacement),
                            "alt_text": "Replacement pixel",
                        },
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
    assert result["errors"][0]["details"]["reason"] == "expected-alt-text"
    assert output.read_bytes() == original_destination
    assert sha256_file(public_created) == source_sha256


def test_public_typed_image_edit_rejects_crop_that_removes_the_whole_axis(
    project_root: Path,
    public_created: Path,
    tmp_path: Path,
) -> None:
    source_sha256 = sha256_file(public_created)
    image = tmp_path / "replacement.png"
    image.write_bytes(_PNG_16)
    output = tmp_path / "invalid-crop.docx"
    original_destination = b"existing destination must survive"
    output.write_bytes(original_destination)
    request = _request(
        tmp_path,
        "typed-image-edit-invalid-crop.json",
        {
            "schema_version": "1.0",
            "operation": "docx.edit",
            "input": str(public_created),
            "output": str(output),
            "arguments": {
                "edits": [
                    {
                        "type": "image_insert",
                        "target": {
                            "story": "body",
                            "paragraph_index": 1,
                            "expected_text": "Hello {name}",
                        },
                        "position": "after",
                        "image": {
                            "path": str(image),
                            "alt_text": "Invalid crop",
                            "crop": {"left": 60, "right": 40},
                        },
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

    assert result["status"] == "invalid_request"
    assert result["errors"][0]["code"] == "DS_REQUEST_INVALID"
    assert output.read_bytes() == original_destination
    assert sha256_file(public_created) == source_sha256
