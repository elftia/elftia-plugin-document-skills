"""Request-bound create validation and PDF-specific promotion failures."""

from io import BytesIO
import hashlib
from pathlib import Path
import re
import zlib

from PIL import Image
import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.content_streams import walk_text_operators
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.service import PdfService
from document_skills_core.formats.pdf.trailer_preflight import trailer_has_encrypt
from document_skills_core.formats.pdf.validation import reopen_pdf, validate_created
import document_skills_core.formats.pdf.service as service_module
from tests.test_pdf_operations import (
    _build_action_pdf,
    _build_encrypted_pdf,
    _build_minimal_pdf,
    _minimal_text_document,
)


def test_create_gate_binds_page_box_and_text_style(tmp_path: Path) -> None:
    document = _styled_document()
    candidate = tmp_path / "styled.pdf"
    creation = create_pdf(candidate, document)
    assert validate_created(candidate, document, creation)["status"] == "pass"

    raw = candidate.read_bytes()
    assert b"/MediaBox [0 0 400 300]" in raw
    candidate.write_bytes(raw.replace(
        b"/MediaBox [0 0 400 300]",
        b"/MediaBox [0 0 401 300]",
        1,
    ))
    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED

    creation = create_pdf(candidate, document)
    raw = candidate.read_bytes()
    assert b"/F4 18 Tf" in raw
    candidate.write_bytes(raw.replace(b"/F4 18 Tf", b"/F4 19 Tf", 1))
    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


def test_create_gate_rejects_text_matrix_scaling(tmp_path: Path) -> None:
    document = _styled_document()
    candidate = tmp_path / "scaled-text.pdf"
    creation = create_pdf(candidate, document)

    raw = candidate.read_bytes()
    assert b"1 0 0 1 " in raw
    candidate.write_bytes(raw.replace(b"1 0 0 1 ", b"2 0 0 2 ", 1))

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


def test_text_bbox_applies_rotated_text_matrix() -> None:
    blocks = walk_text_operators(
        b"BT /F1 12 Tf 0 1 -1 0 100 100 Tm (abcd) Tj ET",
        1,
    )

    assert len(blocks) == 1
    assert blocks[0].bbox == pytest.approx((90.4, 100.0, 102.4, 126.016))


def test_trailer_encryption_detection_follows_escaped_prev_key() -> None:
    raw = bytearray(b"%PDF-1.7\n")
    previous_offset = len(raw)
    raw.extend(
        b"xref\n0 1\n0000000000 65535 f\r\n"
        b"trailer\n<< /Size 1 /Encrypt 5 0 R >>\n"
        + f"startxref\n{previous_offset}\n%%EOF\n".encode("ascii")
    )
    final_offset = len(raw)
    raw.extend(
        b"xref\n0 1\n0000000000 65535 f\r\n"
        + f"trailer\n<< /Size 1 /Pr#65v {previous_offset} >>\n".encode("ascii")
        + f"startxref\n{final_offset}\n%%EOF\n".encode("ascii")
    )

    assert trailer_has_encrypt(bytes(raw), max_depth=8) is True


def test_create_gate_binds_image_draw_object_hash_and_bbox(tmp_path: Path) -> None:
    image = tmp_path / "pixel.png"
    image.write_bytes(_png())
    document = _image_document(image)
    candidate = tmp_path / "image.pdf"
    creation = create_pdf(candidate, document)

    report = validate_created(candidate, document, creation)
    gate = next(item for item in report["gates"] if item["id"] == "operation.create-semantics")
    image_evidence = gate["evidence"]["images"][0]
    assert image_evidence["object"] == creation["images"][0]["image_object"]
    assert image_evidence["asset_sha256"] == hashlib.sha256(image.read_bytes()).hexdigest()
    assert image_evidence["object_sha256"]
    assert image_evidence["visible_bbox"] == creation["images"][0]["bbox"]

    raw = candidate.read_bytes()
    assert b"/Im1 Do" in raw
    candidate.write_bytes(raw.replace(b"/Im1 Do", b"/Ix1 Do", 1))
    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


