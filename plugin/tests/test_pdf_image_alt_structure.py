"""Public PDF create coverage for image alternative-text structure binding."""

import hashlib
from pathlib import Path

from pypdf import PdfReader
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.create_image_validation import (
    actual_image_draws,
)
from document_skills_core.formats.pdf.object_model import parse_pdf
from document_skills_core.formats.pdf.page_tree import walk_pages
from document_skills_core.formats.pdf.validation import reopen_pdf, validate_created
from tests.test_pdf_public import _PNG, _public, _request


def test_public_create_read_reopens_tagged_images_with_exact_structure_binding(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "tagged.png"
    image.write_bytes(_PNG)
    document = _image_document(
        image,
        [["Cover image", "封面图像", None], ["Second page", None]],
    )
    output = tmp_path / "tagged-images.pdf"
    create_request = _request(
        tmp_path,
        "create-tagged-images.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )

    created = _public(project_root, "run", "--request", str(create_request))

    assert created["status"] == "success", created
    creation = created["diagnostics"]["operation_result"]["creation"]
    assert validate_created(output, document, creation)["status"] == "pass"
    assert reopen_pdf(output)["pages"] == 2
    repeated_output = tmp_path / "tagged-images-repeated.pdf"
    repeated_request = _request(
        tmp_path,
        "create-tagged-images-repeated.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(repeated_output),
            "arguments": {"document": document},
        },
    )
    repeated = _public(project_root, "run", "--request", str(repeated_request))
    assert repeated["status"] == "success", repeated
    assert repeated_output.read_bytes() == output.read_bytes()
    assert (
        repeated["diagnostics"]["operation_result"]["creation"]["image_structure"]
        == creation["image_structure"]
    )

    read_request = _request(
        tmp_path,
        "read-tagged-images.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.read",
            "input": str(output),
            "arguments": {},
        },
    )
    read = _public(project_root, "run", "--request", str(read_request))
    assert read["status"] == "success", read
    operation = read["diagnostics"]["operation_result"]
    assert operation["page_count"] == 2
    assert [len(images) for images in operation["images_by_page"]] == [3, 2]

    records = creation["images"]
    associations = creation["image_structure"]
    assert [(item["page"], item["alt"], item["mcid"]) for item in associations] == [
        (1, "Cover image", 0),
        (1, "封面图像", 1),
        (1, None, None),
        (2, "Second page", 0),
        (2, None, None),
    ]
    assert [item["struct_parent"] for item in associations] == [0, 0, None, 1, None]
    assert all(
        item["structure_object"] > 0
        for item in associations
        if item["alt"]
    )
    assert all(
        item["structure_object"] is None
        for item in associations
        if not item["alt"]
    )

    model = parse_pdf(output)
    pages = walk_pages(model)
    draws = actual_image_draws(model, pages)
    for expected, association in zip(records, associations):
        actual = next(
            item
            for item in draws
            if item["page"] == expected["page"]
            and item["object"] == expected["image_object"]
        )
        assert actual["visible_bbox"] == expected["bbox"]
        assert actual["mcid"] == association["mcid"]

    reader = PdfReader(str(output))
    catalog = reader.trailer["/Root"]
    assert bool(catalog["/MarkInfo"]["/Marked"]) is True
    structure_root = catalog["/StructTreeRoot"].get_object()
    elements = [reference.get_object() for reference in structure_root["/K"]]
    assert [element.indirect_reference.idnum for element in elements] == [
        item["structure_object"] for item in associations if item["alt"]
    ]
    assert [element["/S"] for element in elements] == ["/Figure"] * 3
    assert [element["/Alt"] for element in elements] == [
        "Cover image",
        "封面图像",
        "Second page",
    ]
    assert [element["/K"] for element in elements] == [0, 1, 0]
    assert [page["/StructParents"] for page in reader.pages] == [0, 1]
    assert [
        element["/Pg"].indirect_reference.idnum
        for element in elements
    ] == [
        reader.pages[0].indirect_reference.idnum,
        reader.pages[0].indirect_reference.idnum,
        reader.pages[1].indirect_reference.idnum,
    ]
    parent_numbers = structure_root["/ParentTree"].get_object()["/Nums"]
    assert list(parent_numbers[0::2]) == [0, 1]
    assert [len(children) for children in parent_numbers[1::2]] == [2, 1]
    assert [
        [reference.idnum for reference in children]
        for children in parent_numbers[1::2]
    ] == [
        [elements[0].indirect_reference.idnum, elements[1].indirect_reference.idnum],
        [elements[2].indirect_reference.idnum],
    ]


