"""Metadata Info/XMP synchronization and writer safety regressions."""

import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from document_skills_core.core.contracts.errors import DocumentSkillsError, ErrorCode
from document_skills_core.formats.pdf.contracts import parse_pdf_request
from document_skills_core.formats.pdf.create import create_pdf
from document_skills_core.formats.pdf.edit import edit_pdf
from document_skills_core.formats.pdf.metadata_xmp import (
    load_linked_xmp,
    read_xmp_metadata,
)
from document_skills_core.formats.pdf.object_model import IndirectReference, PdfDict, parse_pdf
from document_skills_core.formats.pdf.projection import (
    project_info_dictionary,
    project_xmp_presence,
)
from document_skills_core.formats.pdf.validation import validate_created, validate_mutation


def test_create_emits_deterministic_unicode_info_and_catalog_linked_xmp(
    tmp_path: Path,
) -> None:
    metadata = {
        "title": '文档 & <العربية> 😀',
        "author": "作者 — مؤلف",
        "subject": "主题 \U0001F680",
    }
    document = _document(metadata)
    first = tmp_path / "unicode-first.pdf"
    second = tmp_path / "unicode-second.pdf"
    create_pdf(first, document)
    create_pdf(second, document)

    assert first.read_bytes() == second.read_bytes()
    model = parse_pdf(first)
    info = project_info_dictionary(model)
    assert {key: info[key] for key in metadata} == metadata
    linked = load_linked_xmp(model)
    assert linked is not None
    xmp = read_xmp_metadata(linked.xml)
    assert {key: xmp[key] for key in metadata} == metadata
    assert b"&amp;" in linked.xml
    assert b"&lt;" in linked.xml
    catalog = model.get_object(model.catalog_ref).value
    assert isinstance(catalog, PdfDict)
    assert catalog.get("/Metadata") == IndirectReference(
        linked.obj.obj_num,
        linked.obj.gen_num,
    )
    assert validate_created(first, document)["status"] == "pass"


def test_unicode_metadata_update_contract_accepts_cjk_rtl_and_non_bmp(
    tmp_path: Path,
) -> None:
    parsed = parse_pdf_request({
        "operation": "pdf.edit",
        "input": str(tmp_path / "source.pdf"),
        "output": str(tmp_path / "output.pdf"),
        "arguments": {
            "primitives": [{
                "type": "metadata_update",
                "metadata": {
                    "title": "中文",
                    "author": "العربية",
                    "subject": "emoji 😀",
                    "keywords": "元数据,بيانات,\U0001F680",
                },
            }],
        },
    })

    assert parsed.arguments["primitives"][0]["metadata"]["author"] == "العربية"


def test_metadata_update_replaces_hex_and_literal_info_without_duplicates(
    tmp_path: Path,
) -> None:
    source = _metadata_fixture(
        tmp_path / "hex-literal-info.pdf",
        info=(
            b"<< /Title <FEFF004F006C0064> /Author (Old\\) Author) "
            b"/Custom (keep me) >>"
        ),
    )
    output = tmp_path / "hex-literal-updated.pdf"
    requested = {
        "title": "新标题 😀",
        "author": "كاتب",
        "subject": "主题",
        "keywords": "一,اثنان",
    }
    _operation, manifest = edit_pdf(
        source,
        output,
        {"primitives": [{"type": "metadata_update", "metadata": requested}]},
    )

    model = parse_pdf(output)
    info = project_info_dictionary(model)
    assert {key: info[key] for key in requested} == requested
    linked = load_linked_xmp(model)
    assert linked is not None
    assert read_xmp_metadata(linked.xml) == requested
    info_payload = model.get_object(model.trailer.info).payload_bytes
    assert info_payload.count(b"/Title") == 1
    assert info_payload.count(b"/Author") == 1
    assert b"/Custom (keep me)" in info_payload
    assert validate_mutation(
        output,
        source=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        manifest=manifest,
    )["status"] == "pass"