def test_create_gate_binds_png_alpha_soft_mask(tmp_path: Path) -> None:
    image = tmp_path / "alpha.png"
    image.write_bytes(_alpha_png())
    document = _image_document(image)
    candidate = tmp_path / "alpha.pdf"
    creation = create_pdf(candidate, document)

    report = validate_created(candidate, document, creation)
    gate = next(item for item in report["gates"] if item["id"] == "operation.create-semantics")
    image_evidence = gate["evidence"]["images"][0]
    assert image_evidence["soft_mask_object"] > 0
    assert image_evidence["soft_mask_object_sha256"]
    assert image_evidence["alpha_sha256"] == hashlib.sha256(
        bytes([0, 85, 170, 255])
    ).hexdigest()

    raw = candidate.read_bytes()
    without_soft_mask, replacements = re.subn(
        rb"/SMask\s+\d+\s+0\s+R",
        lambda match: b" " * len(match.group(0)),
        raw,
        count=1,
    )
    assert replacements == 1
    candidate.write_bytes(without_soft_mask)

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


def test_create_gate_rejects_tampered_png_alpha_stream(tmp_path: Path) -> None:
    image = tmp_path / "alpha.png"
    image.write_bytes(_alpha_png())
    document = _image_document(image)
    candidate = tmp_path / "alpha-tampered.pdf"
    creation = create_pdf(candidate, document)

    raw = candidate.read_bytes()
    expected_alpha = zlib.compress(bytes([0, 85, 170, 255]), level=9)
    tampered_alpha = zlib.compress(bytes([255, 170, 85, 0]), level=9)
    assert len(expected_alpha) == len(tampered_alpha)
    assert expected_alpha in raw
    candidate.write_bytes(raw.replace(expected_alpha, tampered_alpha, 1))

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize(
    ("source", "replacement"),
    [
        (b"/Width 2", b"/Width 3"),
        (b"/ColorSpace /DeviceGray", b"/ColorSpace /DeviceRGB "),
    ],
)
def test_create_gate_rejects_png_soft_mask_contract_tampering(
    tmp_path: Path,
    source: bytes,
    replacement: bytes,
) -> None:
    image = tmp_path / "alpha.png"
    image.write_bytes(_alpha_png())
    document = _image_document(image)
    candidate = tmp_path / "alpha-contract.pdf"
    creation = create_pdf(candidate, document)

    raw = candidate.read_bytes()
    soft_mask_match = re.search(rb"/SMask\s+(\d+)\s+0\s+R", raw)
    assert soft_mask_match is not None
    soft_mask_object = soft_mask_match.group(1) + b" 0 obj"
    object_start = raw.index(soft_mask_object)
    object_end = raw.index(b"endobj", object_start)
    payload = raw[object_start:object_end]
    assert source in payload
    assert len(source) == len(replacement)
    candidate.write_bytes(
        raw[:object_start]
        + payload.replace(source, replacement, 1)
        + raw[object_end:]
    )

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


def test_create_gate_rejects_cover_image_without_clip(tmp_path: Path) -> None:
    image = tmp_path / "wide.png"
    image.write_bytes(_png(width=4, height=2))
    document = _image_document(image, fit="cover")
    candidate = tmp_path / "cover.pdf"
    creation = create_pdf(candidate, document)
    assert validate_created(candidate, document, creation)["status"] == "pass"

    raw = candidate.read_bytes()
    without_clip, replacements = re.subn(
        rb"[^\r\n]+ re W n",
        lambda match: b" " * len(match.group(0)),
        raw,
        count=1,
    )
    assert replacements == 1
    candidate.write_bytes(without_clip)

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


def test_create_gate_rejects_tampered_line_path(tmp_path: Path) -> None:
    document = _shape_document()
    candidate = tmp_path / "line-path.pdf"
    creation = create_pdf(candidate, document)
    assert validate_created(candidate, document, creation)["status"] == "pass"

    raw = candidate.read_bytes()
    assert b"30 40 m\n100 60 l" in raw
    candidate.write_bytes(raw.replace(b"30 40 m\n100 60 l", b"30 40 m\n101 60 l", 1))

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


def test_create_gate_rejects_tampered_ellipse_graphics_state(tmp_path: Path) -> None:
    document = _shape_document()
    candidate = tmp_path / "ellipse-style.pdf"
    creation = create_pdf(candidate, document)
    assert validate_created(candidate, document, creation)["status"] == "pass"

    raw = candidate.read_bytes()
    assert b"/ca 0.6 /CA 0.6" in raw
    candidate.write_bytes(raw.replace(b"/ca 0.6 /CA 0.6", b"/ca 0.7 /CA 0.7", 1))

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