def test_public_create_without_alt_does_not_invent_tag_structure(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "untagged.png"
    image.write_bytes(_PNG)
    document = _image_document(image, [[None, ""], [None]])
    first = tmp_path / "untagged-first.pdf"
    second = tmp_path / "untagged-second.pdf"

    for index, output in enumerate((first, second), start=1):
        request = _request(
            tmp_path,
            f"create-untagged-{index}.json",
            {
                "schema_version": "1.0",
                "operation": "pdf.create",
                "output": str(output),
                "arguments": {"document": document},
            },
        )
        result = _public(project_root, "run", "--request", str(request))
        assert result["status"] == "success", result
        assert all(
            item["mcid"] is None
            and item["struct_parent"] is None
            and item["structure_object"] is None
            for item in result["diagnostics"]["operation_result"]["creation"]["image_structure"]
        )

    assert first.read_bytes() == second.read_bytes()
    reader = PdfReader(str(first))
    catalog = reader.trailer["/Root"]
    assert "/MarkInfo" not in catalog
    assert "/StructTreeRoot" not in catalog
    assert all("/StructParents" not in page for page in reader.pages)
    assert b"/Figure" not in first.read_bytes()


@pytest.mark.parametrize(
    ("original", "tampered"),
    [
        (b"/MCID 0", b"/MCID 9"),
        (b"/StructParents 0", b"/StructParents 9"),
    ],
)
def test_create_validation_fails_closed_on_broken_image_structure_binding(
    project_root: Path,
    tmp_path: Path,
    original: bytes,
    tampered: bytes,
) -> None:
    image = tmp_path / "tamper.png"
    image.write_bytes(_PNG)
    document = _image_document(image, [["Bound figure"]])
    output = tmp_path / "tamper.pdf"
    request = _request(
        tmp_path,
        "create-tamper.json",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(output),
            "arguments": {"document": document},
        },
    )
    result = _public(project_root, "run", "--request", str(request))
    assert result["status"] == "success", result
    creation = result["diagnostics"]["operation_result"]["creation"]

    raw = output.read_bytes()
    assert raw.count(original) == 1
    output.write_bytes(raw.replace(original, tampered, 1))

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(output, document, creation)
    assert caught.value.code is ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize("tamper", ["remove", "replace"])
def test_create_validation_binds_image_xobject_alt_exactly(
    tmp_path: Path,
    tamper: str,
) -> None:
    image = tmp_path / "alt-xobject.png"
    image.write_bytes(_PNG)
    document = _image_document(image, [["Cover image"]])
    output = tmp_path / f"alt-xobject-{tamper}.pdf"
    creation = create_pdf(output, document)
    raw = output.read_bytes()
    image_object = creation["images"][0]["image_object"]
    object_start = raw.index(f"{image_object} 0 obj\n".encode("ascii"))
    object_end = raw.index(b"endobj", object_start)
    payload = raw[object_start:object_end]
    original = b"/Alt (Cover image)"
    replacement = b" " * len(original) if tamper == "remove" else b"/Alt (Wrong image)"
    assert len(original) == len(replacement)
    assert original in payload
    output.write_bytes(
        raw[:object_start] + payload.replace(original, replacement, 1) + raw[object_end:]
    )

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(output, document, creation)
    assert caught.value.code is ErrorCode.VALIDATION_FAILED
    gate = next(
        item
        for item in caught.value.validation["gates"]
        if item["id"] == "operation.create-semantics"
    )
    assert gate["evidence"]["image_mismatches"] == [
        {"reason": "image-object-mismatch", "object": image_object}
    ]


def _image_document(
    image: Path,
    page_alts: list[list[str | None]],
) -> dict[str, object]:
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    return {
        "metadata": {"title": "Image tags", "author": "Elftia", "subject": ""},
        "page_size": "A4",
        "pages": [
            {
                "blocks": [_image_block(image, digest, alt) for alt in alts],
                "metadata": None,
            }
            for alts in page_alts
        ],
    }


def _image_block(image: Path, digest: str, alt: str | None) -> dict[str, object]:
    return {
        "type": "image",
        "text": None,
        "style": None,
        "table": None,
        "image": {
            "filename": str(image),
            "sha256": digest,
            "content_type": "image/png",
            "fit": "contain",
            "width": 40,
            "height": 24,
            "alt": alt,
        },
        "shape": None,
    }