def test_metadata_update_adds_info_and_xmp_when_both_are_absent(
    tmp_path: Path,
) -> None:
    source = _metadata_fixture(tmp_path / "no-metadata.pdf", info=None)
    output = tmp_path / "metadata-added.pdf"
    requested = {"title": "Added", "author": "A", "subject": "S", "keywords": "K"}
    _operation, manifest = edit_pdf(
        source,
        output,
        {"primitives": [{"type": "metadata_update", "metadata": requested}]},
    )

    model = parse_pdf(output)
    assert model.trailer.info is not None
    assert project_xmp_presence(model) is True
    linked = load_linked_xmp(model)
    assert linked is not None
    assert read_xmp_metadata(linked.xml) == requested
    assert validate_mutation(
        output,
        source=source,
        source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        manifest=manifest,
    )["status"] == "pass"


def test_metadata_validation_rejects_wrong_manifest_expectation(
    tmp_path: Path,
) -> None:
    source = _metadata_fixture(tmp_path / "validation-source.pdf", info=None)
    output = tmp_path / "validation-output.pdf"
    requested = {"title": "Actual", "author": "A"}
    _operation, manifest = edit_pdf(
        source,
        output,
        {"primitives": [{"type": "metadata_update", "metadata": requested}]},
    )
    wrong_manifest = {
        **manifest,
        "metadata_expectation": {"title": "Different", "author": "A"},
    }

    with pytest.raises(DocumentSkillsError) as captured:
        validate_mutation(
            output,
            source=source,
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
            manifest=wrong_manifest,
        )

    assert captured.value.code == ErrorCode.VALIDATION_FAILED
    assert "operation.metadata.info-xmp-sync" in captured.value.details["failed_gates"]


def test_metadata_update_preserves_unknown_xmp_elements_and_attributes(
    tmp_path: Path,
) -> None:
    xml = b'''<?xpacket begin="" id="test"?>
<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:custom="urn:test">
<rdf:RDF><rdf:Description rdf:about="" custom:flag="yes"><custom:Extra keep="1">value</custom:Extra><dc:title><rdf:Alt><rdf:li xml:lang="x-default">Old</rdf:li></rdf:Alt></dc:title></rdf:Description></rdf:RDF>
</x:xmpmeta><?xpacket end="w"?>'''
    source = _metadata_fixture(
        tmp_path / "unknown-xmp.pdf",
        info=b"<< /Title (Old) >>",
        xmp=xml,
    )
    output = tmp_path / "unknown-xmp-updated.pdf"
    requested = {
        "title": "New & <safe>",
        "author": "Author",
        "subject": "Subject",
        "keywords": "one,two",
    }
    edit_pdf(
        source,
        output,
        {"primitives": [{"type": "metadata_update", "metadata": requested}]},
    )

    linked = load_linked_xmp(parse_pdf(output))
    assert linked is not None
    root = ET.fromstring(linked.xml)
    description = root.find(
        "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}RDF/"
        "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}Description"
    )
    assert description is not None
    assert description.get("{urn:test}flag") == "yes"
    extra = description.find("{urn:test}Extra")
    assert extra is not None and extra.get("keep") == "1" and extra.text == "value"
    assert read_xmp_metadata(linked.xml) == requested


def test_projection_ignores_orphan_metadata_stream(tmp_path: Path) -> None:
    orphan_xml = b"<x:xmpmeta xmlns:x=\"adobe:ns:meta/\" />"
    source = _metadata_fixture(
        tmp_path / "orphan-xmp.pdf",
        info=None,
        xmp=orphan_xml,
        link_xmp=False,
    )

    assert project_xmp_presence(parse_pdf(source)) is False