@pytest.mark.parametrize(
    ("source", "replacement"),
    [
        (b"1 0 0 RG", b"0 0 0 RG"),
        (b"[3 2] 0 d", b"[4 2] 0 d"),
        (b"\nh\nB\nQ", b"\nh\nS\nQ"),
    ],
)
def test_create_gate_rejects_tampered_shape_content_style(
    tmp_path: Path,
    source: bytes,
    replacement: bytes,
) -> None:
    document = _shape_document()
    candidate = tmp_path / "shape-style.pdf"
    creation = create_pdf(candidate, document)

    raw = candidate.read_bytes()
    assert source in raw
    assert len(source) == len(replacement)
    candidate.write_bytes(raw.replace(source, replacement, 1))

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)
    assert caught.value.code == ErrorCode.VALIDATION_FAILED


def test_create_gate_uses_request_shape_semantics_not_creation_style_claims(
    tmp_path: Path,
) -> None:
    document = _shape_document()
    candidate = tmp_path / "shape-creation-claims.pdf"
    creation = create_pdf(candidate, document)

    creation["shapes"][0].update({
        "kind": "rectangle",
        "stroke": [0.0, 0.0, 0.0],
        "fill": [1.0, 1.0, 1.0],
        "opacity": 0.1,
        "dash": [9.0],
        "corner_radius": 99.0,
    })

    assert validate_created(candidate, document, creation)["status"] == "pass"


def test_create_gate_rejects_static_shape_creation_page_override(
    tmp_path: Path,
) -> None:
    document = _shape_document()
    document["pages"].append(_minimal_text_document("Second page")["pages"][0])
    candidate = tmp_path / "shape-static-page-claim.pdf"
    creation = create_pdf(candidate, document)
    mapped_pages = creation["mapping"]["pages"]
    mapped_shapes = [
        block
        for block in mapped_pages[0]["blocks"]
        if block["type"] == "vector_shape"
    ]
    mapped_pages[0]["blocks"] = [
        block
        for block in mapped_pages[0]["blocks"]
        if block["type"] != "vector_shape"
    ]
    for shape, mapped_shape in zip(creation["shapes"], mapped_shapes):
        shape["page"] = 2
        mapped_shape["object"] = mapped_pages[1]["content_stream_object"]
        mapped_pages[1]["blocks"].append(mapped_shape)

    with pytest.raises(DocumentSkillsError) as caught:
        validate_created(candidate, document, creation)

    gate = next(
        item
        for item in caught.value.validation["gates"]
        if item["id"] == "operation.create-semantics"
    )
    assert gate["evidence"]["shape_mismatches"] == [{
        "reason": "shape-creation-page-mismatch",
        "index": 0,
    }]


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("missing-record", "shape-creation-record-count"),
        ("reversed", "shape-creation-order-mismatch"),
        ("missing-page", "shape-creation-page-invalid"),
        ("string-page", "shape-creation-page-invalid"),
        ("zero-page", "shape-creation-page-invalid"),
        ("out-of-range-page", "shape-creation-page-invalid"),
    ],
)
def test_pdf_create_rejects_invalid_paginated_shape_placement_atomically(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_reason: str,
) -> None:
    destination = tmp_path / f"invalid-shape-placement-{case}.pdf"
    destination_before = b"existing-destination"
    destination.write_bytes(destination_before)
    real_create = service_module.create_pdf

    def tampered(*args, **kwargs):
        creation = real_create(*args, **kwargs)
        shapes = creation["shapes"]
        assert len(shapes) == 2
        if case == "missing-record":
            shapes.pop()
        elif case == "reversed":
            shapes.reverse()
        elif case == "missing-page":
            shapes[0].pop("page")
        elif case == "string-page":
            shapes[0]["page"] = "1"
        elif case == "zero-page":
            shapes[0]["page"] = 0
        else:
            shapes[0]["page"] = creation["page_count"] + 1
        return creation

    monkeypatch.setattr(service_module, "create_pdf", tampered)
    result = PdfService(project_root).execute(
        "pdf.create",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(destination),
            "arguments": {"document": _paginated_shape_document()},
        },
    )

    assert result["status"] == "failed", result
    assert result["errors"][0]["code"] == "DS_VALIDATION_FAILED"
    gate = next(
        item
        for item in result["validation"]["gates"]
        if item["id"] == "operation.create-semantics"
    )
    details = gate["evidence"]
    assert "shape_mismatches" in details, result
    reasons = {
        mismatch["reason"]
        for mismatch in details["shape_mismatches"]
    }
    assert expected_reason in reasons
    assert result["artifacts"] == []
    assert destination.read_bytes() == destination_before


def test_pdf_create_public_result_maps_pages_and_blocks(
    project_root: Path,
    tmp_path: Path,
) -> None:
    image = tmp_path / "mapped.png"
    image.write_bytes(_png())
    document = _image_document(image)
    destination = tmp_path / "mapped.pdf"

    result = PdfService(project_root).execute(
        "pdf.create",
        {
            "schema_version": "1.0",
            "operation": "pdf.create",
            "output": str(destination),
            "arguments": {"document": document},
        },
    )

    assert result["status"] == "success", result
    creation = result["diagnostics"]["operation_result"]["creation"]
    mapping = creation["mapping"]
    assert mapping["schema_version"] == "1.0"
    assert len(mapping["pages"]) == 1
    page = mapping["pages"][0]
    assert set(page) == {
        "page",
        "page_object",
        "content_stream_object",
        "bbox",
        "blocks",
    }
    assert page["page"] == 1
    assert page["bbox"] == [0.0, 0.0, 595.276, 841.89]
    assert page["page_object"] > 0
    assert page["content_stream_object"] > 0
    assert page["blocks"] == [
        {
            "block_index": 0,
            "type": "paragraph",
            "object": page["content_stream_object"],
            "bbox": creation["text_blocks"][0]["bbox"],
        },
        {
            "block_index": 1,
            "type": "image",
            "object": creation["images"][0]["image_object"],
            "bbox": creation["images"][0]["bbox"],
        },
    ]


@pytest.mark.parametrize(
    "builder",
    [
        lambda path: _build_action_pdf(path, "<< /S /JavaScript /JS (noop) >>"),
        _build_encrypted_pdf,
    ],
)
def test_reopen_gate_rejects_active_or_encrypted_candidate(tmp_path: Path, builder) -> None:
    candidate = builder(tmp_path / "unsafe.pdf")

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_reopen_gate_rejects_names_tree_javascript(tmp_path: Path) -> None:
    candidate = _build_minimal_pdf(
        tmp_path / "names-javascript.pdf",
        " /Names << /JavaScript << /Names "
        "[(entry) << /S /JavaScript /JS (noop) >>] >> >>",
    )

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


@pytest.mark.parametrize(
    "separator",
    [b"% comment before the value\n", b"\f", b"\x00"],
)
def test_reopen_gate_rejects_action_with_pdf_lexical_separator(
    tmp_path: Path,
    separator: bytes,
) -> None:
    candidate = _build_object_graph_pdf(
        tmp_path / "lexical-separator-javascript.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R /OpenAction 4 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
            b"<< /S" + separator + b"/JavaScript /JS (noop) >>",
        ],
    )

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


@pytest.mark.parametrize("entry_name", [b"/AA", b"/AdditionalActions"])
def test_reopen_gate_rejects_indirect_additional_action(
    tmp_path: Path,
    entry_name: bytes,
) -> None:
    candidate = _build_object_graph_pdf(
        tmp_path / f"indirect-{entry_name[1:].decode('ascii')}-uri.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                + entry_name
                + b" << /O 4 0 R >> >>"
            ),
            b"<< /S /URI /URI (https://example.invalid/) >>",
        ],
    )

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_reopen_gate_rejects_standard_indirect_embedded_executable(
    tmp_path: Path,
) -> None:
    candidate = _build_object_graph_pdf(
        tmp_path / "embedded-executable.pdf",
        [
            (
                b"<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles "
                b"<< /Names [(run.exe) 4 0 R] >> >> >>"
            ),
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
            b"<< /Type /Filespec /F (run.exe) /EF << /F 5 0 R >> >>",
            (
                b"<< /Type /EmbeddedFile /Subtype /application#2Fx-dosexec "
                b"/Length 2 >>\nstream\nMZ\nendstream"
            ),
        ],
    )

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_reopen_gate_allows_standard_indirect_text_attachment(tmp_path: Path) -> None:
    candidate = _build_object_graph_pdf(
        tmp_path / "embedded-text-attachment.pdf",
        [
            (
                b"<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles "
                b"<< /Names [(notes.txt) 4 0 R] >> >> >>"
            ),
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
            b"<< /Type /Filespec /F (notes.txt) /EF << /F 5 0 R >> >>",
            (
                b"<< /Type /EmbeddedFile /Subtype /text#2Fplain /Length 5 >>\n"
                b"stream\nhello\nendstream"
            ),
        ],
    )

    reopened = reopen_pdf(candidate)

    assert reopened["pages"] == 1
    assert reopened["object_count"] == 5
    assert reopened["encrypted"] is False