def test_catalog_metadata_reference_requires_matching_generation(tmp_path: Path) -> None:
    xml = b'<x:xmpmeta xmlns:x="adobe:ns:meta/" />'
    source = _write_sparse_pdf(
        tmp_path / "wrong-xmp-generation.pdf",
        {
            1: (0, b"<< /Type /Catalog /Pages 2 0 R /Metadata 5 1 R >>"),
            2: (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
            3: (
                0,
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] "
                b"/Contents 4 0 R >>",
            ),
            4: (0, b"<< /Length 0 >>\nstream\n\nendstream"),
            5: (
                0,
                f"<< /Type /Metadata /Subtype /XML /Length {len(xml)} >>\nstream\n".encode("ascii")
                + xml
                + b"\nendstream",
            ),
        },
        size=6,
        root=(1, 0),
        info=None,
    )
    model = parse_pdf(source)

    assert project_xmp_presence(model) is False
    with pytest.raises(DocumentSkillsError) as captured:
        load_linked_xmp(model)
    assert captured.value.code == ErrorCode.ARCHIVE_UNSAFE


def test_metadata_writer_preserves_generations_sparse_xref_and_binary_id(
    tmp_path: Path,
) -> None:
    raw_id = b"[(\x00\xffA\\(B\\)) <00FF1020>]"
    source = _sparse_generation_pdf(tmp_path / "sparse.pdf", raw_id=raw_id)
    output = tmp_path / "sparse-updated.pdf"
    edit_pdf(
        source,
        output,
        {"primitives": [{
            "type": "metadata_update",
            "metadata": {"title": "Sparse 😀"},
        }]},
    )

    output_model = parse_pdf(output)
    assert output_model.objects[1].gen_num == 2
    assert output_model.objects[3].gen_num == 4
    assert output_model.objects[5].gen_num == 7
    assert output_model.objects[6].gen_num == 1
    assert output_model.objects[7].gen_num == 5
    assert output_model.xref_entries[2].in_use is False
    assert output_model.xref_entries[4].in_use is False
    assert b"/ID " + raw_id in output.read_bytes()
    assert b"/Root 1 2 R" in output.read_bytes()
    assert b"/Info 7 5 R" in output.read_bytes()


def test_encrypted_source_with_second_metadata_primitive_rejects_before_write(
    tmp_path: Path,
) -> None:
    source = _metadata_fixture(
        tmp_path / "encrypted.pdf",
        info=b"<< /Title (Old) >>",
        encrypt=True,
    )
    output = tmp_path / "encrypted-output.pdf"
    original_destination = b"existing destination"
    output.write_bytes(original_destination)

    with pytest.raises(DocumentSkillsError) as captured:
        edit_pdf(
            source,
            output,
            {"primitives": [
                {"type": "rotate", "pages": [1], "degrees": 90},
                {"type": "metadata_update", "metadata": {"title": "blocked"}},
            ]},
        )

    assert captured.value.code is ErrorCode.ENHANCEMENT_REQUIRED
    assert captured.value.details["capability"] == "pdf.decrypt"
    assert output.read_bytes() == original_destination


def test_encrypted_source_with_rotate_rejects_before_write(tmp_path: Path) -> None:
    source = _metadata_fixture(
        tmp_path / "encrypted-rotate.pdf",
        info=b"<< /Title (Old) >>",
        encrypt=True,
    )
    output = tmp_path / "encrypted-rotate-output.pdf"
    original_destination = b"existing destination"
    output.write_bytes(original_destination)

    with pytest.raises(DocumentSkillsError) as captured:
        edit_pdf(
            source,
            output,
            {"primitives": [{"type": "rotate", "pages": [1], "degrees": 90}]},
        )

    assert captured.value.code is ErrorCode.ENHANCEMENT_REQUIRED
    assert captured.value.details["capability"] == "pdf.decrypt"
    assert output.read_bytes() == original_destination


def _document(metadata: dict[str, str]) -> dict[str, object]:
    return {
        "metadata": metadata,
        "page_size": "A4",
        "pages": [{
            "blocks": [{
                "type": "paragraph",
                "text": "content",
                "style": None,
                "table": None,
                "image": None,
                "shape": None,
            }],
            "metadata": None,
        }],
    }


def _metadata_fixture(
    path: Path,
    *,
    info: bytes | None,
    xmp: bytes | None = None,
    link_xmp: bool = True,
    encrypt: bool = False,
) -> Path:
    catalog_extra = b""
    objects: list[tuple[int, bytes]] = [
        (0, b""),
        (0, b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"),
        (
            0,
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 300] "
            b"/Contents 4 0 R >>",
        ),
        (0, b"<< /Length 0 >>\nstream\n\nendstream"),
    ]
    info_number = None
    if info is not None:
        info_number = len(objects) + 1
        objects.append((0, info))
    if xmp is not None:
        xmp_number = len(objects) + 1
        objects.append((
            0,
            f"<< /Type /Metadata /Subtype /XML /Length {len(xmp)} >>\nstream\n".encode("ascii")
            + xmp
            + b"\nendstream",
        ))
        if link_xmp:
            catalog_extra += f" /Metadata {xmp_number} 0 R".encode("ascii")
    encrypt_number = None
    if encrypt:
        encrypt_number = len(objects) + 1
        objects.append((0, b"<< /Filter /Standard /V 1 /R 2 /Length 40 >>"))
    objects[0] = (0, b"<< /Type /Catalog /Pages 2 0 R" + catalog_extra + b" >>")
    return _write_pdf(
        path,
        objects,
        root=(1, 0),
        info=(info_number, 0) if info_number is not None else None,
        encrypt=(encrypt_number, 0) if encrypt_number is not None else None,
    )


def _sparse_generation_pdf(path: Path, *, raw_id: bytes) -> Path:
    objects = {
        1: (2, b"<< /Type /Catalog /Pages 3 4 R >>"),
        3: (4, b"<< /Type /Pages /Kids [5 7 R] /Count 1 >>"),
        5: (
            7,
            b"<< /Type /Page /Parent 3 4 R /MediaBox [0 0 200 300] "
            b"/Contents 6 1 R >>",
        ),
        6: (1, b"<< /Length 0 >>\nstream\n\nendstream"),
        7: (5, b"<< /Title (Old) /Custom (preserved) >>"),
    }
    return _write_sparse_pdf(
        path,
        objects,
        size=10,
        root=(1, 2),
        info=(7, 5),
        raw_id=raw_id,
    )


def _write_pdf(
    path: Path,
    objects: list[tuple[int, bytes]],
    *,
    root: tuple[int, int],
    info: tuple[int, int] | None,
    encrypt: tuple[int, int] | None,
) -> Path:
    return _write_sparse_pdf(
        path,
        {index: item for index, item in enumerate(objects, start=1)},
        size=len(objects) + 1,
        root=root,
        info=info,
        encrypt=encrypt,
    )


def _write_sparse_pdf(
    path: Path,
    objects: dict[int, tuple[int, bytes]],
    *,
    size: int,
    root: tuple[int, int],
    info: tuple[int, int] | None,
    encrypt: tuple[int, int] | None = None,
    raw_id: bytes | None = None,
) -> Path:
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    body = bytearray()
    offsets: dict[int, int] = {}
    for object_number, (generation, payload) in sorted(objects.items()):
        offsets[object_number] = len(header) + len(body)
        body.extend(f"{object_number} {generation} obj\n".encode("ascii"))
        body.extend(payload)
        body.extend(b"\nendobj\n")
    xref_offset = len(header) + len(body)
    xref = bytearray(f"xref\n0 {size}\n".encode("ascii"))
    xref.extend(b"0000000000 65535 f\r\n")
    for object_number in range(1, size):
        if object_number in objects:
            generation = objects[object_number][0]
            xref.extend(
                f"{offsets[object_number]:010d} {generation:05d} n\r\n".encode("ascii")
            )
        else:
            xref.extend(b"0000000000 00000 f\r\n")
    entries = [f"/Size {size}", f"/Root {root[0]} {root[1]} R"]
    if info is not None:
        entries.append(f"/Info {info[0]} {info[1]} R")
    if encrypt is not None:
        entries.append(f"/Encrypt {encrypt[0]} {encrypt[1]} R")
    trailer = " ".join(entries).encode("ascii")
    if raw_id is not None:
        trailer += b" /ID " + raw_id
    xref.extend(b"trailer\n<< " + trailer + b" >>\n")
    xref.extend(f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii"))
    path.write_bytes(header + bytes(body) + bytes(xref))
    return path