@pytest.mark.parametrize(
    ("filename", "subtype", "payload"),
    [
        (b"run.exe", b"", b"plain"),
        (b"run.exe", b"/Subtype /application#2Foctet-stream ", b"plain"),
        (b"payload.bin", b"/Subtype /application#2Foctet-stream ", b"MZpayload"),
    ],
)
def test_reopen_gate_rejects_embedded_executable_evidence_without_specific_mime(
    tmp_path: Path,
    filename: bytes,
    subtype: bytes,
    payload: bytes,
) -> None:
    candidate = _build_object_graph_pdf(
        tmp_path / "embedded-executable-evidence.pdf",
        [
            (
                b"<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles "
                b"<< /Names [(entry) 4 0 R] >> >> >>"
            ),
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
            b"<< /Type /Filespec /F (" + filename + b") /EF << /F 5 0 R >> >>",
            (
                b"<< /Type /EmbeddedFile "
                + subtype
                + f"/Length {len(payload)} >>\nstream\n".encode("ascii")
                + payload
                + b"\nendstream"
            ),
        ],
    )

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_reopen_gate_rejects_executable_filename_when_filespec_type_is_omitted(
    tmp_path: Path,
) -> None:
    candidate = _build_object_graph_pdf(
        tmp_path / "embedded-executable-untyped-filespec.pdf",
        [
            (
                b"<< /Type /Catalog /Pages 2 0 R /Names << /EmbeddedFiles "
                b"<< /Names [(entry) 4 0 R] >> >> >>"
            ),
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
            b"<< /F (run.exe) /EF << /F 5 0 R >> >>",
            (
                b"<< /Type /EmbeddedFile /Subtype /application#2Foctet-stream "
                b"/Length 5 >>\nstream\nplain\nendstream"
            ),
        ],
    )

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_reopen_gate_rejects_escaped_encrypt_name(tmp_path: Path) -> None:
    candidate = _build_encrypted_pdf(tmp_path / "escaped-encrypt.pdf")
    candidate.write_bytes(
        candidate.read_bytes().replace(b"/Encrypt", b"/#45ncrypt", 1)
    )

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_reopen_gate_rejects_deep_direct_value_nesting_as_archive_unsafe(
    tmp_path: Path,
) -> None:
    nested_value = b"[" * 1_500 + b"0" + b"]" * 1_500
    candidate = _build_object_graph_pdf(
        tmp_path / "deep-direct-value.pdf",
        [
            b"<< /Type /Catalog /Pages 2 0 R /Deep 4 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>",
            b"<< /Value " + nested_value + b" >>",
        ],
    )

    with pytest.raises(DocumentSkillsError) as caught:
        reopen_pdf(candidate)

    assert caught.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_pdf_create_validation_failure_preserves_existing_destination(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "existing.pdf"
    destination.write_bytes(b"existing")

    def reject(*_args, **_kwargs):
        raise DocumentSkillsError(ErrorCode.VALIDATION_FAILED, "injected validation failure")

    monkeypatch.setattr(service_module, "validate_created", reject)
    result = PdfService(project_root).execute(
        "pdf.create",
        _create_request(destination),
    )

    assert result["status"] == "failed"
    assert destination.read_bytes() == b"existing"


def test_pdf_create_destination_race_does_not_overwrite_concurrent_bytes(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "race.pdf"
    destination.write_bytes(b"snapshot")
    real_validate = service_module.validate_created

    def race(*args, **kwargs):
        report = real_validate(*args, **kwargs)
        destination.write_bytes(b"concurrent")
        return report

    monkeypatch.setattr(service_module, "validate_created", race)
    result = PdfService(project_root).execute(
        "pdf.create",
        _create_request(destination),
    )

    assert result["status"] == "failed"
    assert destination.read_bytes() == b"concurrent"


def test_pdf_create_result_identity_mismatch_fails_before_commit(
    project_root: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    destination = tmp_path / "mismatch.pdf"
    destination.write_bytes(b"existing")
    real_write = service_module.write_candidate_result

    def mismatched(*args, **kwargs):
        result = real_write(*args, **kwargs)
        result["artifacts"][-1]["sha256"] = "0" * 64
        return result

    monkeypatch.setattr(service_module, "write_candidate_result", mismatched)
    result = PdfService(project_root).execute(
        "pdf.create",
        _create_request(destination),
    )

    assert result["status"] == "failed"
    assert result["errors"][0]["details"]["candidate_identity_mismatch"] is True
    assert destination.read_bytes() == b"existing"


def _create_request(destination: Path) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "operation": "pdf.create",
        "output": str(destination),
        "arguments": {"document": _minimal_text_document("Bound create")},
    }


def _styled_document() -> dict[str, object]:
    document = _minimal_text_document("Styled text")
    page = document["pages"][0]
    page["size"] = {"width": 400.0, "height": 300.0}
    page["margin"] = {"top": 40.0, "right": 50.0, "bottom": 40.0, "left": 50.0}
    page["blocks"][0]["style"] = {
        "font_family": "Helvetica",
        "font_size": 18.0,
        "font_weight": "bold",
        "font_style": "italic",
        "color": [1.0, 0.0, 0.0],
        "line_height": 24.0,
        "alignment": "center",
    }
    return document


def _image_document(image: Path, *, fit: str = "contain") -> dict[str, object]:
    document = _minimal_text_document("Image evidence")
    document["pages"][0]["blocks"].append({
        "type": "image",
        "text": None,
        "style": None,
        "table": None,
        "image": {
            "filename": str(image),
            "content_type": "image/png",
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
            "width": 40.0,
            "height": 40.0,
            "fit": fit,
            "alt": "pixel",
        },
        "shape": None,
    })
    return document


def _shape_document() -> dict[str, object]:
    document = _minimal_text_document("Shape evidence")
    document["pages"][0]["blocks"].extend([
        {
            "type": "vector_shape",
            "text": None,
            "style": None,
            "table": None,
            "image": None,
            "shape": {
                "kind": "line",
                "x": 30.0,
                "y": 40.0,
                "width": 70.0,
                "height": 20.0,
                "stroke": [1.0, 0.0, 0.0],
                "fill": None,
                "opacity": 0.4,
                "dash": [3.0, 2.0],
            },
        },
        {
            "type": "vector_shape",
            "text": None,
            "style": None,
            "table": None,
            "image": None,
            "shape": {
                "kind": "ellipse",
                "x": 120.0,
                "y": 80.0,
                "width": 50.0,
                "height": 30.0,
                "stroke": [0.0, 0.0, 1.0],
                "fill": [0.2, 0.4, 0.6],
                "opacity": 0.6,
                "dash": [],
            },
        },
    ])
    return document


def _paginated_shape_document() -> dict[str, object]:
    document = _minimal_text_document("")
    document["page_size"] = {"width": 240.0, "height": 180.0}
    page = document["pages"][0]
    page.update({
        "overflow_policy": "paginate",
        "widow_lines": 2,
        "orphan_lines": 2,
        "margin": {
            "top": 24.0,
            "right": 24.0,
            "bottom": 24.0,
            "left": 24.0,
        },
    })
    shapes = _shape_document()["pages"][0]["blocks"][1:]
    paragraph = {
        "type": "paragraph",
        "text": " ".join(f"flow-{index:02d}" for index in range(1, 49)),
        "style": None,
        "table": None,
        "image": None,
        "shape": None,
    }
    page["blocks"] = [paragraph, shapes[0], paragraph, shapes[1]]
    return document


def _png(*, width: int = 2, height: int = 2) -> bytes:
    payload = BytesIO()
    Image.new("RGB", (width, height), "white").save(payload, format="PNG")
    return payload.getvalue()


def _alpha_png() -> bytes:
    payload = BytesIO()
    image = Image.new("RGBA", (2, 2))
    image.putdata([
        (255, 0, 0, 0),
        (0, 255, 0, 85),
        (0, 0, 255, 170),
        (255, 255, 255, 255),
    ])
    image.save(payload, format="PNG")
    return payload.getvalue()


def _build_object_graph_pdf(path: Path, objects: list[bytes]) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: list[int] = []
    for object_number, content in enumerate(objects, start=1):
        offsets.append(len(header) + len(body))
        body.extend(f"{object_number} 0 obj\n".encode("ascii"))
        body.extend(content)
        body.extend(b"\nendobj\n")

    xref_offset = len(header) + len(body)
    xref = bytearray(b"xref\n")
    xref.extend(f"0 {len(objects) + 1}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for offset in offsets:
        xref.extend(f"{offset:010d} 00000 n\r\n".encode("ascii"))
    xref.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path
